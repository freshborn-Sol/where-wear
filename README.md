# where:wear 프로토타입 (웹)

창의설계입문 3조 · 매장 안 옷 위치 안내 서비스의 **1차 프로토타입**입니다.
파이썬 Flask + SQLite로만 만들었고, 추가 장비(GPS·비콘·RFID)는 쓰지 않습니다.

## 실행 방법

```bash
pip install flask pillow qrcode        # 처음 한 번
python seed.py                         # 가상 매장 데이터 만들기 (상품 45개)
python app.py                          # http://localhost:5000
```

휴대폰으로 테스트하려면 노트북과 같은 와이파이에 연결한 뒤
`http://<노트북 IP>:5000/go?at=A-H1` 로 접속하세요.

## 화면

| 주소 | 누구 | 내용 |
|---|---|---|
| `/go?at=A-H1` | 손님 | 선반 QR로 들어오는 시작점. 검색 / 사진 검색 / 필터 |
| `/item/WW001?at=A-H1` | 손님 | 위치 · 갱신 시각 · 2D 길안내 · 없어요 / 직원 호출 |
| `/kiosk` | 어르신 | 큰 글씨 · 3터치 · 글자 입력 없음 |
| `/staff` | 직원 | 선반 QR 1번 → 옷 태그 연속 스캔으로 위치 등록 |
| `/staff/reports` | 직원 | 신고 · 호출 목록 |

## QR 만들기

```bash
python make_qr.py http://<서버주소>:5000     # qr/ 폴더에 PNG 생성
```

* `qr/shelf_A-H1.png` … 선반에 붙이는 QR (손님이 찍으면 서비스 시작)
* `qr/item_WW001.png` … 시연용 옷 태그 QR (실제 매장에서는 기존 바코드 사용)

## 구조

```
seed.py        가상 매장·상품 데이터 생성 (도면, 통로 그래프 포함)
schema.sql     테이블 정의
app.py         웹 서버 (화면 + API)
search.py      검색 엔진 — 한국어 속성 사전 기반 (CLIP 없이도 동작)
clip_search.py [선택] CLIP으로 정확도 올리기
make_qr.py     QR 일괄 생성
templates/     화면 (손님 / 키오스크 / 직원)
static/        CSS, 상품 이미지(SVG)
```

## 핵심 동작 3가지

1. **고정점 방식** — QR마다 주소(`?at=A-H1`)가 박혀 있어 측위 계산이 필요 없습니다.
2. **갱신 시각 표시** — 위치 정보가 언제 등록됐는지 항상 보여줍니다 (1시간 이내 초록 / 6시간 이내 주황 / 그 이상 회색).
3. **신고로 자가 수정** — "여기 없어요"가 같은 자리에 2번 쌓이면 그 위치를 자동으로 내립니다. (`app.py`의 `/api/report`)

## 실제 매장처럼 데이터 채우기

`catalog.csv` 를 엑셀로 열어 채우고 아래를 실행하면 상품 데이터가 통째로 바뀝니다.

```bash
python import_catalog.py
```

| 열 | 설명 |
|---|---|
| sku | 상품 코드. 옷 태그 QR에 들어갈 값 (실제 매장이면 바코드 번호) |
| name / category / subcat | 상품명 / 상의·하의·아우터·신발 / 후드티·슬랙스 등 |
| color / hex | 색 이름(검색 사전과 맞춰야 함) / 비워두면 자동 |
| price / sizes | 가격 / `S:2,M:0,L:3,XL:1` 형식 |
| fixture / level / ago_min | 어느 선반 / 상단·중단·하단 / 몇 분 전에 등록된 것으로 볼지 |

사진은 `static/photos/<SKU>.jpg` 에 넣으면 자동으로 쓰입니다.
**직접 찍은 사진만 쓰세요.** 브랜드 홈페이지 이미지는 저작권 문제가 있습니다.

색 이름을 새로 쓰려면 `search.py` 의 `COLOR_WORDS` 에 한 줄 추가하세요.
(`import_catalog.py` 가 사전에 없는 색을 알려줍니다.)

## 상품 사진 받아오기 (Pexels API)

무료 스톡 사진 API입니다. 상업적 이용까지 허용되고, 시간당 200회·월 20,000회까지 무료입니다.

```bash
# 1) https://www.pexels.com/api/ 에서 키 발급 (가입 즉시, 승인 대기 없음)
echo "발급받은키" > pexels_key.txt
# 2) catalog.csv 의 색상·종류에 맞는 사진 받기
python fetch_photos.py
# 3) 반영
python import_catalog.py
```

* `static/photos/<SKU>.jpg` 로 저장되고, 있으면 색상 그림 대신 그 사진이 쓰입니다.
* 마음에 안 드는 사진은 그 파일만 지우고 `python fetch_photos.py` 를 다시 돌리면 새로 받습니다.
* 출처는 `photo_credits.csv` 에 쌓이고 **웹의 `/credits` 화면에 자동 표시**됩니다.
  Pexels 이용 조건(Pexels 링크 + 촬영자 표기)을 지키기 위한 화면이니 지우지 마세요.

> 네이버 쇼핑 검색 API는 2026년 7월 31일에 종료되어 더 이상 쓸 수 없습니다.
> 구글 이미지를 긁어오는 방식은 저작권 문제가 있어 쓰지 않습니다.

## AI 검색 정확도 올리기 (선택)

기본은 한국어 단어 사전 기반이라 설치 없이 바로 돌아갑니다.
더 올리고 싶으면:

```bash
pip install torch transformers cairosvg
python clip_search.py build      # 상품 이미지 임베딩 계산 (1~2분)
```

`search.py`가 `clip_search`를 자동으로 찾아 순위를 다듬습니다.
모델은 `Bingsu/clip-vit-base-patch32-ko`(한국어) 또는
`patrickjohncyh/fashion-clip`(영어·패션 특화) 중에 고르면 됩니다. 둘 다 MIT 라이선스입니다.

## 아직 안 한 것

* 로그인·권한 (직원 화면이 누구에게나 열려 있음)
* 여러 매장 지원
* PWA (홈 화면에 추가)

## AI 사진 검색 (Gemini)

사진을 올리거나 찍으면 Vision AI가 옷의 특징(분류·종류·색·패턴·핏)을 뽑고,
매장 DB의 옷과 비교해 **가장 비슷한 옷 1개 + 비슷한 추천 4개**를 위치와 함께 보여준다.

1. 키 넣기 (둘 중 하나)
   - 터미널: `export GEMINI_API_KEY="AIza..."`
   - 또는 `gemini_key.txt` 파일에 키 한 줄 (폴더를 남에게 공유할 땐 이 파일을 빼기)
2. 실행: `python app.py` → `http://localhost:5001`
3. 손님: 홈의 **📷 찍어서 찾기 / 🖼 사진 올리기**
4. 직원(전시 준비): `/staff/ai` 에서 선반 고르기 → 옷 촬영 → AI가 채운 특징 확인 → 저장 (EX001, EX002…)

- 모델 바꾸기: `export GEMINI_MODEL="모델이름"` (기본 gemini-3.1-flash-lite)
- 인터넷·한도·키 문제로 AI를 못 쓰면 자동으로 '대표 색' 검색으로 바뀐다
- 같은 사진은 `ai_cache.json`에 저장돼 API를 다시 부르지 않는다
- 휴대폰 카메라는 HTTPS에서만 열린다 → cloudflared 터널 주소로 접속
