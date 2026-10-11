# -*- coding: utf-8 -*-
"""Pexels API로 catalog.csv 의 상품 사진을 받아 static/photos/ 에 저장한다.

준비
  1) https://www.pexels.com/api/ 에서 무료 API 키 발급 (가입 즉시 발급, 승인 대기 없음)
  2) pexels_key.txt 파일에 키를 한 줄로 저장  (또는 환경변수 PEXELS_KEY)
  3) python fetch_photos.py            → 사진이 없는 상품만 받아옴
     python fetch_photos.py --force    → 전부 다시 받음
  4) python import_catalog.py          → 사진이 화면에 반영됨

한도: 시간당 200회, 월 20,000회 (무료). 상품 60개면 한 번에 60회.
출처: Pexels 링크와 촬영자 이름을 표시해야 한다 → photo_credits.csv 에 저장되고
      웹의 /credits 화면에 자동으로 표시된다.
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = Path(__file__).parent
PHOTOS = BASE / "static" / "photos"
CREDITS = BASE / "photo_credits.csv"
API = "https://api.pexels.com/v1/search"

# 우리 색 이름 → Pexels color 파라미터 (지원 색상만)
PEXELS_COLOR = {
    "블랙": "black", "화이트": "white", "그레이": "gray", "네이비": "blue",
    "블루": "blue", "스카이블루": "blue", "베이지": "brown", "브라운": "brown",
    "레드": "red", "그린": "green", "핑크": "pink", "카키": "green",
}
# 우리 색 이름 → 영어 (검색어용)
COLOR_EN = {
    "블랙": "black", "화이트": "white", "그레이": "gray", "네이비": "navy",
    "블루": "blue", "스카이블루": "light blue", "베이지": "beige", "브라운": "brown",
    "레드": "red", "그린": "green", "핑크": "pink", "카키": "khaki",
}
# 우리 종류 → 영어 검색어
SUB_EN = {
    "후드티": "hoodie", "맨투맨": "sweatshirt", "셔츠": "shirt", "니트": "knit sweater",
    "반팔티": "t-shirt", "슬랙스": "trousers", "청바지": "jeans",
    "조거팬츠": "jogger pants", "스커트": "skirt", "코트": "coat",
    "패딩": "puffer jacket", "바람막이": "windbreaker jacket", "가디건": "cardigan",
    "운동화": "sneakers", "슬리퍼": "slippers",
    "긴팔티": "long sleeve t-shirt", "블라우스": "blouse", "조끼": "fleece vest",
    "반바지": "shorts", "재킷": "jacket", "후드집업": "zip up hoodie",
    "구두": "leather shoes", "부츠": "boots",
}

def key():
    k = os.environ.get("PEXELS_KEY")
    f = BASE / "pexels_key.txt"
    if not k and f.exists():
        k = f.read_text(encoding="utf-8").strip().strip('"').strip("'")
    if not k:
        sys.exit("키가 없습니다. pexels_key.txt 에 API 키를 저장하세요.")
    return k

def build_query(color, sub):
    """'블랙' + '후드티' → 'black hoodie clothing'"""
    return f"{COLOR_EN.get(color, color)} {SUB_EN.get(sub, sub)} clothing".strip()

def search(query, api_key, color=None):
    params = {"query": query, "per_page": 15, "orientation": "portrait"}
    if color and color in PEXELS_COLOR:
        params["color"] = PEXELS_COLOR[color]
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={
        "Authorization": api_key,
        # 기본 User-Agent(Python-urllib)는 차단당하는 경우가 있어 브라우저처럼 보낸다
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8")).get("photos", [])

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "where-wear-prototype"})
    with urllib.request.urlopen(req, timeout=20) as r, open(dest, "wb") as f:
        f.write(r.read())

def main():
    force = "--force" in sys.argv
    api_key = key()
    PHOTOS.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(BASE / "catalog.csv", encoding="utf-8-sig")))
    credits, used, ok, skip = [], set(), 0, 0
    if CREDITS.exists():                       # 이미 받은 사진은 다시 고르지 않는다
        for c in csv.DictReader(open(CREDITS, encoding="utf-8-sig")):
            pid = (c.get("pexels_url") or "").rstrip("/").rsplit("-", 1)[-1]
            if pid.isdigit(): used.add(int(pid))

    for r in rows:
        sku = r["sku"].strip().upper()
        dest = PHOTOS / f"{sku}.jpg"
        if dest.exists() and not force:
            skip += 1; continue
        q = (r.get("query") or "").strip() or build_query(r["color"].strip(), r["subcat"].strip())
        try:
            photos = search(q, api_key, r["color"].strip())
        except urllib.error.HTTPError as e:
            hint = {401: "키가 틀렸어요", 403: "키가 없거나 차단됐어요",
                    429: "호출 한도를 넘었어요 (시간당 200회)"}.get(e.code, "")
            print(f"  ! {sku} 검색 실패: HTTP {e.code} {hint}")
            if e.code in (401, 403):
                sys.exit("\n키를 확인하세요:  cat pexels_key.txt  로 키가 한 줄로 들어있는지 보세요.")
            continue
        except Exception as e:
            print(f"  ! {sku} 검색 실패: {e}"); continue
        photo = next((p for p in photos if p["id"] not in used), None)
        if not photo and photos:
            print(f"  ? {sku} '{q}' 새 사진이 없어 겹치는 사진 사용")
            photo = photos[0]
        if not photo:
            print(f"  ? {sku} '{q}' 결과 없음 → 색상 그림 유지"); continue
        used.add(photo["id"])
        try:
            download(photo["src"]["medium"], dest)
        except Exception as e:
            print(f"  ! {sku} 내려받기 실패: {e}"); continue
        credits.append({"sku": sku, "query": q,
                        "photographer": photo.get("photographer", ""),
                        "photographer_url": photo.get("photographer_url", ""),
                        "pexels_url": photo.get("url", "")})
        ok += 1
        print(f"  {sku}  {q}  ← {photo.get('photographer','')}")
        time.sleep(0.3)                      # 호출 간격

    if credits:                              # 출처 기록 (이어쓰기)
        new = not CREDITS.exists()
        with open(CREDITS, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["sku","query","photographer",
                                              "photographer_url","pexels_url"])
            if new: w.writeheader()
            w.writerows(credits)
    print(f"\n완료: 새로 받음 {ok}개, 건너뜀 {skip}개 → {PHOTOS}")
    print("이제  python import_catalog.py  를 실행하세요.")

if __name__ == "__main__":
    main()
