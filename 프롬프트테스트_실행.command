#!/bin/bash
cd "$(dirname "$0")"
# 기존 8001 포트 정리
lsof -ti:8001 | xargs kill -9 2>/dev/null
sleep 1
echo "프롬프트 테스트 서버 시작 중..."
python3 prompt_server.py &
sleep 2
open http://localhost:8001
echo "브라우저에서 열렸습니다. 이 창을 닫으면 서버가 종료됩니다."
wait
