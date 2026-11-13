#!/usr/bin/env bash
# Nakeeb AI - Local Development Runner
# Runs the pipeline locally with proper environment setup

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[RUN]${NC} $*"; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }

cd "${REPO_ROOT}"

# Check .env
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        log "No .env found. Copying from .env.example..."
        cp .env.example .env
        echo
        info "Please edit .env with your API keys:"
        info "  - GEMINI_API_KEY (primary)"
        info "  - OPENROUTER_API_KEY (fallback)"
        info "  - HF_API_KEY (optional)"
        info "  - GH_PAT_DISPATCH (GitHub fine-grained PAT)"
        info "  - BOT_TOKEN, ADMIN_USER_ID (Telegram, optional)"
        echo
        read -p "Press Enter after editing .env, or Ctrl+C to exit..."
    else
        error "No .env.example found!"
        exit 1
    fi
fi

# Load env
set -a
source .env
set +a

# Check Python
if ! command -v python3 &> /dev/null; then
    error "python3 not found"
    exit 1
fi

# Install dependencies if needed
if [ ! -d ".venv" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
    log "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else:
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        info "Using existing virtual environment: ${VIRTUAL_ENV}"
    else:
        info "Using system Python (consider using .venv)"
    fi
fi

# Parse arguments
DRY_RUN=true
SINCE_HOURS=24
PROFILE="both"
MAX_ITEMS=100

while [[ $# -gt 0 ]]; do
    case $1 in
        --publish)
            DRY_RUN=false
            shift
            ;;
        --since-hours)
            SINCE_HOURS="$2"
            shift 2
            ;;
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --max-items)
            MAX_ITEMS="$2"
            shift 2
            ;;
        --rebuild)
            log "Rebuilding database..."
            python -m src.rebuild_db
            exit 0
            ;;
        --test)
            log "Running tests..."
            python -m pytest tests/ -v
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--publish] [--since-hours N] [--profile PROFILE] [--max-items N] [--rebuild] [--test]"
            exit 1
            ;;
    esac
done

# Run pipeline
log "Starting pipeline (dry_run=${DRY_RUN}, since_hours=${SINCE_HOURS}, profile=${PROFILE})"
python -m src.cli run \
    --dry-run "${DRY_RUN}" \
    --since-hours "${SINCE_HOURS}" \
    --profile "${PROFILE}" \
    --max-items "${MAX_ITEMS}"