#!/bin/bash
# 다른 사람이 접속할 수 있는 임시 주소를 만듭니다. (서버켜기.command 를 먼저 실행)
echo ""; echo "  아래에 나오는 https://○○○.trycloudflare.com 뒤에 /go?at=A-H1 을 붙여서 보내세요."; echo ""
cloudflared tunnel --url http://localhost:5001
