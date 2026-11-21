#!/bin/bash
# 시연용 공개 주소를 만들고, 고정 주소가 그 주소로 연결되게 바꿉니다.
#   고정 주소(포스터 · 선반 QR에 넣는 주소): https://freshborn-sol.github.io/where-wear
#   서버켜기.command 를 먼저 실행하세요. 이 창을 닫으면 공개 주소도 꺼져요.
cd "$(dirname "$0")"
FIXED="https://freshborn-sol.github.io/where-wear"
LOG="$(mktemp -t wwtunnel)"
cloudflared tunnel --url http://localhost:5001 >"$LOG" 2>&1 &
TP=$!
trap 'kill $TP 2>/dev/null; rm -f "$LOG"' EXIT
echo ""; echo "  공개 주소를 만드는 중…"
URL=""
for i in $(seq 1 60); do
  URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break; sleep 1
done
if [ -z "$URL" ]; then
  echo "  ❌ 공개 주소를 못 만들었어요. 아래 내용을 Claude에게 보내 주세요"; echo ""; cat "$LOG"
  read -p "  엔터를 누르면 닫혀요"; exit 1
fi
echo "  임시 주소: $URL"
printf '{"url":"%s","updated":"%s"}\n' "$URL" "$(date '+%Y-%m-%d %H:%M')" > docs/server.json
git add docs/server.json
git commit -q -m "시연 서버 주소 갱신" -- docs/server.json
if git push -q 2>/dev/null || { git pull -q --rebase --autostash && git push -q; }; then
  echo ""; echo "  ✅ 고정 주소 연결 완료 — 1~2분 뒤부터 이 주소로 열려요"
  echo "     $FIXED"
else
  echo ""; echo "  ⚠️  GitHub에 올리지 못했어요. 오늘은 임시 주소를 쓰세요:"
  echo "     $URL/go?at=A-H1"
fi
echo ""; echo "  이 창을 닫거나 Ctrl+C 하면 공개 주소가 꺼져요."
wait $TP
