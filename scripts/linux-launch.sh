#!/bin/bash
# CorpusMind Linux Launcher
# This script starts the engine and serves the PWA for Linux users.
# It does not require Tauri or Rust.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$SCRIPT_DIR/engine"
WEB_DIR="$SCRIPT_DIR/web"

echo "========================================="
echo "  CorpusMind v0.7.0 Linux Launcher"
echo "========================================="
echo ""

# Check if engine venv exists
if [ ! -d "$ENGINE_DIR/.venv" ]; then
    echo "Setting up engine for the first time..."
    cd "$ENGINE_DIR"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
    python -m spacy download en_core_web_sm 2>/dev/null || true
    pip install opencv-python-headless pillow python-multipart 2>/dev/null || true
    echo "Engine setup complete."
    echo ""
else
    source "$ENGINE_DIR/.venv/bin/activate"
fi

# Check if Ollama is running
if curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "[OK] Ollama is running"
else
    echo "[WARN] Ollama is not running. AI Assistant will not work."
    echo "       Install from https://ollama.com and run: ollama serve"
    echo ""
fi

# Start the engine
echo "Starting engine on http://127.0.0.1:8765 ..."
cd "$ENGINE_DIR"
corpusmind-engine &
ENGINE_PID=$!

# Wait for engine to be ready
for i in $(seq 1 10); do
    if curl -s http://127.0.0.1:8765/api/v1/health > /dev/null 2>&1; then
        echo "[OK] Engine is ready"
        break
    fi
    sleep 1
done

# Start the web server
echo ""
echo "Starting web frontend on http://localhost:5173 ..."
cd "$WEB_DIR"
if [ ! -d "node_modules" ]; then
    echo "Installing web dependencies..."
    npm install
fi
npm run dev &
WEB_PID=$!

echo ""
echo "========================================="
echo "  CorpusMind is running!"
echo ""
echo "  Web UI:  http://localhost:5173"
echo "  Engine:  http://127.0.0.1:8765"
echo "  API docs: http://127.0.0.1:8765/docs"
echo ""
echo "  Press Ctrl+C to stop both services."
echo "========================================="

# Trap Ctrl+C to kill both processes
trap "kill $ENGINE_PID $WEB_PID 2>/dev/null; exit" INT TERM
wait
