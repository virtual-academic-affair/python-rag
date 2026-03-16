#!/bin/bash
# Usage:
#   ./stop.sh           Dừng FastAPI + MinIO (giữ RabbitMQ)
#   ./stop.sh --all     Dừng FastAPI + MinIO + RabbitMQ

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="default"
if [[ "$1" == "--all" ]]; then
  MODE="all"
fi

echo ""
echo -e "${CYAN}=================================================="
echo "   AI Service — Shutdown"
if [[ "$MODE" == "all" ]]; then
  echo "   Mode: tất cả (app + MinIO + RabbitMQ)"
else
  echo "   Mode: chỉ app + MinIO (giữ RabbitMQ)"
fi
echo -e "==================================================${NC}"

# ── Stop FastAPI process ─────────────────────────────────────────
echo ""
echo -e "${YELLOW}🛑 Dừng FastAPI...${NC}"
PID_FILE="logs/app.pid"
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo -e "${GREEN}   Đã dừng process PID=$PID${NC}"
  fi
  rm -f "$PID_FILE"
else
  # Fallback: kill by port
  PIDS=$(lsof -ti :8000 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    echo "$PIDS" | xargs kill 2>/dev/null || true
    echo -e "${GREEN}   Đã dừng process trên port 8000${NC}"
  else
    echo "   Không tìm thấy process FastAPI đang chạy"
  fi
fi

# ── Stop Docker services ─────────────────────────────────────────
echo ""
echo -e "${YELLOW}🐳 Dừng Docker services...${NC}"

if [[ "$MODE" == "all" ]]; then
  docker-compose down
else
  docker-compose stop minio minio-init 2>/dev/null || true
  docker-compose rm -f minio minio-init 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}✅ Đã dừng tất cả services${NC}"
