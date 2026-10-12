#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[setup]${NC} $*"; }
warn() { echo -e "${YELLOW}[setup]${NC} $*"; }
err()  { echo -e "${RED}[setup]${NC} $*" >&2; exit 1; }

# ── Prerequisites ────────────────────────────────────────────────────────────

command -v docker   >/dev/null 2>&1 || err "Docker is not installed. See https://docs.docker.com/get-docker/"
command -v python3  >/dev/null 2>&1 || err "Python 3 is not installed."
docker compose version >/dev/null 2>&1 || err "Docker Compose plugin not found. Update Docker Desktop or install the plugin."

# ── .env ─────────────────────────────────────────────────────────────────────

if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env created from .env.example"
  warn "Open .env and set API_TOKEN and LLM_API_KEY before running the app, then re-run this script."
  exit 0
fi

grep -q "^API_TOKEN=change-me" .env && warn "API_TOKEN is still the placeholder in .env — every request will be rejected until you set it."
grep -q "^LLM_API_KEY=sk-\.\.\." .env && warn "LLM_API_KEY is still the placeholder in .env — enrichment will fail until you set it."

# ── Python virtual environment ────────────────────────────────────────────────

VENV=".venv"

if [ ! -d "$VENV" ]; then
  info "Creating Python virtual environment ($VENV)..."
  python3 -m venv "$VENV"
fi

info "Installing Python dependencies..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e . --group dev

# ── OpenSearch ────────────────────────────────────────────────────────────────

info "Starting OpenSearch via Docker Compose..."
docker compose up -d

info "Waiting for OpenSearch to be ready..."
until curl -sf http://localhost:9200/_cluster/health >/dev/null 2>&1; do
  printf '.'
  sleep 2
done
echo

# ── Done ──────────────────────────────────────────────────────────────────────

echo
info "Setup complete. To start the app:"
echo
echo "  source $VENV/bin/activate"
echo "  uvicorn kb.app:app --reload"
echo
echo "The items/versions indices are created on first start."
echo "OpenSearch Dashboards: http://localhost:5601"
