#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Fazle Core — external dependency / stack check
#
# Read-only. Starts nothing, changes nothing. Prints one line per dependency
# with the verdict and the exact command to verify it by hand.
#
#   bash scripts/check_stack.sh            # core + optional deps
#   bash scripts/check_stack.sh --core     # only what fazle-core REQUIRES
#
# Exit code: 0 when every REQUIRED dependency is healthy, 1 otherwise.
# Optional dependencies never change the exit code — they are informational.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

CORE_ONLY=0
[ "${1:-}" = "--core" ] && CORE_ONLY=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ -t 1 ]; then
  G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
else
  G=""; Y=""; R=""; D=""; N=""
fi

FAILED=0
WARNED=0

# verdict <OK|OPTIONAL|WARN|REQUIRED-FAIL> <name> <detail>
verdict() {
  case "$1" in
    OK)            printf '  %s✔ OK%s        %-22s %s\n' "$G" "$N" "$2" "$3" ;;
    OPTIONAL)      printf '  %s– absent%s    %-22s %s\n' "$D" "$N" "$2" "$3" ;;
    WARN)          printf '  %s! %-9s%s %-22s %s\n' "$Y" "$1" "$N" "$2" "$3"; WARNED=$((WARNED+1)) ;;
    REQUIRED-FAIL) printf '  %s✘ %-9s%s %-22s %s\n' "$R" "$1" "$N" "$2" "$3"; FAILED=$((FAILED+1)) ;;
  esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# probe <url> -> prints HTTP status code, empty on connection failure
probe() {
  if have curl; then
    curl -s -o /dev/null -m 3 -w '%{http_code}' "$1" 2>/dev/null
  elif have python3; then
    python3 - "$1" <<'PY' 2>/dev/null
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as r:
        print(r.status)
except Exception as e:
    print(getattr(e, "code", ""))
PY
  fi
}

env_val() { # read one key from .env without sourcing it
  [ -f .env ] || return 0
  grep -E "^[[:space:]]*$1[[:space:]]*=" .env 2>/dev/null | tail -1 | \
    sed -E "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//; s/\r$//; s/^[\"']//; s/[\"']$//"
}

echo
echo "Fazle Core — stack check   ($(date '+%Y-%m-%d %H:%M:%S %Z'))"
echo "repo: $ROOT"
echo

# ── 1. Runtime & repo ────────────────────────────────────────────────────────
echo "RUNTIME"
if have python3; then
  PYV="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)"
  case "$PYV" in
    3.10.*|3.11.*|3.12.*) verdict OK python "$PYV (supported: 3.10–3.11 recommended)" ;;
    *) verdict WARN python "$PYV — README supports 3.10/3.11" ;;
  esac
else
  verdict REQUIRED-FAIL python "python3 not found"
fi

PYBIN="python3"
[ -x venv/bin/python ] && PYBIN=venv/bin/python
[ -x .venv/bin/python ] && PYBIN=.venv/bin/python
if [ "$PYBIN" != "python3" ]; then
  verdict OK venv "$PYBIN"
else
  verdict WARN venv "no venv/ or .venv/ found — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

MISSING="$("$PYBIN" - <<'PY' 2>/dev/null
import importlib.util
mods = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "pydantic_settings": "pydantic-settings",
    "asyncpg": "asyncpg", "httpx": "httpx", "yaml": "PyYAML", "apscheduler": "APScheduler",
    "openai": "openai",
}
print(",".join(pkg for mod, pkg in mods.items() if importlib.util.find_spec(mod) is None))
PY
)"
if [ -z "$MISSING" ]; then
  verdict OK "python deps" "core imports resolvable"
else
  verdict REQUIRED-FAIL "python deps" "missing: $MISSING  →  pip install -r requirements.txt"
fi

if [ -f .env ]; then
  PERM="$(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env 2>/dev/null || echo '')"
  if [ -n "$PERM" ] && [ "$PERM" != "600" ] && [ "$PERM" != "640" ]; then
    verdict WARN ".env" "present but mode $PERM — chmod 600 .env"
  else
    verdict OK ".env" "present (mode ${PERM:-unknown})"
  fi
else
  verdict REQUIRED-FAIL ".env" "missing — cp .env.example .env && chmod 600 .env"
fi

DB_URL="${DATABASE_URL:-$(env_val DATABASE_URL)}"
if [ -z "$DB_URL" ]; then
  verdict REQUIRED-FAIL "DATABASE_URL" "not set — the app cannot start without PostgreSQL"
else
  if "$PYBIN" - "$DB_URL" <<'PY' >/dev/null 2>&1
import asyncio, sys
import asyncpg
async def main():
    conn = await asyncpg.connect(sys.argv[1], timeout=4)
    await conn.execute("SELECT 1")
    await conn.close()
asyncio.run(main())
PY
  then
    verdict OK "PostgreSQL" "connect OK"
  else
    verdict REQUIRED-FAIL "PostgreSQL" "cannot connect with DATABASE_URL — pg_isready / check credentials"
  fi
fi

# ── 2. Optional services ─────────────────────────────────────────────────────
if [ "$CORE_ONLY" -eq 0 ]; then
  echo
  echo "OPTIONAL SERVICES  (absent only disables that feature)"

  REDIS_URL="${REDIS_URL:-$(env_val REDIS_URL)}"
  if have redis-cli && [ -n "$REDIS_URL" ]; then
    HOSTPORT="$(printf '%s' "$REDIS_URL" | sed -E 's#^redis://([^/]*).*#\1#')"
    RIP="${HOSTPORT%%:*}"
    RPT="${HOSTPORT##*:}"; [ "$RPT" = "$RIP" ] && RPT=6379
    if [ "$(redis-cli -h "${RIP:-127.0.0.1}" -p "${RPT:-6379}" ping 2>/dev/null)" = "PONG" ]; then
      verdict OK redis "PONG ($HOSTPORT)"
    else
      verdict OPTIONAL redis "no PONG — in-memory fallback used"
    fi
  else
    verdict OPTIONAL redis "redis-cli not installed / REDIS_URL unset — app runs without it"
  fi

  OLLAMA_URL="${OLLAMA_URL:-$(env_val OLLAMA_URL)}"; OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  if [ "$(probe "$OLLAMA_URL/api/tags")" = "200" ]; then
    MODEL="${OLLAMA_MODEL:-$(env_val OLLAMA_MODEL)}"; MODEL="${MODEL:-hermes3:3b}"
    if curl -s -m 3 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "${MODEL%%:*}"; then
      verdict OK ollama "$OLLAMA_URL ($MODEL provisioned)"
    else
      verdict WARN ollama "$OLLAMA_URL reachable but '$MODEL' not listed — ollama pull $MODEL"
    fi
  else
    verdict OPTIONAL ollama "not reachable at $OLLAMA_URL — local AI fallback unavailable"
  fi

  OMN="${OMNIROUTE_URL:-$(env_val OMNIROUTE_URL)}"; OMN="${OMN:-http://127.0.0.1:20128/v1}"
  if [ -n "$(probe "${OMN%/}/models")" ] && [ "$(probe "${OMN%/}/models")" != "000" ]; then
    verdict OK omniroute "$OMN"
  else
    verdict OPTIONAL omniroute "not reachable — reply chain falls through to Ollama"
  fi

  B1="${BRIDGE1_URL:-$(env_val BRIDGE1_URL)}"; B1="${B1:-http://127.0.0.1:8082}"
  B2="${BRIDGE2_URL:-$(env_val BRIDGE2_URL)}"; B2="${B2:-http://127.0.0.1:8081}"
  B3="${BRIDGE3_URL:-$(env_val BRIDGE3_URL)}"; B3="${B3:-http://127.0.0.1:8083}"
  UP=0
  for pair in "bridge1 $B1" "bridge2 $B2" "bridge3 $B3"; do
    NAME="${pair%% *}"; URL="${pair#* }"
    CODE="$(probe "${URL%/}/health")"
    if [ "$CODE" = "200" ]; then UP=$((UP+1)); fi
  done
  if [ "$UP" -eq 3 ]; then
    verdict OK bridges "all three /health OK"
  elif [ "$UP" -gt 0 ]; then
    verdict WARN bridges "$UP/3 responding — conversation continuity degrades"
  else
    verdict OPTIONAL bridges "none responding — no inbound/outbound WhatsApp traffic"
  fi

  for pair in "bridge1_db $(env_val BRIDGE1_DB_PATH)" "bridge2_db $(env_val BRIDGE2_DB_PATH)" "bridge3_db $(env_val BRIDGE3_DB_PATH)"; do
    NAME="${pair%% *}"; P="${pair#* }"
    [ -z "$P" ] && continue
    if [ -r "$P" ]; then
      verdict OK "$NAME" "readable: $P"
    else
      verdict WARN "$NAME" "not readable: $P — inbound polling will find nothing"
    fi
  done

  HR="${HERMES_RUNNER_URL:-$(env_val HERMES_RUNNER_URL)}"; HR="${HR:-http://127.0.0.1:8093}"
  if [ "$(probe "${HR%/}/health")" = "200" ]; then
    verdict OK hermes-runner "$HR"
  else
    verdict OPTIONAL hermes-runner "not reachable — admin HERMES relay + customer dispatch fail closed"
  fi

  HSEC="${HERMES_RUNNER_SECRET:-$(env_val HERMES_RUNNER_SECRET)}"
  if [ -n "$HSEC" ]; then
    verdict OK hermes-secrets "HERMES_RUNNER_SECRET set"
  else
    verdict OPTIONAL hermes-secrets "unset — Hermes paths stay off (safe default)"
  fi

  MP="${MEDIA_PROCESSOR_URL:-$(env_val MEDIA_PROCESSOR_URL)}"; MP="${MP:-http://127.0.0.1:8090}"
  if [ "$(probe "${MP%/}/health")" = "200" ]; then
    verdict OK media-processor "$MP"
  else
    verdict OPTIONAL media-processor "not reachable — media stays media_unprocessed"
  fi

  QH="${QDRANT_HOST:-$(env_val QDRANT_HOST)}"
  if [ -n "$QH" ]; then
    if [ "$(probe "http://$QH:${QDRANT_PORT:-6333}/healthz")" = "200" ]; then
      verdict OK qdrant "$QH"
    else
      verdict OPTIONAL qdrant "QDRANT_HOST set but unreachable — RAG falls back to BM25"
    fi
  else
    verdict OPTIONAL qdrant "no QDRANT_HOST — embedded/BM25 retrieval only"
  fi
fi

# ── 3. fazle-core itself ─────────────────────────────────────────────────────
echo
echo "FAZLE CORE"
PORT="${APP_PORT:-$(env_val APP_PORT)}"; PORT="${PORT:-8200}"
CODE="$(probe "http://127.0.0.1:${PORT}/health")"
if [ "$CODE" = "200" ]; then
  verdict OK "core :$PORT" "/health 200"
elif [ "$CODE" = "503" ]; then
  verdict WARN "core :$PORT" "/health 503 — running but degraded (check DB/Redis)"
else
  verdict OPTIONAL "core :$PORT" "not running — start: $PYBIN -m uvicorn app.main:app --host 127.0.0.1 --port $PORT"
fi

if [ -n "${DB_URL:-}" ]; then
  PENDING="$("$PYBIN" db/migrate.py --dry-run 2>&1 | grep -c 'pending' || true)"
  if [ "${PENDING:-0}" -gt 0 ]; then
    verdict WARN migrations "$PENDING pending — run: $PYBIN db/migrate.py"
  elif [ -n "$PENDING" ]; then
    verdict OK migrations "schema up to date"
  fi
fi

OUTB="$(env_val OUTBOUND_ENABLED)"; AR="$(env_val AUTO_REPLY_ENABLED)"
case "${OUTB:-false}" in
  1|true|TRUE|yes) verdict WARN "operating mode" "OUTBOUND_ENABLED=true — real WhatsApp sends are live" ;;
  *)               verdict OK "operating mode" "OUTBOUND_ENABLED=false (safe), AUTO_REPLY_ENABLED=${AR:-false}" ;;
esac

echo
if [ "$FAILED" -gt 0 ]; then
  echo "${R}${FAILED} required dependency problem(s).${N} The app will not run until these are fixed."
  echo "See docs/SETUP_BN.md (Bengali) or README §4 for the full install path."
  exit 1
fi
echo "${G}All required dependencies look healthy.${N} Optional gaps: ${WARNED} warning(s)."
echo "Dashboard: http://127.0.0.1:${PORT}/   Health: http://127.0.0.1:${PORT}/health"
exit 0
