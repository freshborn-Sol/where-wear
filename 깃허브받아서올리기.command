#!/bin/bash
# GitHub에 내 컴퓨터에 없는 커밋이 있을 때: 먼저 받아서 합친 뒤 올립니다.
cd "$(dirname "$0")"
echo ""; echo "  where:wear ← GitHub 받아서 합치기"; echo ""
git fetch origin || { echo "  ❌ 받기 실패 — 위 메시지를 Claude에게 보내 주세요"; read -p "  엔터를 누르면 닫혀요"; exit 1; }
echo "  GitHub에만 있던 커밋:"; git log --format='   %h %an %ad  %s' --date=format:'%m-%d %H:%M' HEAD..origin/main
echo "  GitHub에서 바뀐 파일:"; git diff --stat HEAD...origin/main | sed 's/^/   /'
echo ""
if git pull --rebase origin main; then
  git push && echo "" && echo "  ✅ 합쳐서 올렸어요: https://github.com/freshborn-Sol/where-wear" || echo "  ❌ push 실패 — 위 메시지를 Claude에게 보내 주세요"
else
  echo ""; echo "  ⚠️  같은 파일이 양쪽에서 바뀌어 자동으로 못 합쳤어요. 원래대로 되돌립니다."
  git status --short | sed 's/^/   /'
  git rebase --abort
  echo "  위 내용을 Claude에게 보내 주세요."
fi
echo ""; read -p "  엔터를 누르면 창이 닫혀요"
