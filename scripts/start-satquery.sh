#!/usr/bin/env bash
# SatQuery AI - one-click local launcher (macOS / Linux)
# Checks requirements, installs missing deps when possible, starts API + UI.
#
# Double-click:  START_SATQUERY.command
# Or run:        ./scripts/start-satquery.sh

set -euo pipefail

SKIP_OLLAMA=0
SKIP_BROWSER=0
BACKEND_PORT=8000
FRONTEND_PORT=3000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ollama) SKIP_OLLAMA=1; shift ;;
    --skip-browser) SKIP_BROWSER=1; shift ;;
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
ROUTER_DIR="$REPO_ROOT/router"
VENV_DIR="$BACKEND_DIR/.venv"
REQ_LITE="$BACKEND_DIR/requirements-lite.txt"
ENV_LOCAL="$FRONTEND_DIR/.env.local"
LOG_DIR="$REPO_ROOT/scripts/logs"
STATE_FILE="$LOG_DIR/last-run.json"

FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
OLLAMA_URL="http://127.0.0.1:11434"
OLLAMA_MODEL="qwen3:4b-instruct"

BACKEND_PID=""
FRONTEND_PID=""
OLLAMA_PID=""

mkdir -p "$LOG_DIR"

banner() { echo; echo "================================================================"; echo "  $1"; echo "================================================================"; }
step()   { echo; echo ">> $1"; }
ok()     { echo "   [OK]  $1"; }
warn()   { echo "   [!]   $1"; }
fail()   { echo "   [X]   $1"; FAILURES+=("$1"); }
info()   { echo "   ...  $1"; }

FAILURES=()
WARNINGS=()

have_cmd() { command -v "$1" >/dev/null 2>&1; }

wait_http() {
  local url="$1" timeout="${2:-90}" label="${3:-service}"
  local start
  start=$(date +%s)
  while true; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    if (( $(date +%s) - start >= timeout )); then
      fail "$label did not become ready at $url within ${timeout}s"
      return 1
    fi
    sleep 2
  done
}

free_port() {
  local port="$1"
  if have_cmd lsof; then
    local pids
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [[ -n "${pids}" ]]; then
      info "Port $port in use - stopping: $pids"
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 1
    fi
  fi
}

cleanup() {
  echo
  echo "Shutting down SatQuery processes..."
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  # child trees
  [[ -n "$FRONTEND_PID" ]] && pkill -P "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$BACKEND_PID" ]] && pkill -P "$BACKEND_PID" 2>/dev/null || true
  echo "Stopped."
}
trap cleanup EXIT INT TERM

try_brew_install() {
  local formula="$1" label="$2"
  if ! have_cmd brew; then
    warn "Homebrew not available - cannot auto-install $label"
    return 1
  fi
  info "Installing $label via Homebrew ($formula)..."
  brew install "$formula" || return 1
  return 0
}

banner "SatQuery AI - One-Click Local Setup"
echo "Repo: $REPO_ROOT"

# 1 folders
step "1/8  Checking project folders"
for pair in "Backend|$BACKEND_DIR" "Frontend|$FRONTEND_DIR" "Router|$ROUTER_DIR"; do
  name="${pair%%|*}"
  path="${pair#*|}"
  if [[ -d "$path" ]]; then ok "$name"
  else fail "$name missing: $path"
  fi
done
if (( ${#FAILURES[@]} > 0 )); then
  echo "SETUP FAILED: required folders missing"; exit 1
fi

# 2 requirements
step "2/8  Checking system requirements"

PYTHON_BIN=""
if have_cmd python3; then
  PYVER=$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
  MAJOR=${PYVER%%.*}
  MINOR=${PYVER#*.}
  if [[ -n "$MAJOR" && ( "$MAJOR" -gt 3 || ( "$MAJOR" -eq 3 && "$MINOR" -ge 11 ) ) ]]; then
    PYTHON_BIN="python3"
    ok "Python $PYVER found"
  else
    warn "Python $PYVER is too old (need 3.11+)"
  fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
  warn "Python 3.11+ not found - attempting brew install..."
  try_brew_install "python@3.12" "Python 3.12" || true
  hash -r 2>/dev/null || true
  if have_cmd python3; then
    PYTHON_BIN="python3"
    ok "Python installed: $($PYTHON_BIN --version 2>&1)"
  else
    fail "Install Python 3.12+ (https://www.python.org/downloads/ or brew install python@3.12), then re-run."
  fi
fi

if have_cmd node; then
  ok "Node.js $(node --version)"
else
  warn "Node.js not found - attempting brew install..."
  try_brew_install "node" "Node.js" || true
  hash -r 2>/dev/null || true
  if have_cmd node; then ok "Node.js $(node --version)"
  else fail "Install Node.js LTS from https://nodejs.org/ then re-run."
  fi
fi
if have_cmd npm; then ok "npm $(npm --version)"
elif have_cmd node; then fail "npm missing - repair/reinstall Node.js"
fi

OLLAMA_OK=0
if [[ "$SKIP_OLLAMA" -eq 0 ]]; then
  if have_cmd ollama; then
    ok "Ollama found"; OLLAMA_OK=1
  else
    warn "Ollama not found - attempting brew cask install..."
    if have_cmd brew; then
      brew install --cask ollama || true
      hash -r 2>/dev/null || true
    fi
    if have_cmd ollama; then ok "Ollama installed"; OLLAMA_OK=1
    else warn "Ollama missing - planner will use rule-based fallback. Install from https://ollama.com/download"
    fi
  fi
else
  info "Skipping Ollama (--skip-ollama)"
fi

if (( ${#FAILURES[@]} > 0 )); then
  echo "SETUP FAILED: fix requirements above"; exit 1
fi

# 3 backend
step "3/8  Backend virtualenv + Python packages"
[[ -f "$REQ_LITE" ]] || { fail "Missing $REQ_LITE"; exit 1; }
ok "requirements-lite.txt present"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  info "Creating venv..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "venv created"
else
  ok "venv already exists"
fi

info "Installing / verifying Python packages..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$REQ_LITE" -q
ok "Backend dependencies ready"

export USE_SHIVEN_ROUTER=true
export SKIP_MODEL_INFERENCE=true
export SHIVEN_ROUTER_ROOT="$ROUTER_DIR"
export OLLAMA_BASE_URL="$OLLAMA_URL"
export OLLAMA_PLANNER_MODEL="$OLLAMA_MODEL"

# 4 frontend
step "4/8  Frontend .env + npm packages"
echo "NEXT_PUBLIC_API_URL=$BACKEND_URL" > "$ENV_LOCAL"
ok "frontend/.env.local -> NEXT_PUBLIC_API_URL=$BACKEND_URL"

pushd "$FRONTEND_DIR" >/dev/null
if [[ ! -d "node_modules/next" ]]; then
  info "Running npm install (first run can take several minutes)..."
  npm install
  ok "Frontend dependencies installed"
else
  ok "node_modules present - refreshing..."
  npm install --prefer-offline
  ok "Frontend dependencies verified"
fi
popd >/dev/null

# 5 ollama model
step "5/8  Ollama planner model ($OLLAMA_MODEL)"
if [[ "$OLLAMA_OK" -eq 1 && "$SKIP_OLLAMA" -eq 0 ]]; then
  if curl -fsS --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    ok "Ollama API already running"
  else
    info "Starting Ollama serve..."
    # On macOS, opening the app is often enough; also try CLI serve.
    if [[ -d "/Applications/Ollama.app" ]]; then
      open -a Ollama || true
    fi
    nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    wait_http "$OLLAMA_URL/api/tags" 60 "Ollama" && ok "Ollama API ready" || true
  fi
  if curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
      ok "Model already downloaded: $OLLAMA_MODEL"
    else
      info "Downloading $OLLAMA_MODEL (large download - please wait)..."
      if ollama pull "$OLLAMA_MODEL"; then ok "Model ready: $OLLAMA_MODEL"
      else warn "Could not pull $OLLAMA_MODEL - rule fallback will be used"
      fi
    fi
  fi
else
  warn "Ollama unavailable - Debug panel will show planner fallback when used"
fi

# 6 backend start
step "6/8  Starting FastAPI backend on :$BACKEND_PORT"
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

UVICORN="$VENV_DIR/bin/uvicorn"
[[ -x "$UVICORN" ]] || { fail "uvicorn missing in venv"; exit 1; }

(
  cd "$BACKEND_DIR"
  export USE_SHIVEN_ROUTER SKIP_MODEL_INFERENCE SHIVEN_ROUTER_ROOT OLLAMA_BASE_URL OLLAMA_PLANNER_MODEL
  exec "$UVICORN" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$LOG_DIR/backend.log" 2>"$LOG_DIR/backend.err.log" &
BACKEND_PID=$!

wait_http "$BACKEND_URL/api/health" 90 "Backend" || {
  info "backend.err.log (tail):"
  tail -n 40 "$LOG_DIR/backend.err.log" || true
  exit 1
}
ok "Backend healthy: $BACKEND_URL/api/health"
ok "API docs:        $BACKEND_URL/docs"

# 7 frontend start
step "7/8  Starting Next.js frontend on :$FRONTEND_PORT"
(
  cd "$FRONTEND_DIR"
  exec npm run dev -- -p "$FRONTEND_PORT"
) >"$LOG_DIR/frontend.log" 2>"$LOG_DIR/frontend.err.log" &
FRONTEND_PID=$!

wait_http "$FRONTEND_URL" 150 "Frontend" || {
  info "frontend.err.log (tail):"
  tail -n 50 "$LOG_DIR/frontend.err.log" || true
  exit 1
}
ok "Frontend ready: $FRONTEND_URL"

# 8 ready
step "8/8  Ready"
cat > "$STATE_FILE" <<EOF
{
  "website": "$FRONTEND_URL",
  "backend": "$BACKEND_URL",
  "docs": "$BACKEND_URL/docs",
  "health": "$BACKEND_URL/api/health",
  "ollama": "$OLLAMA_URL",
  "model": "$OLLAMA_MODEL",
  "logs": "$LOG_DIR",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

banner "SatQuery is running"
echo
echo "  OPEN THE WEBSITE:"
echo "  $FRONTEND_URL"
echo
echo "  Backend API:   $BACKEND_URL"
echo "  Swagger docs:  $BACKEND_URL/docs"
echo "  Health:        $BACKEND_URL/api/health"
echo "  Logs:          $LOG_DIR"
echo
echo "  Tip: Enable Debug Mode in the sidebar to inspect routing,"
echo "       intent decomposition, and model-not-loaded steps."
echo
echo "  Leave this window open. Press Ctrl+C to stop everything."
echo

if [[ "$SKIP_BROWSER" -eq 0 ]]; then
  info "Opening browser..."
  if have_cmd open; then open "$FRONTEND_URL"
  elif have_cmd xdg-open; then xdg-open "$FRONTEND_URL" || true
  fi
fi

# keep alive
while true; do
  sleep 2
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "Backend exited unexpectedly. See $LOG_DIR/backend.err.log"
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "Frontend exited unexpectedly. See $LOG_DIR/frontend.err.log"
    exit 1
  fi
done
