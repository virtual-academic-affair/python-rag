#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${CYAN}=================================================="
echo "   AI Service — Shutdown"
echo -e "==================================================${NC}"

# 1. Kill FastAPI process nếu có lưu PID
if [[ -f logs/app.pid ]]; then
  APP_PID=$(cat logs/app.pid)
  echo ""
  echo -e "${YELLOW}🛑 Dừng FastAPI (PID: $APP_PID)...${NC}"
  
  if kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID"
    echo -e "${GREEN}✅ Đã dừng FastAPI.${NC}"
  else
    echo -e "${YELLOW}⚠️  Tiến trình FastAPI không tồn tại hoặc đã dừng trước đó.${NC}"
  fi
  rm logs/app.pid
else
  # Cleanup theo port nếu không có PID file
  OLD_PID=$(lsof -ti :8000 2>/dev/null || true)
  if [[ -n "$OLD_PID" ]]; then
    echo -e "${YELLOW}🛑 Dừng process trên port 8000 (PID: $OLD_PID)...${NC}"
    kill "$OLD_PID" 2>/dev/null || true
    echo -e "${GREEN}✅ Đã dừng process.${NC}"
  else
    echo -e "${YELLOW}⚠️  Không tìm thấy FastAPI log PID hay process nào trên port 8000.${NC}"
  fi
fi

echo ""
echo -e "${GREEN}✅ Hệ thống đã được shutdown hoàn toàn.${NC}"
echo ""
