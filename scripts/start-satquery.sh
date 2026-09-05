#!/usr/bin/env bash
# SatQuery AI - one-click local launcher (macOS / Linux)
# Role-aware: Controller / Model Host / Full System.
# Always asks for device role every launch (never reuses a previous role).
# On exit: stops services, unloads Ollama models, clears role config.
#
# Double-click:  START_SATQUERY.command
# Or run:        ./scripts/start-satquery.sh

set -euo pipefail

SKIP_OLLAMA=0
SKIP_BROWSER=0
BACKEND_PORT=8000
FRONTEND_PORT=3000
NODE_PORT=8100

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ollama) SKIP_OLLAMA=1; shift ;;
    --skip-browser) SKIP_BROWSER=1; shift ;;
    --backend-port) BACKEND_PORT="$2"; shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    --node-port) NODE_PORT="$2"; shift 2 ;;
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
DEVICE_JSON="$REPO_ROOT/.satquery/device.json"
CONFIGURE_PY="$SCRIPT_DIR/configure_role.py"
PAIR_PY="$SCRIPT_DIR/pair_host.py"

FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
OLLAMA_URL="http://127.0.0.1:11434"
PLANNER_MODEL="qwen3:4b-instruct"
HOST_VLM_MODEL="qwen2.5vl:7b"
HOST_VLM_FALLBACKS=(
  "qwen2.5vl:7b"
  "qwen2.5vl:latest"
  "qwen2.5vl"
  "hf.co/bartowski/Qwen_Qwen2.5-VL-7B-Instruct-GGUF:Q4_K_M"
)

BACKEND_PID=""
FRONTEND_PID=""
NODE_PID=""
OLLAMA_PID=""
ROLE="full_system"
NODE_ID=""
PAIRING_CODE=""

mkdir -p "$LOG_DIR"

banner() { echo; echo "================================================================"; echo "  $1"; echo "================================================================"; }
step()   { echo; echo ">> $1"; }
ok()     { echo "   [OK]  $1"; }
warn()   { echo "   [!]   $1"; WARNINGS+=("$1"); }
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
  echo "Shutting down SatQuery (freeing ports + model memory)..."
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${NODE_PID:-}" ]] && kill "$NODE_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && pkill -P "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "${BACKEND_PID:-}" ]] && pkill -P "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${NODE_PID:-}" ]] && pkill -P "$NODE_PID" 2>/dev/null || true
  free_port "$BACKEND_PORT" || true
  free_port "$FRONTEND_PORT" || true
  free_port "$NODE_PORT" || true

  if have_cmd ollama; then
    info "Unloading Ollama models from memory..."
    # Stop any running models (ollama ps)
    while read -r name _; do
      [[ -z "${name:-}" || "$name" == "NAME" ]] && continue
      ollama stop "$name" >/dev/null 2>&1 || true
      ok "Unloaded Ollama model: $name"
    done < <(ollama ps 2>/dev/null || true)
    for m in "$PLANNER_MODEL" "$HOST_VLM_MODEL" "qwen2.5vl:7b" "qwen2.5vl" "qwen3:4b-instruct"; do
      ollama stop "$m" >/dev/null 2>&1 || true
    done
  fi

  [[ -n "${OLLAMA_PID:-}" ]] && kill "$OLLAMA_PID" 2>/dev/null || true

  if [[ -f "$DEVICE_JSON" ]]; then
    rm -f "$DEVICE_JSON"
    info "Cleared device role config (.satquery/device.json)"
  fi
  rmdir "$REPO_ROOT/.satquery" 2>/dev/null || true
  echo "Stopped. Role cleared - next launch will ask again."
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

ensure_ollama_model() {
  local model="$1" label="$2"
  # Case-insensitive / partial match - do not re-download if present
  if ollama list 2>/dev/null | grep -qiF "$model"; then
    ok "$label already downloaded: $model"
    return 0
  fi
  local base="${model%%:*}"
  if ollama list 2>/dev/null | grep -qiF "$base"; then
    ok "$label already present (variant of $base)"
    return 0
  fi
  info "Downloading $model ($label) - large download, please wait..."
  if ollama pull "$model"; then
    ok "$label ready: $model"
    return 0
  fi
  warn "Could not pull $model"
  return 1
}

ensure_host_vlm() {
  if ollama list 2>/dev/null | grep -qiE 'qwen2\.5vl|qwen2\.5-vl|Qwen2\.5-VL'; then
    local hit
    hit=$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -iE 'qwen2\.5vl|qwen2\.5-vl' | head -n1 || true)
    if [[ -n "$hit" ]]; then
      ok "Host VLM already present: $hit"
      HOST_VLM_MODEL="$hit"
      return 0
    fi
  fi
  local cand
  for cand in "${HOST_VLM_FALLBACKS[@]}"; do
    info "Trying Host VLM candidate: $cand"
    if ensure_ollama_model "$cand" "Host VLM (VQA/caption)"; then
      HOST_VLM_MODEL="$cand"
      "$VENV_DIR/bin/python" - <<PY || true
import json
from pathlib import Path
p = Path(r"$DEVICE_JSON")
if p.is_file():
    d = json.loads(p.read_text(encoding="utf-8"))
    for m in d.get("hosted_models") or []:
        if m.get("id") == "qwen-vl":
            m["ollama_tag"] = "$cand"
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
PY
      return 0
    fi
  done
  warn "No Host VLM available. Install with: ollama pull qwen2.5vl:7b"
  return 1
}

banner "SatQuery AI - One-Click Setup"
echo "Repo: $REPO_ROOT"

step "1/9  Checking project folders"
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

step "2/9  Checking system requirements"

# Prefer 3.12/3.13/3.11 — pydantic-core wheels fail on Python 3.14+ (PyO3 max 3.13).
PYTHON_BIN=""
python_version_ok() {
  local bin="$1"
  local ver major minor
  ver=$("$bin" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
  [[ -z "$ver" ]] && return 1
  major=${ver%%.*}
  minor=${ver#*.}
  if [[ "$major" -eq 3 && "$minor" -ge 11 && "$minor" -le 13 ]]; then
    echo "$ver"
    return 0
  fi
  return 1
}

for cand in python3.12 python3.13 python3.11; do
  if have_cmd "$cand"; then
    if ver=$(python_version_ok "$cand"); then
      PYTHON_BIN="$cand"
      ok "Python $ver found ($cand) — using for backend venv"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]] && have_cmd python3; then
  PYVER=$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
  MAJOR=${PYVER%%.*}
  MINOR=${PYVER#*.}
  if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 && "$MINOR" -le 13 ]]; then
    PYTHON_BIN="python3"
    ok "Python $PYVER found (python3)"
  elif [[ "$MAJOR" -eq 3 && "$MINOR" -ge 14 ]]; then
    warn "python3 is $PYVER — too new for SatQuery deps (need 3.11-3.13; pydantic/PyO3 unsupported on 3.14)"
  else
    warn "Python $PYVER is unsupported (need 3.11-3.13)"
  fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
  warn "Compatible Python not found - attempting brew install python@3.12..."
  try_brew_install "python@3.12" "Python 3.12" || true
  hash -r 2>/dev/null || true
  # Homebrew often installs as python3.12, not default python3
  for cand in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if have_cmd "$cand" || [[ -x "$cand" ]]; then
      if [[ -x "$cand" ]]; then
        if ver=$(python_version_ok "$cand"); then
          PYTHON_BIN="$cand"
          ok "Python $ver ready ($cand)"
          break
        fi
      fi
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  fail "Install Python 3.12 (recommended):  brew install python@3.12"
  fail "Then re-run. Do not use Python 3.14 for this project yet."
fi

NODE_OK=0
NPM_OK=0
if have_cmd node; then ok "Node.js $(node --version)"; NODE_OK=1; fi
if have_cmd npm; then ok "npm $(npm --version)"; NPM_OK=1; fi

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
    else warn "Ollama missing - install from https://ollama.com/download"
    fi
  fi
else
  info "Skipping Ollama (--skip-ollama)"
fi

if (( ${#FAILURES[@]} > 0 )); then
  echo "SETUP FAILED: fix requirements above"; exit 1
fi

step "3/9  Backend virtualenv + Python packages"
[[ -f "$REQ_LITE" ]] || { fail "Missing $REQ_LITE"; exit 1; }
ok "requirements-lite.txt present"

# Recreate venv if missing OR built with unsupported Python (e.g. leftover 3.14)
NEED_VENV=0
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  NEED_VENV=1
else
  VENV_VER=$("$VENV_DIR/bin/python" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")
  VMAJOR=${VENV_VER%%.*}
  VMINOR=${VENV_VER#*.}
  if [[ "$VMAJOR" -ne 3 || "$VMINOR" -lt 11 || "$VMINOR" -gt 13 ]]; then
    warn "Existing venv is Python $VENV_VER (unsupported) - recreating with $PYTHON_BIN"
    rm -rf "$VENV_DIR"
    NEED_VENV=1
  else
    ok "venv already exists (Python $VENV_VER) - skipping recreate"
  fi
fi

if [[ "$NEED_VENV" -eq 1 ]]; then
  info "Creating venv with $PYTHON_BIN..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "venv created"
fi

info "Installing / verifying Python packages (pinned requirements-lite.txt)..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip -q
# Remove interrupted pip leftovers if present
find "$VENV_DIR" -type d -name '~*' 2>/dev/null | while read -r d; do
  info "Removing broken package leftover: $(basename "$d")"
  rm -rf "$d"
done
if ! "$VENV_DIR/bin/pip" install -r "$REQ_LITE" -q; then
  fail "pip install failed. Ensure Python is 3.11-3.13 (not 3.14). Current venv: $($VENV_DIR/bin/python --version 2>&1)"
  exit 1
fi
ok "Backend dependencies ready"

step "Device role (asked every launch)"
rm -f "$DEVICE_JSON"
echo
echo "  Select this device's SatQuery role:"
echo "    1. Controller   (frontend + backend + small planner Qwen)"
echo "    2. Model Host   (node API + $HOST_VLM_MODEL)"
echo "    3. Full System"
echo
"$VENV_DIR/bin/python" "$CONFIGURE_PY" --change

[[ -f "$DEVICE_JSON" ]] || { echo "No device role saved"; exit 1; }
ROLE=$("$VENV_DIR/bin/python" -c "import json; print(json.load(open(r'$DEVICE_JSON'))['role'])")
NODE_ID=$("$VENV_DIR/bin/python" -c "import json; print(json.load(open(r'$DEVICE_JSON'))['node_id'])")
PAIRING_CODE=$("$VENV_DIR/bin/python" -c "import json; print(json.load(open(r'$DEVICE_JSON')).get('pairing_code',''))")
NODE_PORT=$("$VENV_DIR/bin/python" -c "import json; print(json.load(open(r'$DEVICE_JSON')).get('node_port',$NODE_PORT))")
BACKEND_PORT=$("$VENV_DIR/bin/python" -c "import json; print(json.load(open(r'$DEVICE_JSON')).get('port',$BACKEND_PORT))")
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
ok "Role: $ROLE  node_id: $NODE_ID"

NEED_FRONTEND=0
NEED_PLANNER=0
NEED_HOST_VLM=0
[[ "$ROLE" == "controller" || "$ROLE" == "full_system" ]] && NEED_FRONTEND=1 && NEED_PLANNER=1
[[ "$ROLE" == "model_host" || "$ROLE" == "full_system" ]] && NEED_HOST_VLM=1

if [[ "$NEED_FRONTEND" -eq 1 && "$NODE_OK" -eq 0 ]]; then
  warn "Node.js not found - attempting brew install..."
  try_brew_install "node" "Node.js" || true
  hash -r 2>/dev/null || true
  if have_cmd node; then ok "Node.js $(node --version)"; NODE_OK=1
  else fail "Install Node.js LTS then re-run."; exit 1
  fi
fi

export USE_SHIVEN_ROUTER=true
export SKIP_MODEL_INFERENCE=true
export SHIVEN_ROUTER_ROOT="$ROUTER_DIR"
export OLLAMA_BASE_URL="$OLLAMA_URL"
export OLLAMA_PLANNER_MODEL="$PLANNER_MODEL"
export SATQUERY_ROLE="$ROLE"
export SATQUERY_NODE_PORT="$NODE_PORT"

if [[ "$NEED_FRONTEND" -eq 1 ]]; then
  step "4/9  Frontend .env + npm packages"
  echo "NEXT_PUBLIC_API_URL=$BACKEND_URL" > "$ENV_LOCAL"
  ok "frontend/.env.local -> NEXT_PUBLIC_API_URL=$BACKEND_URL"
  pushd "$FRONTEND_DIR" >/dev/null
  if [[ ! -d "node_modules/next" ]]; then
    info "Running npm install (first run can take several minutes)..."
    npm install
    ok "Frontend dependencies installed"
  else
    ok "node_modules present - skipping full reinstall"
    npm install --prefer-offline
    ok "Frontend dependencies verified"
  fi
  popd >/dev/null
else
  step "4/9  Frontend skipped (Model Host role)"
  ok "Not installing or starting Next.js on Model Host"
fi

step "5/9  Ollama models"
if [[ "$OLLAMA_OK" -eq 1 && "$SKIP_OLLAMA" -eq 0 ]]; then
  if curl -fsS --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    ok "Ollama API already running"
  else
    info "Starting Ollama serve..."
    if [[ -d "/Applications/Ollama.app" ]]; then
      open -a Ollama || true
    fi
    nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    wait_http "$OLLAMA_URL/api/tags" 60 "Ollama" && ok "Ollama API ready" || true
  fi
  if curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    if [[ "$NEED_PLANNER" -eq 1 ]]; then
      ensure_ollama_model "$PLANNER_MODEL" "Planner" || true
    else
      info "Skipping planner model pull (Model Host)"
    fi
    if [[ "$NEED_HOST_VLM" -eq 1 ]]; then
      ensure_host_vlm || true
    else
      info "Skipping Host VLM pull (Controller) - remote Model Host provides $HOST_VLM_MODEL"
    fi
  fi
else
  warn "Ollama unavailable"
fi

UVICORN="$VENV_DIR/bin/uvicorn"
[[ -x "$UVICORN" ]] || { fail "uvicorn missing in venv"; exit 1; }

if [[ "$ROLE" == "model_host" ]]; then
  step "6/9  Starting Model Host node API on :$NODE_PORT (foreground — live traffic)"
  free_port "$NODE_PORT"
  sleep 1

  banner "SatQuery Model Host is running"
  echo
  echo "  Node ID:       $NODE_ID"
  echo "  Port:          $NODE_PORT"
  echo "  Pairing code:  $PAIRING_CODE"
  echo "  VLM model:     $HOST_VLM_MODEL"
  echo "  Docs:          http://127.0.0.1:$NODE_PORT/docs"
  echo
  echo "  On the Controller, pair with:"
  echo "    python scripts/pair_host.py <THIS_LAN_IP> $NODE_PORT $PAIRING_CODE"
  echo
  echo "  Live pairing / query / answer logs will print below."
  echo "  Leave this window open. Press Ctrl+C to stop."
  echo

  cd "$BACKEND_DIR"
  export USE_SHIVEN_ROUTER SKIP_MODEL_INFERENCE SHIVEN_ROUTER_ROOT OLLAMA_BASE_URL OLLAMA_PLANNER_MODEL SATQUERY_ROLE SATQUERY_NODE_PORT
  export PYTHONUNBUFFERED=1
  # Foreground (no exec) so cleanup trap still runs on Ctrl+C
  "$UVICORN" app.node.host_app:app --host 0.0.0.0 --port "$NODE_PORT" --log-level info
  exit $?
fi

step "6/9  Starting FastAPI backend on :$BACKEND_PORT"
free_port "$BACKEND_PORT"
[[ "$NEED_FRONTEND" -eq 1 ]] && free_port "$FRONTEND_PORT"

: >"$LOG_DIR/backend.log"
: >"$LOG_DIR/backend.err.log"
(
  cd "$BACKEND_DIR"
  export USE_SHIVEN_ROUTER SKIP_MODEL_INFERENCE SHIVEN_ROUTER_ROOT OLLAMA_BASE_URL OLLAMA_PLANNER_MODEL SATQUERY_ROLE SATQUERY_NODE_PORT
  export PYTHONUNBUFFERED=1
  exec "$UVICORN" app.main:app --host 0.0.0.0 --port "$BACKEND_PORT"
) >"$LOG_DIR/backend.log" 2>"$LOG_DIR/backend.err.log" &
BACKEND_PID=$!

wait_http "$BACKEND_URL/api/health" 90 "Backend" || {
  info "backend.err.log (tail):"
  tail -n 40 "$LOG_DIR/backend.err.log" || true
  exit 1
}
ok "Backend healthy: $BACKEND_URL/api/health"

step "7/9  Starting Next.js frontend on :$FRONTEND_PORT"
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

step "8/9  Model Host pairing (optional)"
PAIRED_COUNT=$("$VENV_DIR/bin/python" -c "import json; print(len(json.load(open(r'$DEVICE_JSON')).get('paired_hosts') or []))")
if [[ "$PAIRED_COUNT" -gt 0 ]]; then
  ok "Already have $PAIRED_COUNT paired host(s)"
else
  echo "  No Model Host paired. Enter: <ip> <port> <code>  (or press Enter to skip)"
  read -r -p "  Pair: " PAIR_LINE || true
  if [[ -n "${PAIR_LINE:-}" ]]; then
    # shellcheck disable=SC2086
    set -- $PAIR_LINE
    if [[ $# -ge 3 ]]; then
      "$VENV_DIR/bin/python" "$PAIR_PY" "$1" "$2" "$3" && ok "Paired" || warn "Pairing failed"
    else
      warn "Need: address port code"
    fi
  else
    info "Skipped pairing — VQA/caption needs Model Host with $HOST_VLM_MODEL"
  fi
fi

step "9/9  Ready"
cat > "$STATE_FILE" <<EOF
{
  "role": "$ROLE",
  "website": "$FRONTEND_URL",
  "backend": "$BACKEND_URL",
  "docs": "$BACKEND_URL/docs",
  "health": "$BACKEND_URL/api/health",
  "ollama": "$OLLAMA_URL",
  "planner": "$PLANNER_MODEL",
  "host_vlm": "$HOST_VLM_MODEL",
  "logs": "$LOG_DIR",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

banner "SatQuery Controller / Full System is running"
echo
echo "  OPEN THE WEBSITE:"
echo "  $FRONTEND_URL"
echo
echo "  Backend API:   $BACKEND_URL"
echo "  Role:          $ROLE"
echo "  Host VLM:      $HOST_VLM_MODEL (on Model Host via /node/inference)"
echo "  Logs:          $LOG_DIR"
echo "  Change role:   ./scripts/start-satquery.sh --change-role"
echo
echo "  Leave this window open. Press Ctrl+C to stop everything."
echo "  Live analyze / remote-host traffic will appear below (from backend.log)."
echo

if [[ "$SKIP_BROWSER" -eq 0 ]]; then
  info "Opening browser..."
  if have_cmd open; then open "$FRONTEND_URL"
  elif have_cmd xdg-open; then xdg-open "$FRONTEND_URL" || true
  fi
fi

LOG_POS=0
while true; do
  sleep 1
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "Backend exited unexpectedly. See $LOG_DIR/backend.err.log"
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "Frontend exited unexpectedly. See $LOG_DIR/frontend.err.log"
    exit 1
  fi
  if [[ -f "$LOG_DIR/backend.log" ]]; then
    TOTAL=$(wc -l < "$LOG_DIR/backend.log" | tr -d ' ')
    if [[ -n "$TOTAL" && "$TOTAL" -gt "$LOG_POS" ]]; then
      sed -n "$((LOG_POS + 1)),${TOTAL}p" "$LOG_DIR/backend.log" 2>/dev/null | while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if echo "$line" | grep -Eqi 'OUTGOING|INCOMING|Remote VLM|paired Model Host|No Model Host|No paired|analyze'; then
          echo "  $line"
        elif echo "$line" | grep -Eqi 'ERROR|Error|failed|WARNING'; then
          echo "  $line"
        fi
      done
      LOG_POS=$TOTAL
    fi
  fi
done
