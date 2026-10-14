#!/bin/bash
# 더블클릭하면 where:wear 프로토타입 서버를 켭니다. (끄려면 이 창에서 Ctrl+C 또는 창 닫기)
cd "$(dirname "$0")"
lsof -ti:5001 | xargs kill 2>/dev/null          # 이미 켜진 서버가 있으면 끄고 새로
unset GEMINI_API_KEY                             # 예전 가짜 키 무시 → gemini_key.txt 사용
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; PY=python; else PY=python3; fi
echo ""; echo "  where:wear 서버를 켭니다… (이 창을 닫으면 서버도 꺼져요)"
( sleep 2; open "http://localhost:5001/go?at=A-H1" ) &
$PY app.py
