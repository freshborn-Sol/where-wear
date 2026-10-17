# -*- coding: utf-8 -*-
"""가상 모델 매장 데이터를 만든다. (실행: python seed.py)
   - 매장 도면(구역/집기), 통로 그래프, 상품 60개, 초기 위치 등록
   - 상품 이미지는 SVG로 자동 생성 (색상 + 카테고리 실루엣)
"""
import os, random, sqlite3, datetime
from pathlib import Path

BASE = Path(__file__).parent
DB = BASE / "store.db"
IMG = BASE / "static" / "img"
random.seed(7)

# ---------- 1. 매장 도면 ----------
# 집기(선반) : id, 구역, 이름, 종류, 도면 좌표(x,y), 폭/높이
FIXTURES = [
    ("A-H1", "A", "A구역 1번 행거", "행거", 120, 110, 150, 40),
    ("A-H2", "A", "A구역 2번 행거", "행거", 120, 200, 150, 40),
    ("A-T1", "A", "A구역 매대",     "매대", 120, 290, 150, 50),
    ("B-H1", "B", "B구역 1번 행거", "행거", 430, 110, 150, 40),
    ("B-H2", "B", "B구역 2번 행거", "행거", 430, 200, 150, 40),
    ("C-S1", "C", "C구역 선반",     "선반", 430, 300, 150, 50),
    ("ENTRANCE", "E", "매장 입구(키오스크)", "입구", 300, 430, 90, 30),
]
# 통로 노드 : 집기 앞 지점 + 통로 교차점
NODES = {
    "A-H1": (300, 130), "A-H2": (300, 220), "A-T1": (300, 310),
    "B-H1": (400, 130), "B-H2": (400, 220), "C-S1": (400, 310),
    "N1": (350, 130), "N2": (350, 220), "N3": (350, 310), "N4": (350, 400),
    "ENTRANCE": (300, 420),
}
EDGES = [("A-H1","N1"),("B-H1","N1"),("A-H2","N2"),("B-H2","N2"),
         ("A-T1","N3"),("C-S1","N3"),("N1","N2"),("N2","N3"),("N3","N4"),
         ("N4","ENTRANCE")]

# ---------- 2. 상품 카탈로그 ----------
CATS = {
    "상의": ["후드티", "맨투맨", "셔츠", "니트", "반팔티"],
    "하의": ["슬랙스", "청바지", "조거팬츠", "스커트"],
    "아우터": ["코트", "패딩", "바람막이", "가디건"],
    "신발": ["운동화", "슬리퍼"],
}
COLORS = {  # 색상명 : (HEX, 비슷한 색 검색용 RGB)
    "블랙": "#222222", "화이트": "#f2f2f2", "그레이": "#9aa0a6",
    "네이비": "#1f3864", "블루": "#2f6fd0", "스카이블루": "#7fc4f0",
    "베이지": "#d9c7a7", "브라운": "#6b4a2f", "레드": "#c0392b",
    "그린": "#2e7d52", "핑크": "#e79ab5", "카키": "#6b6b47",
}
FITS = ["오버핏", "레귤러핏", "슬림핏", "크롭"]
SIZES = ["S", "M", "L", "XL"]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 380">
<rect width="300" height="380" fill="#f6f7f9"/>{shape}
<text x="150" y="350" font-size="20" text-anchor="middle" fill="#555"
 font-family="sans-serif">{label}</text></svg>"""
SHAPES = {  # 카테고리별 아주 단순한 실루엣
 "상의":'<path d="M90 70 L130 55 L170 55 L210 70 L225 120 L195 130 L195 280 L105 280 L105 130 L75 120 Z" fill="{c}" stroke="#00000022"/>',
 "하의":'<path d="M110 60 H190 L200 300 H160 L150 170 L140 300 H100 Z" fill="{c}" stroke="#00000022"/>',
 "아우터":'<path d="M85 70 L130 52 L170 52 L215 70 L230 140 L200 150 L200 300 L100 300 L100 150 L70 140 Z" fill="{c}" stroke="#00000022"/><line x1="150" y1="60" x2="150" y2="300" stroke="#00000033" stroke-width="3"/>',
 "신발":'<path d="M70 230 L150 200 L200 230 Q235 245 235 270 L60 270 Z" fill="{c}" stroke="#00000022"/>',
}

def make_image(sku, cat, hexcode, label):
    svg = SVG.format(shape=SHAPES[cat].format(c=hexcode), label=label)
    (IMG / f"{sku}.svg").write_text(svg, encoding="utf-8")

def main():
    IMG.mkdir(parents=True, exist_ok=True)
    if DB.exists(): DB.unlink()
    db = sqlite3.connect(DB)
    db.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))

    for f in FIXTURES:
        db.execute("INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?)", f)
    for nid, (x, y) in NODES.items():
        db.execute("INSERT INTO nodes VALUES (?,?,?)", (nid, x, y))
    for a, b in EDGES:
        db.execute("INSERT INTO edges VALUES (?,?)", (a, b))
        db.execute("INSERT INTO edges VALUES (?,?)", (b, a))

    # 상품 60개
    shelf_ids = [f[0] for f in FIXTURES if f[0] != "ENTRANCE"]
    n = 0
    now = datetime.datetime.now()
    for cat, subs in CATS.items():
        for sub in subs:
            for _ in range(3):
                n += 1
                sku = f"WW{n:03d}"
                color = random.choice(list(COLORS))
                fit = random.choice(FITS)
                name = f"{fit} {color} {sub}"
                price = random.choice([19900, 29900, 39900, 49900, 59900])
                make_image(sku, cat, COLORS[color], f"{color} {sub}")
                db.execute(
                    "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?)",
                    (sku, name, cat, sub, color, COLORS[color], fit, price,
                     f"img/{sku}.svg"))
                for s in SIZES:
                    db.execute("INSERT INTO stock (sku,size,qty) VALUES (?,?,?)",
                               (sku, s, random.choice([0, 0, 1, 2, 3, 5])))
                # 초기 위치: 카테고리에 맞는 집기에 배치
                pref = {"상의": ["A-H1", "A-H2"], "하의": ["B-H1", "B-H2"],
                        "아우터": ["B-H1", "A-H2"], "신발": ["C-S1"]}[cat]
                fx = random.choice(pref + ["A-T1"])
                lv = random.choice(["상단", "중단", "하단"])
                ago = random.choice([3, 12, 40, 90, 260, 1500])  # 분 단위
                ts = (now - datetime.timedelta(minutes=ago)).isoformat(timespec="seconds")
                db.execute(
                    "INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                    " VALUES (?,?,?,?,?,1)", (sku, fx, lv, ts, "seed"))
    db.commit()
    print(f"완료: 상품 {n}개, 집기 {len(FIXTURES)}개 → {DB}")

if __name__ == "__main__":
    main()
