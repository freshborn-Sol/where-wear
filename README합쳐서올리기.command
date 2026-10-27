#!/bin/bash
# 한 번만 쓰는 파일: GitHub 웹에서 고친 README와 새 README를 합쳐서 올립니다.
cd "$(dirname "$0")"
echo ""; echo "  README 합쳐서 올리기"; echo ""
[ -f .README_merged.md ] || { echo "  ❌ .README_merged.md 가 없어요"; read -p "  엔터"; exit 1; }
git fetch origin || { echo "  ❌ 받기 실패"; read -p "  엔터"; exit 1; }
git merge --no-commit origin/main >/dev/null 2>&1
OTHER=$(git diff --name-only --diff-filter=U | grep -v '^README.md$')
if [ -n "$OTHER" ]; then
  echo "  ⚠️  README 말고도 충돌난 파일이 있어요: $OTHER"; git merge --abort; echo "  Claude에게 보내 주세요."; read -p "  엔터"; exit 1
fi
cp .README_merged.md README.md && git add README.md
git commit -q -m "README 합치기: GitHub에서 고친 소속·QR/키오스크 설명 + 심사용 README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rz3xLJN8hTN2PY9ZkddwHb" || { echo "  ❌ 커밋 실패"; read -p "  엔터"; exit 1; }
rm -f .README_merged.md
git push && echo "" && echo "  ✅ 올렸어요: https://github.com/freshborn-Sol/where-wear" || echo "  ❌ push 실패 — 위 메시지를 Claude에게 보내 주세요"
echo ""; read -p "  엔터를 누르면 창이 닫혀요"
