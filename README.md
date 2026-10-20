<p align="center"><img src="static/logo/logo.svg" alt="where:wear" height="56"></p>

# where:wear — 매장 안 옷 위치 안내 프로토타입

광운대학교 창의설계입문 3조 **뿌셔뿌셔조** (김준구 · 류한솔 · 이준혁)

찾는 옷이 매장의 **어느 행거·어느 단**에 있는지 알려주는 서비스입니다.
폰이 있으면 선반의 **QR**, 폰이 없거나 익숙하지 않으면 입구의 **키오스크**로 들어옵니다.
GPS·비콘·RFID 없이 Flask + SQLite만으로 동작합니다.

## 실행

```bash
pip install -r requirements.txt
python import_catalog.py      # catalog.csv → store.db (상품 125개, 처음 한 번)
python app.py                 # http://localhost:5001/go?at=A-H1
```

macOS에서는 폴더의 `.command` 파일을 더블클릭해도 됩니다.

| 파일 | 하는 일 |
|---|---|
| `서버켜기.command` | 서버 실행 + 브라우저 열기 |
| `공유링크켜기.command` | 다른 사람이 접속할 임시 주소 만들기 (cloudflared 필요) |
| `깃허브올리기.command` | 변경 내용 커밋·푸시 (키 파일이 섞이면 자동 중단) |

**사진으로 찾기(AI)** 를 쓰려면 [Google AI Studio](https://aistudio.google.com/apikey)에서 받은 Gemini 키를
`gemini_key.txt` 에 저장하세요. 키는 각자 발급하고 **절대 커밋·공유하지 않습니다** (`.gitignore`로 제외됨).
연결 확인: `python check_ai.py`

> `import_catalog.py` 는 `store.db` 를 새로 만듭니다. 직원이 등록한 위치·전시 실물 상품이 지워지니,
> 전시용 DB는 노트북 한 대에서만 관리하세요.

## 화면

| 주소 | 누구 | 내용 |
|---|---|---|
| `/go?at=A-H1` | 손님 (QR) | 검색 · 📷 사진으로 찾기(AI) · 종류 사진 타일 · 색상 |
| `/search` | 손님 | 종류 · 색상 · 핏 · 무늬 필터 (선택한 조건 안에서 개수 표시) |
| `/item/<sku>` | 손님 | 사이즈별 재고 · **추천 사이즈** · 위치 · 2D 길안내 · **찾았어요! / 찾는 게 없나요?** |
| `/me` | 손님 | 키·몸무게·발 사이즈 입력 (휴대폰 브라우저에만 저장, 서버 저장 없음) |
| `/kiosk` | 어르신 | 큰 글씨 · 종류(사진) → 색 → 결과, 결과에서 핏·무늬로 더 좁히기 |
| `/staff` | 직원 | 선반 QR → 옷 태그 연속 스캔으로 위치 등록 |
| `/staff/ai` | 직원 | 옷 사진 한 장으로 상품 등록 (AI가 종류·색·무늬·핏 채움) |
| `/staff/reports` | 직원·점장 | 신고함 — 손님 대기 / 위치 고칠 것 / 처리 기록 |
| `/staff/summary` | 점장 | 점장 요약 — 응대 지표 · 사용률 · 순위 (최근 7일) |

## '찾는 게 없나요?' 흐름

```
찾았어요!            → 이 위치가 맞다고 기록 ("방금 다른 손님이 찾았어요"), 같은 자리 신고 취소
찾는 게 없나요?
 ├ 다른 색을 보고 싶어요   → 같은 옷의 다른 색과 위치 (직원 호출 없음)
 ├ 여기에 옷이 없어요      → 신고 기록 → 재고 있으면 사이즈 골라 직원 호출 / 없으면 솔직히 안내
 │                          + 지금 매장에 있는 비슷한 옷 3개
 └ 직원에게 물어볼게요     → 사유 선택 후 호출
직원 호출 → 손님 화면에 진행 상태 (알림 → 가는 중 → 도착), 10분 지나면 자동 취소
```

- 같은 휴대폰의 같은 옷 신고는 1번만 집계 (익명 기기 id)
- 서로 다른 손님 2명이 신고하면 그 위치를 안내에서 내림 → 직원이 고치면 복구
- 직원 신고함: **손님 대기**(가는 중 · 전달 완료 · 재고 없음) / **위치 고칠 것**(선반별 묶음: 재등록 · 이동 · 재고 없음 · 오신고)

## 핵심 설계

1. **고정점 측위** — QR마다 주소(`?at=A-H1`)가 들어 있어 "지금 어디"를 계산할 필요가 없습니다.
2. **갱신 시각 + 손님 확인** — 위치가 언제 등록됐는지, 최근 손님이 찾았는지 함께 보여줍니다.
3. **AI는 특징 추출만, 비교는 코드가** — Gemini가 정해진 단어 목록 안에서만 종류·색·무늬·핏을 고르고,
   점수 계산은 `vision.py`가 합니다. 결과가 일정하고, 같은 사진은 캐시로 다시 부르지 않습니다.

## 파일 구조

```
app.py            웹 서버 (화면 + API)
vision.py         사진 → Gemini → 특징(JSON) → 비슷한 옷 순위
search.py         글자 검색 — 한국어 색·종류·핏 사전
seed.py           매장 도면(선반·통로 그래프)과 색상표
import_catalog.py catalog.csv → store.db
schema.sql        테이블 정의
catalog.csv       상품 목록 (sku · 종류 · 색 · 핏 · 무늬 · 사이즈별 재고 · 선반)
fetch_photos.py   Pexels에서 상품 사진 받기 (pexels_key.txt 필요)
photo_credits.csv 사진 출처 (Pexels 라이선스, /credits 에 표시)
make_qr.py        선반·상품 QR 생성 → qr/  (python make_qr.py <서버주소>)
check_ai.py       Gemini 키·모델 연결 점검
templates/        화면 (손님 · 키오스크 · 직원)
static/           cx.css(고객) · ks.css(키오스크·직원) · style.css · logo/ · photos/
```

상품 사진: [Pexels](https://www.pexels.com) (출처는 `photo_credits.csv`, 앱의 `/credits`)
