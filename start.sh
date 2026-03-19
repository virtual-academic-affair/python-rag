#!/bin/bash
# Usage:
#   ./start.sh          Start only (dùng khi RabbitMQ đã chạy từ nest-api)
#   ./start.sh --all    Start + RabbitMQ

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="default"
if [[ "$1" == "--all" ]]; then
  MODE="all"
fi

echo ""
echo -e "${CYAN}=================================================="
echo "   AI Service — Startup"
if [[ "$MODE" == "all" ]]; then
  echo "   Mode: tất cả (RabbitMQ)"
else
  echo "   Mode: mặc định (RabbitMQ từ nest-api)"
fi
echo -e "==================================================${NC}"

# ── Docker services ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}🐳 Khởi động Docker services...${NC}"

if [[ "$MODE" == "all" ]]; then
  docker-compose up -d rabbitmq
fi

echo ""
echo -e "${GREEN}✅ Trạng thái Docker services:${NC}"
docker-compose ps

# ── Python virtual environment ───────────────────────────────────
echo ""
if [[ ! -d ".venv" ]]; then
  echo -e "${YELLOW}📦 Tạo môi trường ảo .venv...${NC}"
  python3 -m venv .venv
fi

echo -e "${YELLOW}📦 Kích hoạt môi trường ảo và cài dependencies...${NC}"
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

if [[ "$MODE" == "all" ]]; then
  echo -e "   RabbitMQ UI:      ${CYAN}http://localhost:15672${NC}  (guest/guest)"
fi
echo ""

mkdir -p logs
python run.py >> logs/app.log 2>&1 &
APP_PID=$!
echo $APP_PID > logs/app.pid
echo -e "   PID: ${GREEN}$APP_PID${NC}"
echo -e "   Log: ${CYAN}logs/app.log${NC}  (Ctrl+C để thoát tail, server vẫn chạy)"
echo ""
tail -f logs/app.log
