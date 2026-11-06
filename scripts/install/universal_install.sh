#!/usr/bin/env bash
# Fazle Core — Universal Installer (any PC / VPS)
# Usage:
#   bash scripts/install/universal_install.sh
# Non-interactive:
#   INTERNAL_API_KEY=xxx ADMIN_NUMBERS=88017... BRIDGE_REGISTRY_JSON='[...]' bash scripts/install/universal_install.sh --yes

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

YES=0
if [[ "${1:-}" == "--yes" ]]; then YES=1; fi

say() { echo -e "  $1"; }
ok()  { echo -e "✓ $1"; }
warn(){ echo -e "⚠ $1" >&2; }

if [[ $EUID -eq 0 ]]; then warn "Running as root — prefer a normal user with sudo"; fi

# ── Detect OS ──────────────────────────────────────────────────────────────────
OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
  if command -v apt-get >/dev/null 2>&1; then PKG="apt"; elif command -v dnf >/dev/null 2>&1; then PKG="dnf"; elif command -v pacman >/dev/null 2>&1; then PKG="pacman"; else PKG="unknown"; fi
else PKG="brew";
fi
say "OS: $OS ($PKG)  dir: $ROOT_DIR"

# ── 1. System deps ───────────────────────────────────────────────────────────
if [[ "$PKG" == "apt" ]]; then
  say "Checking system packages (apt)..."
  sudo apt-get update -qq
  sudo apt-get install -y python3 python3-venv python3-pip curl git sqlite3 >/dev/null
  ok "System packages ok"
elif [[ "$PKG" == "brew" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then warn "Install Python 3.11+ via brew: brew install python@3.11"; fi
fi

# ── 2. Python venv ───────────────────────────────────────────────────────────
if [[ ! -d venv ]]; then
  python3 -m venv venv
  ok "venv created"
fi
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
ok "Python deps installed"

# ── 3. .env wizard ───────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then cp .env.example .env; ok ".env created from .env.example"; else touch .env; fi
fi

need() {
  local key="$1" prompt="$2" def="$3" cur
  cur="$(grep -E "^${key}=" .env 2>/dev/null | cut -d= -f2- | tail -n1 || true)"
  # already set via env var? prefer that
  if [[ -n "${!key:-}" ]]; then cur="${!key}"; fi
  if [[ -n "$cur" && "$cur" != "" ]]; then say "$key already set"; return; fi
  local val="$def"
  if [[ $YES -eq 0 ]]; then
    read -rp "$prompt [$def]: " inp
    val="${inp:-$def}"
  fi
  # upsert into .env
  if grep -qE "^${key}=" .env 2>/dev/null; then
    # escape for sed
    esc="$(printf '%s' "$val" | sed 's/[\/&]/\\&/g')"
    sed -i "s|^${key}=.*|${key}=${esc}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

say ""
say "=== .env wizard (press Enter to keep default, Ctrl-C to edit manually) ==="
need "DATABASE_URL" "DATABASE_URL" "postgresql://fazle:fazle_local_password@127.0.0.1:5432/fazle_core"
# generate key if empty
CUR_KEY="$(grep -E '^INTERNAL_API_KEY=' .env | cut -d= -f2- | tail -n1 || true)"
if [[ -z "$CUR_KEY" ]]; then
  GEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  need "INTERNAL_API_KEY" "INTERNAL_API_KEY" "$GEN"
else
  say "INTERNAL_API_KEY already set"
fi
need "ADMIN_NUMBERS" "ADMIN_NUMBERS (comma, 880…)" ""
need "BRIDGE_REGISTRY_JSON" "BRIDGE_REGISTRY_JSON (JSON array or empty for legacy BRIDGE1 vars)" ""
need "APP_PORT" "APP_PORT" "8200"
ok ".env ready — edit .env manually for any other key"

# ── 4. Database ──────────────────────────────────────────────────────────────
say ""
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  say "Docker available — you can run: docker-compose up -d postgres redis"
  if [[ $YES -eq 1 ]]; then
    docker-compose up -d postgres redis 2>/dev/null || docker compose up -d postgres redis || true
    ok "postgres+redis via Docker"
  else
    read -rp "Start postgres+redis via Docker now? [y/N]: " yn
    if [[ "$yn" =~ ^[yY] ]]; then
      docker-compose up -d postgres redis 2>/dev/null || docker compose up -d postgres redis || true
      ok "postgres+redis started"
    else
      warn "Skipped Docker DB — ensure DATABASE_URL points to a live Postgres"
    fi
  fi
else
  warn "Docker not found — install Postgres 15+ and Redis, or run this on a PC with Docker"
fi

# ── 5. Migrate ───────────────────────────────────────────────────────────────
say ""
if [[ -f db/migrate.py ]]; then
  say "Running DB migrations..."
  # migrate.py reads DATABASE_URL from .env
  venv/bin/python db/migrate.py 2>&1 | tail -n 50 || warn "migrate.py failed — check DATABASE_URL and Postgres"
  ok "migrations attempted"
elif [[ -f db/migrate.py ]]; then
  venv/bin/python -m db.migrate || warn "migration failed"
else
  warn "No db/migrate.py found — run migrations manually"
fi

# ── 6. Logs dir ──────────────────────────────────────────────────────────────
mkdir -p logs
ok "logs/ ready"

# ── 7. Systemd (optional, VPS only) ─────────────────────────────────────────
if [[ -f fazle-core.service ]] && command -v systemctl >/dev/null 2>&1; then
  if [[ $YES -eq 0 ]]; then
    read -rp "Install systemd service (fazle-core.service)? [y/N]: " yn
    if [[ "$yn" =~ ^[yY] ]]; then
      sudo cp fazle-core.service /etc/systemd/system/
      # Patch WorkingDirectory/EnvironmentFile to this ROOT_DIR
      sudo sed -i "s|^WorkingDirectory=.*|WorkingDirectory=${ROOT_DIR}|" /etc/systemd/system/fazle-core.service
      sudo sed -i "s|^EnvironmentFile=.*|EnvironmentFile=${ROOT_DIR}/.env|" /etc/systemd/system/fazle-core.service || true
      sudo systemctl daemon-reload
      sudo systemctl enable fazle-core
      sudo systemctl restart fazle-core
      ok "systemd installed — tail logs: journalctl -u fazle-core -f"
    fi
  fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────
say ""
ok "Install complete!"
say "  Dashboard: http://localhost:8200/  (or /static/wa-bridges.html, /static/setup-identity.html)"
say "  Health:    curl http://localhost:\$(grep APP_PORT .env | cut -d= -f2)/health | jq"
say "  Run dev:   venv/bin/python run.py"
say "  Docker:    docker-compose up -d  (app + postgres + redis)"
say "  Bridges:   open http://localhost:8200/static/wa-bridges.html → Add bridge → Test → History Sync"
say "  Identity:  open http://localhost:8200/static/setup-identity.html → set your admin numbers + contacts CSV"
say ""
say "Next: edit .env BRIDGE_REGISTRY_JSON, then POST /api/bridges or use the UI"
