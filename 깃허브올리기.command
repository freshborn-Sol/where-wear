#!/bin/bash
# 더블클릭하면 지금까지 바뀐 내용을 GitHub(freshborn-Sol/where-wear)에 올립니다.
cd "$(dirname "$0")"
echo ""; echo "  where:wear → GitHub 올리기"; echo ""
git add -A
# 안전장치: API 키 파일이 섞이면 중단
if git diff --cached --name-only | grep -E "gemini_key|pexels_key|\.env$" ; then
  echo "  ⚠️  키 파일이 포함돼 있어 중단했어요. .gitignore를 확인하세요."; git reset -q; read -p "  엔터를 누르면 닫혀요"; exit 1
fi
git status --short
MSG="${1:-프로토타입 업데이트}"
if [ -f .commit_msg.txt ]; then git commit -q -F .commit_msg.txt; else git commit -q -m "$MSG"; fi
git push && echo "" && echo "  ✅ GitHub에 올렸어요: https://github.com/freshborn-Sol/where-wear" || echo "  ❌ push 실패 — 위 메시지를 Claude에게 보내 주세요"
echo ""; read -p "  엔터를 누르면 창이 닫혀요"
