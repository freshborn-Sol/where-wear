# where:wear — AI 에이전트 작업 규칙

의류 매장 옷 위치 안내 웹앱 (Flask + Jinja + SQLite). 답변과 커밋 메시지는 한국어로.

## 구조
- `app.py` 서버 · `templates/` 화면 (home, results, item, kiosk*, staff*) · `search.py` 글자 검색 · `vision.py` 사진 검색
- `static/cx.css` 손님(QR) 화면 스타일 · `static/ks.css` 키오스크·직원 화면 스타일 · `static/frame.js` PC에서 휴대폰·키오스크 모양 틀
- `templates/_cx.html`, `templates/_ks.html` 공통 매크로 (아이콘 · 탭바 · 상단 바)
- `i18n.py` 영어 화면 번역 사전 — 화면에 한국어 문구를 새로 넣으면 `PHRASES`(숫자가 들어가면 `PATTERNS`)에 영어도 추가

## 디자인
- 색은 `cx.css` · `ks.css` 맨 위 `:root` 변수만 사용: 주색 `--blue` #1677E8, 포인트 `--gold`(이름만 gold, 값은 아쿠아 #3DD6CF)
- 성공(초록) · 신고(빨강) · 경고(주황)는 의미가 있는 색이라 바꾸지 않음
- 키오스크는 40대 이상용: 글씨 크기 · 대비 · 버튼 크기를 줄이지 않음

## 지켜야 할 것
- 기능, 주소(URL), 폼 값(value), 스크립트 동작은 바꾸지 않음
- `gemini_key.txt`, `pexels_key.txt`, `vapid.json`, `store.db`는 열지도 커밋하지도 않음
- 바꾼 뒤 `python app.py` → http://localhost:5001/go?at=A-H1 , /kiosk , /staff 가 열리는지 확인하고, 확인이 끝나면 서버를 끔
- 작업 단위마다 git commit (메시지는 실제로 바꾼 내용으로), 끝나면 바꾼 내용을 한국어로 요약
- 다른 AI(Claude 등)와 같은 폴더를 동시에 고치지 않음. 시작 전에 `git status`가 깨끗한지 확인
