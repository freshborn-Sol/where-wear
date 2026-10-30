# -*- coding: utf-8 -*-
"""where:wear 모델 매장 도면 (대형 SPA 매장 1층 · 900×760 도면 좌표)

  - 구역(zones): 아우터(C) · 신발·잡화(D) · 상의(A) · 하의(B) · 입구 추천존(P)
  - 집기(fixtures): 행거 · 원형 행거 · 벽면 선반 · 매대 · 마네킹 · 신발/잡화 진열대  → 옷을 거는 곳(QR 붙임)
  - 시설: 입구(키오스크) · 피팅룸 · 창고(직원 전용) · 계산대 · 기둥            → 길을 막거나 표시만
  - 통로 그래프(nodes/edges): 15px 격자에서 집기·시설을 피한 칸만 이어 자동 생성.
    각 집기는 가장 가까운 통로 칸에 연결된다 → 앱은 이 그래프로 '꺾임이 적은 최단 경로'를 찾는다.

실행
  python store_map.py          # 지금 store.db 의 도면을 새 도면으로 바꾸고, 상품 위치를 새 집기로 옮긴다
                               # (상품·재고·찜·신고 기록은 그대로)
"""
import sqlite3, datetime
from pathlib import Path

BASE = Path(__file__).parent
STORE = (20, 20, 860, 720)          # 매장 외벽 x, y, w, h
SIZE = (900, 760)                    # 도면 전체 크기
DOOR = (400, 500)                    # 아래 벽의 출입문 구간 (x 시작~끝)

# 구역: id, 이름, x, y, w, h, 바탕색, 이름표 위치(lx, ly — 집기와 안 겹치는 빈자리)
ZONES = [
    ("C", "아우터",      40,  40, 290, 210, "#EEF6F1",  50, 212),
    ("D", "신발 · 잡화", 350,  40, 230, 210, "#FDF4EA", 360, 220),
    ("A", "상의",        40, 290, 380, 270, "#EAF4FF",  72, 530),
    ("B", "하의",       480, 290, 380, 270, "#F3EFFB", 490, 530),
    ("P", "추천",       220, 590, 460, 100, "#FDEFF3", 600, 598),
]

# 집기·시설: id, 구역, 이름, 종류, x, y, w, h
FIXTURES = [
    # 상의 (A)
    ("A-W1", "A", "A구역 벽면 선반",   "벽면",    40, 300,  26, 250),
    ("A-H1", "A", "A구역 1번 행거",    "행거",   100, 305, 260,  30),
    ("A-H2", "A", "A구역 2번 행거",    "행거",   100, 375, 260,  30),
    ("A-R1", "A", "A구역 원형 행거 1", "원형행거", 105, 445,  84,  84),
    ("A-R2", "A", "A구역 원형 행거 2", "원형행거", 225, 445,  84,  84),
    ("A-T1", "A", "A구역 매대",        "매대",   335, 450,  70,  90),
    # 하의 (B)
    ("B-H1", "B", "B구역 1번 행거",    "행거",   500, 305, 260,  30),
    ("B-H2", "B", "B구역 2번 행거",    "행거",   500, 375, 260,  30),
    ("B-H3", "B", "B구역 3번 행거",    "행거",   500, 445, 170,  30),
    ("B-T1", "B", "B구역 데님 매대",   "매대",   500, 488, 170,  40),
    ("B-M1", "B", "B구역 마네킹",      "마네킹", 715, 470,  60,  60),
    ("B-W1", "B", "B구역 벽면 선반",   "벽면",   834, 300,  26, 250),
    # 아우터 (C)
    ("C-W1", "C", "C구역 벽면 선반",   "벽면",    50,  40, 270,  26),
    ("C-H1", "C", "C구역 1번 행거",    "행거",    70, 100, 230,  30),
    ("C-H2", "C", "C구역 2번 행거",    "행거",    70, 170, 230,  30),
    # 신발 · 잡화 (D)
    ("D-W1", "D", "D구역 신발 벽면",   "벽면",   360,  40, 210,  26),
    ("D-S1", "D", "D구역 신발 진열대", "진열대", 385, 100, 150,  50),
    ("D-S2", "D", "D구역 잡화 진열대", "진열대", 385, 174, 150,  40),
    # 입구 추천존 (P)
    ("P-M1", "P", "P구역 입구 마네킹", "마네킹", 240, 605,  56,  56),
    ("P-T1", "P", "P구역 신상품 매대", "매대",   320, 605, 120,  60),
    ("P-T2", "P", "P구역 할인 매대",   "매대",   470, 605, 120,  60),
    # 시설 (옷을 두지 않음)
    ("FIT",   "S", "피팅룸",            "피팅룸", 600,  40, 260, 105),
    ("STOCK", "S", "창고 (직원 전용)",   "창고",   600, 160, 260,  90),
    ("COUNTER", "S", "계산대",          "계산대", 700, 600, 160, 110),
    ("COL1",  "S", "기둥",              "기둥",   330, 262,  20,  20),
    ("COL2",  "S", "기둥",              "기둥",   570, 262,  20,  20),
    ("COL3",  "S", "기둥",              "기둥",   441, 420,  20,  20),
    ("ENTRANCE", "E", "매장 입구(키오스크)", "입구", 400, 716, 100, 24),
]
FACILITY_KINDS = ("입구", "계산대", "피팅룸", "창고", "기둥")

# 예전 도면(집기 7개) → 새 도면
OLD_TO_NEW = {"A-H1": "A-H1", "A-H2": "A-H2", "A-T1": "A-T1", "B-H1": "B-H1",
              "B-H2": "B-H2", "C-S1": "D-S1", "ENTRANCE": "ENTRANCE"}

# 상품 종류 → 새 집기 (대형 SPA 매장식 진열)
SUB_TO_FX = {
    "후드티": None,            # 예전 위치(A-H1/A-H2) 그대로
    "맨투맨": "A-H2", "셔츠": "A-R1", "블라우스": "A-R1", "니트": "A-R2",
    "반팔티": "A-T1", "긴팔티": "A-W1", "조끼": "A-W1",
    "슬랙스": "B-H1", "조거팬츠": "B-H2", "반바지": "B-H3", "청바지": "B-T1", "스커트": "B-W1",
    "코트": "C-H1", "재킷": "C-H1", "패딩": "C-H2", "바람막이": "C-H2", "가디건": "C-W1", "후드집업": "C-W1",
    "운동화": "D-W1", "슬리퍼": "D-S1", "구두": "D-S1", "부츠": "D-S1",
    "원피스": "B-W1", "모자": "D-S2", "가방": "D-S2", "양말": "D-S2", "벨트": "D-S2", "기타": "D-S2",
}
# 추천존 · 마네킹에 따로 두는 옷
FEATURED = {"UQ016": ("P-M1", "중단"), "UQ022": ("P-T1", "상단"), "UQ033": ("P-T1", "중단"),
            "UQ040": ("P-T2", "상단"), "UQ020": ("P-T2", "중단"), "UQ036": ("B-M1", "중단"),
            "UQ158": ("P-T2", "하단"), "UQ160": ("B-M1", "하단"), "UQ174": ("P-M1", "중단"), "UQ178": ("P-T1", "상단"), "UQ192": ("P-T2", "상단"), "UQ197": ("P-T1", "하단")}

def fixture_for(sku, subcat, old_fx):
    if sku in FEATURED: return FEATURED[sku][0]
    nf = SUB_TO_FX.get(subcat)
    if nf: return nf
    return OLD_TO_NEW.get(old_fx, old_fx)

# ---------- 통로 그래프 ----------
STEP, PAD = 15, 9

def _blocked(x, y):
    sx, sy, sw, sh = STORE
    if not (sx + PAD <= x <= sx + sw - PAD and sy + PAD <= y <= sy + sh - PAD):
        return True
    for f in FIXTURES:
        if f[0] == "ENTRANCE": continue
        fx, fy, fw, fh = f[4:8]
        if fx - PAD <= x <= fx + fw + PAD and fy - PAD <= y <= fy + fh + PAD:
            return True
    return False

def _rect_dist(x, y, f):
    fx, fy, fw, fh = f[4:8]
    dx = max(fx - x, 0, x - (fx + fw)); dy = max(fy - y, 0, y - (fy + fh))
    return (dx * dx + dy * dy) ** .5

def build_graph():
    """15px 격자 통로 → NODES {id:(x,y)}, EDGES [(a,b)]. 집기는 가장 가까운 통로 칸에 붙는다."""
    sx, sy, sw, sh = STORE
    cells = {}
    for x in range(sx + STEP, sx + sw, STEP):
        for y in range(sy + STEP, sy + sh + 1, STEP):
            if not _blocked(x, y):
                cells[(x, y)] = f"g{x}_{y}"
    nodes = {cid: xy for xy, cid in cells.items()}
    edges = []
    for (x, y), cid in cells.items():
        for nx, ny in ((x + STEP, y), (x, y + STEP)):
            if (nx, ny) in cells: edges.append((cid, cells[(nx, ny)]))
    for f in FIXTURES:
        if f[3] in ("기둥",): continue
        if f[0] == "ENTRANCE":
            tx, ty = f[4] + f[6] / 2, f[5] - 6
            best = min(cells, key=lambda c: (c[0] - tx) ** 2 + (c[1] - ty) ** 2)
        else:
            cx, cy = f[4] + f[6] / 2, f[5] + f[7] / 2
            near = [c for c in cells if _rect_dist(c[0], c[1], f) <= PAD + STEP + 1] or list(cells)   # 집기 바로 앞 통로 칸들
            best = min(near, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)                          # 그중 집기 가운데와 가장 가까운 칸
        nodes[f[0]] = best
        edges.append((f[0], cells[best]))
    return nodes, edges

NODES, EDGES = build_graph()

ZONES_SQL = "CREATE TABLE IF NOT EXISTS zones (id TEXT PRIMARY KEY, name TEXT, x INT, y INT, w INT, h INT, color TEXT, lx INT, ly INT)"

def write_map(db):
    """도면 표(zones/fixtures/nodes/edges)를 새 도면으로 채운다."""
    if db.execute("SELECT name FROM sqlite_master WHERE name='zones'").fetchone() and \
       "lx" not in {r[1] for r in db.execute("PRAGMA table_info(zones)")}:
        db.execute("DROP TABLE zones")                 # 예전 형식이면 새로
    db.execute(ZONES_SQL)
    for t in ("zones", "fixtures", "nodes", "edges"): db.execute(f"DELETE FROM {t}")
    db.executemany("INSERT INTO zones VALUES (?,?,?,?,?,?,?,?,?)", ZONES)
    db.executemany("INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?)", FIXTURES)
    db.executemany("INSERT INTO nodes VALUES (?,?,?)", [(k, x, y) for k, (x, y) in NODES.items()])
    db.executemany("INSERT INTO edges VALUES (?,?)", EDGES + [(b, a) for a, b in EDGES])

def migrate(db_path=BASE / "store.db"):
    """지금 DB의 도면만 바꾸고, 상품 위치는 종류에 맞는 새 집기로 옮긴다 (등록 시각·단은 그대로)."""
    db = sqlite3.connect(db_path); db.row_factory = sqlite3.Row
    write_map(db)
    moved = 0
    for p in db.execute("""SELECT p.id, p.sku, p.fixture_id, p.level, i.subcat FROM placements p
                           LEFT JOIN items i ON i.sku = p.sku WHERE p.active = 1""").fetchall():
        nf = fixture_for(p["sku"], p["subcat"], p["fixture_id"])
        lv = FEATURED[p["sku"]][1] if p["sku"] in FEATURED else p["level"]
        if nf != p["fixture_id"] or lv != p["level"]:
            db.execute("UPDATE placements SET fixture_id=?, level=? WHERE id=?", (nf, lv, p["id"])); moved += 1
    # 비활성 위치 · 신고 기록의 예전 집기 이름도 새 이름으로
    for old, new in OLD_TO_NEW.items():
        if old != new:
            db.execute("UPDATE placements SET fixture_id=? WHERE fixture_id=?", (new, old))
            db.execute("UPDATE reports SET fixture_id=? WHERE fixture_id=?", (new, old))
    db.commit()
    n_fx = sum(1 for f in FIXTURES if f[3] not in FACILITY_KINDS)
    print(f"새 도면 적용: 구역 {len(ZONES)}개 · 옷 거는 집기 {n_fx}개 · 시설 {len(FIXTURES) - n_fx}개 · 통로 점 {len(NODES)}개")
    print(f"상품 위치 {moved}건을 새 집기로 옮김 → {db_path}")

if __name__ == "__main__":
    migrate()
