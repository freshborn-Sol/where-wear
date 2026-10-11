# -*- coding: utf-8 -*-
"""네이버 쇼핑 검색 API로 상품 카탈로그를 받아 catalog_naver.csv 를 만든다.

준비
  1) https://developers.naver.com → 애플리케이션 등록 → '검색' API 선택
     → Client ID / Client Secret 발급
  2) 아래 둘 중 하나로 키를 알려준다
        export NAVER_ID=...   export NAVER_SECRET=...
     또는 naver_key.txt 파일 첫 줄에  아이디,시크릿  형식으로 저장
  3) python fetch_naver.py            → catalog_naver.csv 생성
     python fetch_naver.py --images   → 상품 이미지 주소까지 넣기
  4) 내용을 확인하고 catalog.csv 로 바꾼 뒤  python import_catalog.py

주의
  * 받아오는 건 '온라인 상품 정보'다. 매장 내 위치는 이 스크립트가 임의로 배정한다.
  * 이미지 주소는 네이버/판매처 서버의 사진이다. 발표 자료에 그대로 쓰기 전에
    출처 표기와 이용 조건을 확인할 것. 기본값은 색상 그림(--images 없이)이다.
"""
import csv, json, os, random, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
from search import COLOR_WORDS
from seed import COLORS

BASE = Path(__file__).parent
API = "https://openapi.naver.com/v1/search/shop.json"
random.seed(1)

# 검색어 → (대분류, 종류, 놓을 집기 후보)
QUERIES = [
    ("남성 후드티",    "상의",   "후드티",   ["A-H1", "A-H2"]),
    ("맨투맨 스웨트셔츠", "상의",  "맨투맨",   ["A-H1", "A-H2"]),
    ("옥스포드 셔츠",   "상의",   "셔츠",     ["A-H2"]),
    ("니트 스웨터",     "상의",   "니트",     ["A-H2", "A-T1"]),
    ("반팔 티셔츠",     "상의",   "반팔티",   ["A-H1", "A-T1"]),
    ("와이드 슬랙스",   "하의",   "슬랙스",   ["B-H1"]),
    ("와이드 청바지",   "하의",   "청바지",   ["B-H1", "B-H2"]),
    ("조거 팬츠",       "하의",   "조거팬츠", ["B-H2"]),
    ("롱 스커트",       "하의",   "스커트",   ["B-H2"]),
    ("경량 패딩",       "아우터", "패딩",     ["B-H1", "A-T1"]),
    ("트렌치 코트",     "아우터", "코트",     ["A-T1"]),
    ("바람막이 자켓",   "아우터", "바람막이", ["A-T1"]),
    ("가디건",          "아우터", "가디건",   ["A-T1"]),
    ("스니커즈",        "신발",   "운동화",   ["C-S1"]),
    ("슬리퍼",          "신발",   "슬리퍼",   ["C-S1"]),
]
PER_QUERY = 4          # 검색어당 몇 개를 쓸지 (총 60개 정도)
SIZES = ["S", "M", "L", "XL"]

def keys():
    i, s = os.environ.get("NAVER_ID"), os.environ.get("NAVER_SECRET")
    f = BASE / "naver_key.txt"
    if (not i or not s) and f.exists():
        i, s = [t.strip() for t in f.read_text(encoding="utf-8").strip().split(",")[:2]]
    if not i or not s:
        sys.exit("키가 없습니다. naver_key.txt 에  아이디,시크릿  을 저장하거나 환경변수를 설정하세요.")
    return i, s

def call(query, cid, csec, display=20):
    url = f"{API}?{urllib.parse.urlencode({'query': query, 'display': display, 'sort': 'sim'})}"
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8")).get("items", [])

def clean(title):
    """<b> 태그 제거 + 공백 정리"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()

def guess_color(text):
    """상품명에서 색을 추측한다. 못 찾으면 None"""
    t = text.lower().replace(" ", "")
    for name, words in COLOR_WORDS.items():
        if any(w in t for w in words):
            return name
    return None

def to_rows(items, cat, sub, fixtures, use_images, seq):
    rows, seen = [], set()
    for it in items:
        name = clean(it.get("title", ""))
        if not name or name in seen: continue
        color = guess_color(name)
        if not color:                       # 색이 안 적힌 상품은 우리가 임의로 정한다
            color = random.choice(list(COLORS))
            name = f"{color} {name}"
        seen.add(name)
        seq[0] += 1
        rows.append({
            "sku": f"NV{seq[0]:03d}",
            "name": name[:40],
            "category": cat, "subcat": sub,
            "color": color, "hex": COLORS.get(color, ""),
            "fit": random.choice(["오버핏", "레귤러핏", "슬림핏"]),
            "price": int(it.get("lprice") or 0),
            "sizes": ",".join(f"{s}:{random.choice([0,0,1,2,3,4])}" for s in SIZES),
            "fixture": random.choice(fixtures),
            "level": random.choice(["상단", "중단", "하단"]),
            "ago_min": random.choice([2, 9, 25, 70, 180, 600]),
            "image_url": it.get("image", "") if use_images else "",
            "brand": it.get("brand") or it.get("maker") or "",
            "source": it.get("link", ""),
        })
        if len(rows) >= PER_QUERY: break
    return rows

def main():
    use_images = "--images" in sys.argv
    cid, csec = keys()
    all_rows, seq = [], [0]
    for q, cat, sub, fx in QUERIES:
        try:
            items = call(q, cid, csec)
        except Exception as e:
            print(f"  ! '{q}' 실패: {e}"); continue
        rows = to_rows(items, cat, sub, fx, use_images, seq)
        all_rows += rows
        print(f"  {q}: {len(rows)}개")
        time.sleep(0.3)                    # 호출 간격
    out = BASE / "catalog_naver.csv"
    cols = ["sku","name","category","subcat","color","hex","fit","price","sizes",
            "fixture","level","ago_min","image_url","brand","source"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(all_rows)
    print(f"\n완료: {len(all_rows)}개 → {out}")
    print("확인 후  mv catalog_naver.csv catalog.csv  →  python import_catalog.py")

if __name__ == "__main__":
    main()
