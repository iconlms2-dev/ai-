#!/bin/bash
cd "$(dirname "$0")"
echo "🚀 마케팅 자동화 서버 시작 중..."
echo "브라우저에서 http://localhost:8000 으로 접속하세요"
echo ""
source venv/bin/activate
python3 server.py
