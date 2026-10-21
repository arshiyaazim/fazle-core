#!/usr/bin/env bash
# Local CI runner — mirrors .github/workflows/ci.yml.
# Run from repo root:  bash scripts/run_ci.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PY:-venv/bin/python}"
if [[ ! -x "$PY" ]]; then
    PY="python3"
fi

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[1;32m✔\033[0m %s\n" "$*"; }
fail() { printf "  \033[1;31m✘\033[0m %s\n" "$*"; exit 1; }

step "Python: $($PY --version)"

step "compileall (syntax)"
"$PY" -m compileall -q app modules scripts && ok "syntax clean"

step "pyflakes (warnings only; fails on undefined names)"
if "$PY" -m pyflakes --version >/dev/null 2>&1; then
    "$PY" -m pyflakes app modules > /tmp/_pyflakes.txt 2>&1 || true
    UND=$(grep -cE "undefined name" /tmp/_pyflakes.txt || true)
    WARN=$(wc -l < /tmp/_pyflakes.txt | tr -d ' ')
    if [[ "$UND" -gt 0 ]]; then
        echo "--- undefined names ---"
        grep -E "undefined name" /tmp/_pyflakes.txt
        fail "pyflakes found $UND undefined name(s)"
    fi
    ok "pyflakes ok ($WARN total warnings, 0 undefined)"
else
    echo "  (pyflakes not installed — skipping)"
fi

step "import smoke"
"$PY" -c "from modules import observability as o; o.inc('x'); assert o.snapshot()['counters']['x']" && ok "observability import"
"$PY" -c "import modules.fazle_intent, modules.scheduler, modules.outbound" && ok "module imports"

step "Batch 22 observability test (offline, no services)"
"$PY" scripts/test_batch22_observability.py

step "OPTIONAL — live integration tests (require running fazle-core + DB)"
if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8200/health; then
    ok "fazle-core is up — running live test suite"
    LIVE_TESTS=(
        scripts/test_batch19_rbac.py
        scripts/test_batch21_rag.py
    )
    for t in "${LIVE_TESTS[@]}"; do
        if [[ -f "$t" ]]; then
            echo "  → $t"
            "$PY" "$t" || fail "$t"
        fi
    done
    ok "live tests passed"
else
    echo "  (fazle-core not reachable on 127.0.0.1:8200 — skipping live tests)"
fi

printf "\n\033[1;32m✅ CI passed\033[0m\n"
