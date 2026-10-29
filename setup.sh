#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[setup]${NC} $*"; }
warn() { echo -e "${YELLOW}[setup]${NC} $*"; }
err()  { echo -e "${RED}[setup]${NC} $*" >&2; exit 1; }

OPENSEARCH=http://localhost:9201
APP=http://localhost:8000
JSON='Content-Type: application/json'

# ── Prerequisites ────────────────────────────────────────────────────────────

command -v docker   >/dev/null 2>&1 || err "Docker is not installed. See https://docs.docker.com/get-docker/"
command -v python3  >/dev/null 2>&1 || err "Python 3 is not installed."
command -v npm      >/dev/null 2>&1 || err "Node.js is not installed; the web app is built with it (Node 24)."
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

# ── Python virtual environment (tests and tools; the app itself runs in Docker) ──

VENV=".venv"

if [ ! -d "$VENV" ]; then
  info "Creating Python virtual environment ($VENV)..."
  python3 -m venv "$VENV"
fi

info "Installing Python dependencies..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e . --group dev

# ── OpenSearch + app ─────────────────────────────────────────────────────────

env_value() { grep -E "^$1=" .env | cut -d= -f2- | tr -d '"' || true; }

BACKUP_DIR=$(env_value KB_BACKUP_DIR)
mkdir -p "${BACKUP_DIR:-./backups}"

INDEX_PREFIX=$(env_value OPENSEARCH_INDEX_PREFIX)
INDICES="${INDEX_PREFIX}items,${INDEX_PREFIX}versions,${INDEX_PREFIX}taxonomy"

info "Building and starting OpenSearch and the app via Docker Compose..."
docker compose up -d --build

info "Waiting for the app (it creates the indices on start)..."
until curl -sf "$APP/health" >/dev/null 2>&1; do
  printf '.'
  sleep 2
done
echo

# One node: no replicas, so the indices are green rather than yellow.
curl -sf -X PUT "$OPENSEARCH/$INDICES/_settings" -H "$JSON" \
  -d '{"index.number_of_replicas": 0}' >/dev/null

# ── Web app: built into web/dist, which the app serves at /app ───────────────

# The build generates the API types from the running app's /openapi.json, so it comes after the app is up.
info "Building the web app..."
(cd web && npm ci --silent && npm run build --silent >/dev/null)

# ── Backups: snapshot repository + snapshot-management policy ────────────────

info "Configuring backups into ${BACKUP_DIR:-./backups}..."
curl -sf -X PUT "$OPENSEARCH/_snapshot/kb-backups" -H "$JSON" \
  -d '{"type": "fs", "settings": {"location": "/usr/share/opensearch/snapshots"}}' >/dev/null

# Every 2 hours, so a PC that is off at some hours still gets snapshots; kept 14 days.
if ! curl -sf "$OPENSEARCH/_plugins/_sm/policies/kb-backups" >/dev/null 2>&1; then
  curl -sf -X POST "$OPENSEARCH/_plugins/_sm/policies/kb-backups" -H "$JSON" -d '{
    "description": "KB backups: every 2 hours, kept 14 days",
    "creation": {"schedule": {"cron": {"expression": "0 */2 * * *", "timezone": "UTC"}}},
    "deletion": {
      "schedule": {"cron": {"expression": "30 */2 * * *", "timezone": "UTC"}},
      "condition": {"max_age": "14d", "min_count": 1}
    },
    "snapshot_config": {"repository": "kb-backups", "indices": "'"$INDICES"'", "include_global_state": false},
    "enabled": true
  }' >/dev/null
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo
info "Setup complete. The Knowledge Base runs at $APP and restarts with Docker."
echo
echo "  Start Docker Desktop at sign-in (Settings → General) so it is always up."
echo "  Code changes in kb/ reload live; after changing dependencies run: docker compose up -d --build"
echo "  The web app (/app) is live after: cd web && npm run build"
echo "  Logs: docker compose logs -f app"
