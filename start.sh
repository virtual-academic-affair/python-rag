#!/bin/bash
# Usage: ./start.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${CYAN}=================================================="
echo "   AI Service — Startup"
echo "   RabbitMQ: Cloud Hosted"
echo -e "==================================================${NC}"

# ── Python virtual environment ───────────────────────────────────
echo ""
if [[ ! -d ".venv" ]]; then
  echo -e "${YELLOW}Box Tạo môi trường ảo .venv...${NC}"
  # Check if python3 is available
  if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ python3 không được cài đặt. Vui lòng cài đặt Python 3.${NC}"
    exit 1
  fi
  python3 -m venv .venv
fi

echo -e "${YELLOW}Box Kích hoạt môi trường ảo và cài dependencies...${NC}"
source .venv/bin/activate
pip install -r requirements.txt --quiet

# ── Kill process cũ trên port 8000 (nếu có) ─────────────────────
OLD_PID=$(lsof -ti :8000 2>/dev/null || true)
if [[ -n "$OLD_PID" ]]; then
  echo -e "${YELLOW}⚠️  Port 8000 đang bị chiếm (PID: $OLD_PID), đang kill...${NC}"
  kill $OLD_PID 2>/dev/null || true
  sleep 1
fi

# ── Start FastAPI ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}🚀 Khởi động FastAPI...${NC}"
echo -e "   API:              ${CYAN}http://localhost:8000${NC}"
echo -e "   Docs:             ${CYAN}http://localhost:8000/docs${NC}"
echo ""

mkdir -p logs
python run.py >> logs/app.log 2>&1 &
APP_PID=$!
echo $APP_PID > logs/app.pid
echo -e "   PID: ${GREEN}$APP_PID${NC}"
echo -e "   Log: ${CYAN}logs/app.log${NC}  (Ctrl+C để thoát tail, server vẫn chạy)"
echo ""
tail -f logs/app.log
