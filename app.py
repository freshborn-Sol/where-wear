# -*- coding: utf-8 -*-
"""where:wear 프로토타입 웹 서버  (실행: python app.py → http://localhost:5000)

화면
  /go?at=A-H1    손님: 선반 QR로 들어오는 시작점 (검색·필터·사진검색)
  /item/WW001    상품 상세 + 2D 길안내 + 갱신 시각 + 없어요/직원호출
  /kiosk         어르신용 키오스크 (큰 글씨·3터치·글자입력 없음)
  /staff         직원: 선반 QR 1번 → 옷 QR 연속 스캔으로 위치 등록
  /staff/reports 직원: 신고·호출 목록
"""
import datetime, json, os, sqlite3, uuid
from collections import Counter, deque
from urllib.parse import urlencode
from pathlib import Path
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

import search as S
import vision as V
from seed import COLORS, CATS

BASE = Path(__file__).parent
DBFILE = Path(os.environ.get("WW_DB", BASE / "store.db"))
UPLOADS = BASE / "static" / "uploads"
STORE_NAME = os.environ.get("WW_STORE", "유니클로 명동점")   # 고객 화면(안내)에 보이는 매장 이름
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024     # 사진 15MB까지

def ensure_schema():
    """예전 store.db를 지우지 않고, AI 사진검색에 필요한 칸만 덧붙인다."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DBFILE)
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    for col, typ in [("pattern", "TEXT"), ("ai_json", "TEXT"), ("is_demo", "INTEGER DEFAULT 0")]:
        if col not in cols:
            con.execute(f"ALTER TABLE items ADD COLUMN {col} {typ}")
    rcols = {r[1] for r in con.execute("PRAGMA table_info(reports)")}
    for col, typ in [("detail", "TEXT"),        # 호출 사유
                     ("size", "TEXT"),          # 손님이 원하는 사이즈
                     ("device", "TEXT"),        # 익명 기기 id (중복 신고 방지)
                     ("wait_state", "TEXT DEFAULT ''"),   # '' / waiting / going / served / nostock / expired
                     ("wait_at", "TEXT"), ("served_at", "TEXT"),
                     ("resolution", "TEXT"), ("resolved_at", "TEXT")]:
        if col not in rcols:
            con.execute(f"ALTER TABLE reports ADD COLUMN {col} {typ}")
    if "confirmed_at" not in {r[1] for r in con.execute("PRAGMA table_info(placements)")}:
        con.execute("ALTER TABLE placements ADD COLUMN confirmed_at TEXT")   # 손님이 '찾았어요' 누른 시각
    # ⑧ 창고 재고: stock.qty = 매장 진열, stock.wh = 창고
    if "wh" not in {r[1] for r in con.execute("PRAGMA table_info(stock)")}:
        con.execute("ALTER TABLE stock ADD COLUMN wh INTEGER DEFAULT 0")
    if not con.execute("SELECT COUNT(*) FROM stock WHERE wh>0").fetchone()[0]:   # 시연용: 창고 재고 채우기(항상 같은 값)
        import zlib
        for sku, size in con.execute("SELECT sku, size FROM stock").fetchall():
            con.execute("UPDATE stock SET wh=? WHERE sku=? AND size=?", (zlib.crc32(f"{sku}{size}".encode()) % 4, sku, size))
    # ① 바코드 ↔ 상품: 같은 상품도 시즌마다 바코드가 달라서, 여러 바코드를 한 상품(sku)에 연결
    con.execute("CREATE TABLE IF NOT EXISTS barcodes (code TEXT PRIMARY KEY, sku TEXT, season TEXT)")
    if not con.execute("SELECT COUNT(*) FROM barcodes").fetchone()[0]:
        import zlib
        for (sku,) in con.execute("SELECT sku FROM items").fetchall():
            for season in ("26SS", "26FW"):
                n = zlib.crc32(f"{sku}{season}".encode()) % 10**9
                con.execute("INSERT OR IGNORE INTO barcodes VALUES (?,?,?)", (f"880{n:09d}{'1' if season=='26SS' else '2'}", sku, season))
    # ④⑪ 매장 설정 / ⑦ 진열 점검일
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in [("store_type", "대형"), ("staff_count", "4"), ("kiosk", "1"), ("busy", "auto"),
                 ("last_check", datetime.date.today().isoformat())]:
        con.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
    # ⑩ 사용률 지표
    con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, sku TEXT, src TEXT, ts TEXT)")
    # 찜목록: 로그인 없이 휴대폰별 익명 id(device)로 저장
    con.execute("CREATE TABLE IF NOT EXISTS likes (device TEXT, sku TEXT, ts TEXT, PRIMARY KEY (device, sku))")
    con.commit(); con.close()
ensure_schema()

# ---------- DB ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DBFILE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    if (d := g.pop("db", None)): d.close()

def rows(sql, args=()): return [dict(r) for r in db().execute(sql, args)]
def one(sql, args=()):
    r = db().execute(sql, args).fetchone()
    return dict(r) if r else None

def now(): return datetime.datetime.now()

# ---------- ④⑪ 매장 설정 ----------
CHECK_DAYS = 14                     # ⑦ 진열 점검 주기 (인터뷰: 2~3주마다 진열 변경)
def setting(k, default=""):
    r = one("SELECT value FROM settings WHERE key=?", (k,))
    return r["value"] if r else default
def set_setting(k, v):
    db().execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
def is_busy():
    """바쁨 모드: 켜기/끄기, 자동이면 '직원 2명 이하' 또는 '기다리는 손님 수 ≥ 직원 수'"""
    mode = setting("busy", "auto")
    if mode in ("on", "off"): return mode == "on"
    staff = int(setting("staff_count", "4") or 4)
    waiting = one("SELECT COUNT(*) n FROM reports WHERE wait_state IN ('waiting','going')")["n"]
    return staff <= 2 or waiting >= staff

# ---------- ⑩ 사용률 기록 ----------
def log_event(kind, sku=None, src=None):
    try:
        db().execute("INSERT INTO events (kind,sku,src,ts) VALUES (?,?,?,?)", (kind, sku, src, now().isoformat(timespec="seconds")))
        db().commit()
    except Exception:
        pass

# ---------- ① 바코드 → 상품 ----------
def resolve_code(code):
    """찍은 코드(상품코드 또는 시즌별 바코드)를 상품으로. 바코드가 달라도 같은 상품으로 묶는다."""
    code = (code or "").strip().upper()
    it = one("SELECT * FROM items WHERE sku=?", (code,))
    if it: return it, None
    b = one("SELECT * FROM barcodes WHERE code=?", (code,))
    if b: return one("SELECT * FROM items WHERE sku=?", (b["sku"],)), b["season"]
    return None, None

@app.context_processor
def helpers():
    """상품 이미지 주소. 로컬 파일이면 static/, http로 시작하면 그대로 사용."""
    def imgsrc(it):
        p = (it.get("image") or "") if isinstance(it, dict) else (it["image"] or "")
        return p if p.startswith("http") else url_for("static", filename=p)
    def with_args(**kw):
        """현재 검색 조건에서 일부만 바꾼 주소 (값이 비면 그 조건을 뺌)"""
        a = request.args.to_dict()
        for k, v in kw.items():
            if v in (None, ""): a.pop(k, None)
            else: a[k] = v
        return "/search?" + urlencode(a)
    try: busy = is_busy()
    except Exception: busy = False
    staff_badge = 0
    if request.path.startswith("/staff"):                 # 직원 탭바 '신고함' 숫자 = 기다리는 손님 수
        try: staff_badge = one("SELECT COUNT(*) n FROM reports WHERE wait_state IN ('waiting','going')")["n"]
        except Exception: staff_badge = 0
    return dict(imgsrc=imgsrc, with_args=with_args, store_name=STORE_NAME, busy=busy, staff_badge=staff_badge,
                cx_at=request.args.get("at") or "ENTRANCE")   # 고객 화면 탭바·링크용 현재 QR 위치

# ---------- 위치 + 갱신 시각 ----------
def placement_of(sku):
    """가장 최근에 등록된 (살아 있는) 위치 1건"""
    return one("""SELECT p.*, f.name AS fixture_name, f.zone, f.x, f.y
                  FROM placements p JOIN fixtures f ON f.id = p.fixture_id
                  WHERE p.sku=? AND p.active=1
                  ORDER BY p.updated_at DESC LIMIT 1""", (sku,))

def freshness(ts):
    """'12분 전' + 신선도 등급(fresh/ok/old)"""
    if not ts: return ("위치 정보 없음", "none")
    m = max(0, (now() - datetime.datetime.fromisoformat(ts)).total_seconds() / 60)   # 시계 차이로 음수 방지
    if m < 60:   return (f"{int(m)}분 전 등록", "fresh")
    if m < 60*6: return (f"{int(m//60)}시간 전 등록", "ok")
    if m < 60*24:return (f"{int(m//60)}시간 전 등록", "old")
    return (f"{int(m//60//24)}일 전 등록", "old")

def decorate(items):
    """상품 목록에 위치·신선도·재고를 붙인다."""
    out = []
    for it in items:
        p = placement_of(it["sku"])
        it = dict(it)
        it["place"] = p
        it["fresh"] = freshness(p["updated_at"] if p else None)
        it["sizes"] = rows("SELECT size, qty, COALESCE(wh,0) wh FROM stock WHERE sku=? ORDER BY size", (it["sku"],))
        out.append(it)
    return out

# ---------- 길찾기 (BFS) ----------
_GRAPH = {}

def _graph():
    """통로 그래프(점 좌표 + 이웃)를 한 번만 읽어 둔다. 도면이 바뀌면 점 개수로 알아채고 다시 읽음"""
    n = one("SELECT COUNT(*) n FROM nodes")["n"]
    if _GRAPH.get("n") != n:
        pos = {r["id"]: (r["x"], r["y"]) for r in rows("SELECT * FROM nodes")}
        adj = {}
        for e in rows("SELECT * FROM edges"):
            adj.setdefault(e["a"], []).append(e["b"])
        _GRAPH.update(n=n, pos=pos, adj=adj)
    return _GRAPH["pos"], _GRAPH["adj"]

def path_between(start, goal):
    """통로를 따라가는 최단 경로. 같은 길이면 덜 꺾이는 길을 고른다 (꺾일 때마다 벌점)."""
    import heapq
    pos, adj = _graph()
    if start not in adj or goal not in adj: return []
    TURN = 40                                   # 한 번 꺾을 때 더하는 거리 (도면 좌표)
    def d(a, b): return abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1])
    def dirn(a, b):
        dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
        return (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    best = {(start, None): 0}
    prev = {}
    pq = [(0, 0, start, None)]
    k = 0
    while pq:
        c, _, u, du = heapq.heappop(pq)
        if u == goal:
            out, st = [u], (u, du)
            while st in prev:
                st = prev[st]; out.append(st[0])
            return out[::-1]
        if c > best.get((u, du), 1e18): continue
        for v in adj.get(u, []):
            dv = dirn(u, v)
            nc = c + d(u, v) + (TURN if du is not None and dv != du else 0)
            if nc < best.get((v, dv), 1e18):
                best[(v, dv)] = nc; prev[(v, dv)] = (u, du); k += 1
                heapq.heappush(pq, (nc, k, v, dv))
    return []

def _simplify(pts):
    """일직선 위의 중간 점을 빼서 꺾이는 점만 남김"""
    out = []
    for p in pts:
        if len(out) >= 2:
            (x1, y1), (x2, y2) = out[-2], out[-1]
            if (x2 - x1) * (p[1] - y2) == (y2 - y1) * (p[0] - x2):
                out[-1] = p; continue
        if not out or out[-1] != p: out.append(p)
    return out

def map_data(at, target_fixture=None):
    """도면 그리기에 필요한 값 묶음: 구역 · 집기 · 시설 · 경로 · 도면 크기"""
    pos, _ = _graph()
    pts = []
    if target_fixture:
        pts = [pos[n] for n in path_between(at, target_fixture) if n in pos]
        fx = one("SELECT * FROM fixtures WHERE id=?", (target_fixture,))
        if pts and fx:                              # 마지막: 통로에서 집기 가장자리까지
            lx, ly = pts[-1]
            ex = min(max(lx, fx["x"]), fx["x"] + fx["w"]); ey = min(max(ly, fx["y"]), fx["y"] + fx["h"])
            pts.append((ex + (6 if ex < lx else -6 if ex > lx else 0), ey + (6 if ey < ly else -6 if ey > ly else 0)))
    try: zones = rows("SELECT * FROM zones")
    except sqlite3.OperationalError: zones = []
    fixtures = rows("SELECT * FROM fixtures")
    W = max([f["x"] + f["w"] for f in fixtures] + [620]) + 20
    H = max([f["y"] + f["h"] for f in fixtures] + [470])
    start = pts[0] if pts else (pos.get(at) or (0, 0))   # '나' 표시: 지금 선 자리(통로)
    return {"fixtures": fixtures, "zones": zones, "at": at, "target": target_fixture, "W": W, "H": H + 20, "start": start,
            "path": " ".join(f"{x},{y}" for x, y in _simplify(pts))}

def _plen(path):
    """경로 길이 (통로 좌표 기준)"""
    pos, _ = _graph()
    return sum(abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1]) for a, b in zip(path, path[1:]))

def fix_route(start, stops):
    """직원 동선: start 에서 출발해 고칠 집기를 모두 들르는 가장 짧은 순서 (7곳 이하는 전부 비교, 넘으면 가까운 곳부터)"""
    from itertools import permutations
    stops = [s for s in dict.fromkeys(stops) if s and s != start]
    if not stops: return [], []
    pts = [start] + stops
    cost, seg = {}, {}
    for a_ in pts:
        for b_ in pts:
            if a_ != b_:
                pth = path_between(a_, b_); seg[a_, b_] = pth
                cost[a_, b_] = _plen(pth) if pth else 1e9
    if len(stops) <= 7:
        order = min(permutations(stops), key=lambda o: sum(cost[x, y] for x, y in zip((start,) + o, o)))
    else:
        order, cur, left = [], start, set(stops)
        while left:
            nxt = min(left, key=lambda z: cost[cur, z]); order.append(nxt); left.discard(nxt); cur = nxt
    nodes = []
    for x, y in zip([start] + list(order), order):
        nodes += seg[x, y][1:] if nodes else seg[x, y]
    return list(order), nodes

def fix_map(start, groups):
    """신고함 위 '고칠 곳 돌기' 지도: 고칠 집기에 순서 번호 + 한 번에 도는 길"""
    fxs = [k for k in groups if k and k != "위치 없음"]
    order, nodes = fix_route(start, fxs)
    pos, _ = _graph()
    m = map_data(start)
    pts = [pos[n] for n in nodes if n in pos]
    m.update(path=" ".join(f"{x},{y}" for x, y in _simplify(pts)), start=(pts[0] if pts else m["start"]),
             stops={fx: {"no": i + 1, "n": len(groups.get(fx, []))} for i, fx in enumerate(order)})
    return m, order, round(_plen(nodes) / 50) if nodes else 0     # 도면 50 ≈ 1m (대략)

FACILITY_KINDS = ("입구", "계산대", "피팅룸", "창고", "기둥")

def shelves():
    """옷을 둘 수 있는 집기만 (입구·계산대·피팅룸·창고·기둥 제외) — 직원 화면 선반 고르기용"""
    return rows(f"SELECT * FROM fixtures WHERE kind NOT IN ({','.join('?' * len(FACILITY_KINDS))}) ORDER BY id", FACILITY_KINDS)

# ---------- 필터: 소분류 사진 타일 + 핏·패턴 ----------
SUB_ORDER = [x for v in V.SUBCATS.values() for x in v]
FIT_ORDER = ["오버핏", "레귤러핏", "슬림핏", "크롭"]
PAT_ORDER = ["무지", "로고·그래픽", "스트라이프", "체크", "꽃무늬"]
FACET_COL = {"cat": "category", "sub": "subcat", "color": "color", "fit": "fit", "pattern": "pattern"}

def _order(vals, order):
    return sorted(vals, key=lambda v: order.index(v) if v in order else 999)

def subcat_tiles():
    """대분류별 소분류 목록. 각 소분류의 대표 사진 1장 + 상품 수 (유니클로식 사진 그리드)"""
    tiles = {c: [] for c in CATS}
    for r in rows("SELECT category, subcat, COUNT(*) n FROM items GROUP BY category, subcat"):
        if r["category"] not in tiles: continue
        rep = one("""SELECT * FROM items WHERE category=? AND subcat=?
                     ORDER BY (image LIKE 'photos/%') DESC, sku LIMIT 1""", (r["category"], r["subcat"]))
        tiles[r["category"]].append({"sub": r["subcat"], "n": r["n"], "rep": rep})
    for c in tiles:
        tiles[c].sort(key=lambda t: SUB_ORDER.index(t["sub"]) if t["sub"] in SUB_ORDER else 999)
    return tiles

def apply_filters(items, sel, skip=None):
    for k, col in FACET_COL.items():
        if k != skip and sel.get(k):
            items = [i for i in items if (i.get(col) or "") == sel[k]]
    return items

def facet_counts(base, sel):
    """각 필터 줄에 보여줄 값과 개수. 자기 줄은 빼고 나머지 조건으로 센다 (다른 값으로 바꿔 누를 수 있게)"""
    out = {}
    orders = {"sub": SUB_ORDER, "color": list(COLORS), "fit": FIT_ORDER, "pattern": PAT_ORDER}
    for k, order in orders.items():
        if k == "sub" and not sel.get("cat"):
            continue                                   # 종류 줄은 대분류를 고른 뒤에만
        c = Counter(i.get(FACET_COL[k]) for i in apply_filters(base, sel, skip=k))
        out[k] = [(v, c[v]) for v in _order([v for v in c if v], order)]
    return out

# ---------- 손님 화면 ----------
@app.route("/")
def root(): return redirect(url_for("go", at="ENTRANCE"))

@app.route("/go")
def go():
    at = request.args.get("at", "ENTRANCE")
    here = one("SELECT * FROM fixtures WHERE id=?", (at,))
    return render_template("home.html", at=at, here=here, tiles=subcat_tiles(),
                           tab=request.args.get("tab", "상의"), cats=list(CATS), colors=COLORS)

@app.route("/search")
def search():
    at = request.args.get("at", "ENTRANCE")
    q = request.args.get("q", "").strip()
    sel = {k: request.args.get(k, "").strip() for k in FACET_COL}
    base = rows("SELECT * FROM items")
    note = ""
    if q:
        base, parsed, note = S.text_search(base, q, limit=999)
        log_event("search", src=q[:40])
    items = apply_filters(base, sel)
    if not q:
        picked = [v for v in (sel["cat"], sel["sub"], sel["color"], sel["fit"], sel["pattern"]) if v]
        note = " · ".join(picked) if picked else "전체 상품"
    return render_template("results.html", at=at, items=decorate(items), q=q, sel=sel,
                           facets=facet_counts(base, sel), note=note,
                           cat=sel["cat"], color=sel["color"], cats=list(CATS), colors=COLORS)

def first_file(field="photo"):
    """같은 이름의 입력이 둘(촬영/고르기)이라 실제로 고른 파일 하나만 꺼낸다."""
    for f in request.files.getlist(field):
        if f and f.filename:
            return f
    return None

def save_upload(raw, prefix):
    """올린 사진을 static/uploads/ 에 저장하고 static 기준 경로를 돌려준다."""
    name = f"{prefix}_{uuid.uuid4().hex[:10]}.jpg"
    (UPLOADS / name).write_bytes(V.prepare(raw))
    return f"uploads/{name}"

@app.route("/search/photo", methods=["POST"])
def search_photo():
    """사진 → AI 특징 추출 → 매장 옷과 비교 → 1등 + 비슷한 추천 3~4개.
       AI를 못 쓰면(키 없음·인터넷·한도) 예전 '대표 색' 검색으로 자동 전환."""
    at = request.form.get("at", "ENTRANCE")
    f = first_file()
    if not f:
        return redirect(url_for("go", at=at))
    raw = f.read()
    log_event("photo")
    try:
        qimg = save_upload(raw, "q")
    except Exception:
        return render_template("results.html", at=at, items=[], q="", cat="", color="",
                               note="사진 파일을 읽지 못했어요. 다른 사진으로 해보세요.",
                               cats=list(CATS), colors=COLORS)
    try:
        q = V.analyze(raw)
    except V.VisionError as e:
        f.stream.seek(0)
        rgb = S.dominant_color(f)
        items, cname = S.photo_search(rows("SELECT * FROM items"), COLORS, rgb)
        note = f"AI 분석을 못 했어요({e}) · 대신 사진의 대표 색 '{cname}' 기준으로 찾았어요"
        return render_template("results.html", at=at, items=decorate(items[:8]), q="",
                               cat="", color="", note=note, cats=list(CATS),
                               colors=COLORS, swatch="#%02x%02x%02x" % rgb)
    ranked = V.rank(decorate(rows("SELECT * FROM items")), q, limit=5)
    best = ranked[0] if ranked else None
    return render_template("photo_result.html", at=at, q=q, qimg=qimg,
                           best=best, others=ranked[1:], colors=COLORS,
                           verdict=V.verdict(best["score"]) if best else None)

@app.route("/item/<sku>")
def item(sku):
    at = request.args.get("at", "ENTRANCE")
    it = one("SELECT * FROM items WHERE sku=?", (sku,))
    if not it: return "없는 상품", 404
    it = decorate([it])[0]
    src = request.args.get("src", "")
    log_event("tag" if src == "tag" else "view", sku, src or None)     # ⑨ 옷 태그 QR로 들어왔는지
    fx = it["place"]["fixture_id"] if it["place"] else None
    return render_template("item.html", src=src, at=at, it=it, map=map_data(at, fx),
                           flag=loc_flag(it), similar=similar_items(it), **help_data(it))

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]

def sort_sizes(sizes):
    return sorted(sizes, key=lambda s: (SIZE_ORDER.index(s["size"]) if s["size"] in SIZE_ORDER else 99, s["size"]))

def help_data(it):
    """'찾는 게 없나요?' 패널에 쓸 값: 같은 옷 다른 색 / 사이즈별 대안"""
    # 같은 옷(이름이 같은 상품)의 다른 색. 없으면 같은 종류·같은 핏의 다른 색
    same = rows("SELECT * FROM items WHERE name=? AND sku!=?", (it["name"], it["sku"]))
    basis = "같은 옷"
    if not same:
        same = rows("SELECT * FROM items WHERE subcat=? AND fit=? AND color!=? AND sku!=?",
                    (it["subcat"], it["fit"], it["color"], it["sku"]))
        basis = f"같은 종류({it['subcat']}·{it['fit']})"
    by_color = {}
    for o in decorate(same):                      # 색마다 1개 (위치 등록된 것 우선)
        if o["color"] == it["color"]: continue
        if o["color"] not in by_color or (o["place"] and not by_color[o["color"]]["place"]):
            by_color[o["color"]] = o
    other_colors = [by_color[c] for c in COLORS if c in by_color]

    # 사이즈: 재고 0인 사이즈는 '같은 종류·같은 색' 중 그 사이즈가 있는 옷을 최대 3개
    sizes = sort_sizes(it["sizes"])
    alts = {}
    for sz in sizes:
        if sz["qty"] > 0: continue
        cand = rows("""SELECT i.* FROM items i JOIN stock s ON s.sku=i.sku
                       WHERE i.subcat=? AND i.sku!=? AND s.size=? AND s.qty>0
                       ORDER BY (i.color=?) DESC, (i.fit=?) DESC LIMIT 3""",
                    (it["subcat"], it["sku"], sz["size"], it["color"], it["fit"]))
        alts[sz["size"]] = decorate(cand)
    return {"other_colors": other_colors, "color_basis": basis, "hsizes": sizes, "size_alts": alts}

# ---------- 신고 / 직원 호출 ----------
WAIT_MIN = 10          # 손님이 기다리는 최대 시간(분). 넘으면 '시간 초과'

def ts(): return now().isoformat(timespec="seconds")
def mins_since(t):
    return int(max(0, (now() - datetime.datetime.fromisoformat(t)).total_seconds()) // 60) if t else 0

def stock_total(sku):
    return one("SELECT COALESCE(SUM(qty),0) n FROM stock WHERE sku=?", (sku,))["n"]
def wh_total(sku):
    return one("SELECT COALESCE(SUM(wh),0) n FROM stock WHERE sku=?", (sku,))["n"]

def open_none(sku, fx):
    """이 자리에 대한 열린 '여기 없어요' 신고 수 (기기 기준 중복 제거)"""
    return one("""SELECT COUNT(DISTINCT COALESCE(device, 'r'||id)) c FROM reports
                  WHERE sku=? AND fixture_id=? AND kind='none' AND done=0""", (sku, fx))["c"]

def loc_flag(it):
    """상품 화면에 띄울 위치 신뢰 표시: 신고 있음 / 손님 확인"""
    p = it.get("place")
    if not p: return None
    n = open_none(it["sku"], p["fixture_id"])
    if n: return ("warn", "최근 '여기 없어요' 신고가 있었어요. 직원이 확인 중이에요")
    c = p.get("confirmed_at")
    if c and c >= (p.get("updated_at") or "") and mins_since(c) < 360:
        m = mins_since(c)
        when = "방금" if m < 1 else (f"{m}분 전" if m < 60 else f"{m//60}시간 전")
        return ("ok", f"{when} 다른 손님이 이 자리에서 찾았어요")
    return None

def similar_items(it, limit=3):
    """대안: 같은 종류 · 위치 있음 · 재고 있음. 같은 색 → 같은 핏 순"""
    cand = rows("""SELECT i.* FROM items i
                   WHERE i.subcat=? AND i.sku!=?
                     AND EXISTS (SELECT 1 FROM placements p WHERE p.sku=i.sku AND p.active=1)
                     AND (SELECT COALESCE(SUM(qty),0) FROM stock s WHERE s.sku=i.sku) > 0
                   ORDER BY (i.color=?) DESC, (i.fit=?) DESC, i.sku LIMIT ?""",
                (it["subcat"], it["sku"], it["color"], it["fit"], limit))
    return decorate(cand)

def expire_waits():
    """10분 넘게 기다린 호출은 '시간 초과'로"""
    cut = (now() - datetime.timedelta(minutes=WAIT_MIN)).isoformat(timespec="seconds")
    db().execute("""UPDATE reports SET wait_state='expired',
                      done=CASE WHEN kind='none' THEN done ELSE 1 END,
                      resolution=CASE WHEN kind='none' THEN resolution ELSE '시간 초과' END,
                      resolved_at=CASE WHEN kind='none' THEN resolved_at ELSE ? END
                    WHERE wait_state IN ('waiting','going') AND wait_at < ?""", (ts(), cut))
    db().commit()

def close_loc_reports(sku, fx, resolution):
    q = "UPDATE reports SET done=1, resolution=?, resolved_at=? WHERE sku=? AND kind='none' AND done=0"
    args = [resolution, ts(), sku]
    if fx: q += " AND fixture_id=?"; args.append(fx)
    db().execute(q, args)

# ---------- 손님: 신고 / 호출 ----------
@app.route("/api/report", methods=["POST"])
def report():
    d = request.get_json(force=True)
    sku, fx, kind = d.get("sku"), d.get("fixture") or None, d.get("kind", "none")
    detail, size, dev = (d.get("detail") or "")[:40], (d.get("size") or "")[:6], (d.get("device") or "")[:40] or None
    if kind not in ("none", "size", "call"): kind = "call"

    if kind == "none":
        # 같은 기기가 같은 옷을 이미 신고했으면 새로 만들지 않음
        old = one("""SELECT id FROM reports WHERE sku=? AND kind='none' AND done=0 AND device=?""", (sku, dev)) if dev else None
        if old:
            rid, msg = old["id"], "이미 알려주셨어요. 직원이 확인할게요"
        else:
            rid = db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,device) VALUES (?,?,?,?,?)",
                               (sku, fx, "none", ts(), dev)).lastrowid
            msg = "알려주셔서 고마워요. 다음 손님은 정확한 위치를 안내받아요"
        delisted = False
        if fx and open_none(sku, fx) >= 2:     # 서로 다른 손님 2명이 신고 → 안내에서 내림
            db().execute("UPDATE placements SET active=0 WHERE sku=? AND fixture_id=?", (sku, fx))
            delisted = True
        db().commit()
        return jsonify(ok=True, id=rid, message=msg, delisted=delisted, stock=stock_total(sku), wh=wh_total(sku), busy=is_busy())

    # 호출·사이즈 요청: 손님이 그 자리에서 기다림
    rid = db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,detail,size,device,wait_state,wait_at)
                          VALUES (?,?,?,?,?,?,?,'waiting',?)""",
                       (sku, fx, kind, ts(), detail, size, dev, ts())).lastrowid
    db().commit()
    log_event("call", sku, kind)
    return jsonify(ok=True, id=rid, message="직원에게 알렸어요. 이 자리에서 잠시만 기다려 주세요")

@app.route("/api/report/<int:rid>/wait", methods=["POST"])
def report_wait(rid):
    """'여기 없어요' 뒤에 '찾아주세요'를 고른 경우: 같은 신고에 대기 표시"""
    d = request.get_json(force=True)
    size = (d.get("size") or "")[:6]
    db().execute("""UPDATE reports SET wait_state='waiting', wait_at=?, size=?,
                    detail=? WHERE id=?""", (ts(), size, f"위치에 없음{(' · ' + size) if size else ''}", rid))
    db().commit()
    log_event("call", None, "none")
    return jsonify(ok=True, id=rid, message="직원에게 알렸어요. 이 자리에서 잠시만 기다려 주세요")

@app.route("/api/report/<int:rid>")
def report_status(rid):
    """손님 화면이 몇 초마다 물어봄: 지금 어디까지 처리됐나"""
    expire_waits()
    r = one("SELECT * FROM reports WHERE id=?", (rid,))
    if not r: return jsonify(state="gone")
    return jsonify(state=r["wait_state"] or "none", minutes=mins_since(r["wait_at"]), size=r["size"])

@app.route("/api/found", methods=["POST"])
def found():
    """손님이 '찾았어요' → 이 위치가 맞다는 확인 + 같은 자리 신고는 취소"""
    d = request.get_json(force=True)
    sku, fx = d.get("sku"), d.get("fixture")
    db().execute("UPDATE placements SET confirmed_at=? WHERE sku=? AND fixture_id=? AND active=1", (ts(), sku, fx))
    db().execute("""UPDATE reports SET done=1, resolution='손님이 찾음', resolved_at=?
                    WHERE sku=? AND fixture_id=? AND kind='none' AND done=0 AND wait_state IN ('', 'expired')""",
                 (ts(), sku, fx))
    db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,device,done,resolution,resolved_at)
                    VALUES (?,?,'found',?,?,1,'손님이 찾음',?)""", (sku, fx, ts(), d.get("device"), ts()))   # 점장 요약용 기록
    db().commit()
    return jsonify(ok=True, message="고마워요! 덕분에 다음 손님 안내가 더 정확해져요")

# ---------- 직원 화면 ----------
# ---------- 찜목록 ----------
def _dev(v): return (v or "").strip()[:40]

@app.route("/api/like", methods=["POST"])
def api_like():
    """하트 누르기: on 값이 없으면 토글"""
    d = request.get_json(force=True) or {}
    sku, dev = d.get("sku"), _dev(d.get("device"))
    if not dev or not one("SELECT sku FROM items WHERE sku=?", (sku,)):
        return jsonify(ok=False), 400
    has = one("SELECT 1 x FROM likes WHERE device=? AND sku=?", (dev, sku)) is not None
    on = (not has) if d.get("on") is None else bool(d.get("on"))
    if on and not has:
        db().execute("INSERT INTO likes VALUES (?,?,?)", (dev, sku, ts())); log_event("like", sku)
    elif not on and has:
        db().execute("DELETE FROM likes WHERE device=? AND sku=?", (dev, sku))
    db().commit()
    skus = [r["sku"] for r in rows("SELECT sku FROM likes WHERE device=? ORDER BY ts DESC", (dev,))]
    return jsonify(ok=True, on=on, skus=skus,
                   message="찜목록에 담았어요" if on else "찜목록에서 뺐어요")

@app.route("/likes")
def likes():
    """손님: 찜한 옷 모아 보기 — 매장 안에서 돌아보기 좋게 구역·선반 순으로 정렬"""
    at, dev = request.args.get("at", "ENTRANCE"), _dev(request.args.get("d"))
    its = rows("""SELECT i.* FROM likes l JOIN items i ON i.sku=l.sku WHERE l.device=? ORDER BY l.ts DESC""", (dev,)) if dev else []
    its = decorate(its)
    for it in its:
        it["sizes"] = sort_sizes(it["sizes"])
        it["floor"] = sum(s["qty"] for s in it["sizes"]); it["wh"] = sum(s["wh"] for s in it["sizes"])
    its.sort(key=lambda it: (0, it["place"]["zone"], it["place"]["fixture_id"]) if it["place"] else (1, "", ""))
    return render_template("likes.html", at=at, items=its, has_dev=bool(dev))

@app.route("/staff")
def staff():
    last = setting("last_check") or datetime.date.today().isoformat()
    days = (datetime.date.today() - datetime.date.fromisoformat(last)).days
    return render_template("staff.html",
                           fixtures=shelves(),
                           items=rows("SELECT sku, name, color FROM items ORDER BY sku"),
                           priority=priority_list(), check_days=days, CHECK_DAYS=CHECK_DAYS,
                           samples=rows("""SELECT b.code, b.season, i.sku, i.name, i.color FROM barcodes b JOIN items i ON i.sku=b.sku
                                           WHERE i.sku IN ('UQ003','UQ004','UQ073') ORDER BY i.sku, b.season"""))

def priority_list(limit=10):
    """⑦ 다시 찍을 옷: 자주 찾는데(조회·검색) 위치가 오래됐거나 신고가 있는 옷부터"""
    since = (now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    out = []
    for it in rows("SELECT sku, name, color, image FROM items"):
        p = placement_of(it["sku"])
        views = one("SELECT COUNT(*) n FROM events WHERE sku=? AND kind IN ('view','tag') AND ts>=?", (it["sku"], since))["n"]
        reps = one("SELECT COUNT(*) n FROM reports WHERE sku=? AND kind='none' AND done=0", (it["sku"],))["n"]
        age = (now() - datetime.datetime.fromisoformat(p["updated_at"])).days if p else 99
        if not p or age >= CHECK_DAYS or reps:
            why = []
            if reps: why.append(f"'없어요' {reps}건")
            if not p: why.append("위치 없음")
            elif age >= CHECK_DAYS: why.append(f"{age}일 전 등록")
            if views: why.append(f"최근 7일 조회 {views}회")
            out.append({**it, "place": p, "age": age, "views": views, "reps": reps, "why": why,
                        "score": reps * 5 + views * 2 + min(age, 60) / 10 + (3 if not p else 0)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]

@app.route("/staff/confirm/<sku>", methods=["POST"])
def staff_confirm(sku):
    """⑦ '그대로 맞아요': 다시 안 찍고 현재 위치의 등록 시각만 새로"""
    p = placement_of(sku)
    if p:
        db().execute("UPDATE placements SET updated_at=?, updated_by='staff-check' WHERE id=?", (ts(), p["id"]))
        close_loc_reports(sku, p["fixture_id"], "재등록")
        db().commit()
    return redirect(url_for("staff") + "#priority")

@app.route("/staff/checked", methods=["POST"])
def staff_checked():
    """⑦ 진열 점검 완료 → 다음 알림은 14일 뒤"""
    set_setting("last_check", datetime.date.today().isoformat()); db().commit()
    return redirect(url_for("staff"))

@app.route("/api/register", methods=["POST"])
def register():
    """① 바코드(시즌별로 달라도) → 상품으로 묶어서 등록
       ② 한 번 스캔: 사이즈는 원래 한 상품이고, '같은 상품 모든 색'을 켜면 색까지 한 번에"""
    d = request.get_json(force=True)
    code, fx, lv = d.get("sku", ""), d.get("fixture"), d.get("level", "중단")
    it, season = resolve_code(code)
    if not it: return jsonify(ok=False, message=f"모르는 코드: {code}"), 400
    if not one("SELECT 1 FROM fixtures WHERE id=?", (fx,)):
        return jsonify(ok=False, message=f"모르는 선반: {fx}"), 400
    targets = [it]
    if d.get("all_colors"):
        targets = rows("SELECT * FROM items WHERE name=? ORDER BY sku", (it["name"],)) or [it]
    for t in targets:
        db().execute("UPDATE placements SET active=0 WHERE sku=?", (t["sku"],))   # 이전 위치는 내림
        db().execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                     " VALUES (?,?,?,?,?,1)", (t["sku"], fx, lv, ts(), "staff"))
        close_loc_reports(t["sku"], None, "재등록")                              # 관련 위치 신고 처리
    db().commit()
    sizes = rows("SELECT size FROM stock WHERE sku=?", (it["sku"],))
    colors = " · ".join(t["color"] for t in targets)
    note = f" (시즌 바코드 {season} → 같은 상품으로 인식)" if season else ""
    return jsonify(ok=True, count=len(targets),
                   message=f"{it['name']} [{colors}] 사이즈 {len(sizes)}종 → {fx} {lv}{note}")

# ---------- 직원: 실물 옷을 사진으로 등록 (전시회용) ----------
def next_demo_sku():
    n = one("SELECT COUNT(*) c FROM items WHERE sku LIKE 'EX%'")["c"]
    while one("SELECT 1 FROM items WHERE sku=?", (f"EX{n+1:03d}",)): n += 1
    return f"EX{n+1:03d}"

def staff_ai_ctx(**kw):
    return dict(fixtures=shelves(),
                demos=decorate(rows("SELECT * FROM items WHERE is_demo=1 ORDER BY sku")),
                V=V, **kw)

@app.route("/staff/ai")
def staff_ai():
    return render_template("staff_ai.html", step="photo", **staff_ai_ctx())

@app.route("/staff/ai/analyze", methods=["POST"])
def staff_ai_analyze():
    f = first_file()
    if not f:
        return redirect(url_for("staff_ai"))
    raw = f.read()
    img = save_upload(raw, "item")
    err, a = "", {}
    try:
        a = V.analyze(raw)
    except V.VisionError as e:
        err = f"AI 분석 실패: {e} · 아래에서 직접 골라 주세요"
    return render_template("staff_ai.html", step="confirm", img=img, a=a, err=err,
                           fx=request.form.get("fixture"), lv=request.form.get("level", "중단"),
                           **staff_ai_ctx())

@app.route("/staff/ai/save", methods=["POST"])
def staff_ai_save():
    d = request.form
    sku = next_demo_sku()
    color = d.get("color") if d.get("color") in COLORS else "그레이"
    attrs = {k: d.get(k) for k in ("category", "subcat", "color", "pattern", "fit")}
    name = d.get("name", "").strip() or f"{color} {d.get('subcat', '옷')}"
    try:
        price = int(d.get("price") or 0)
    except ValueError:
        price = 0
    db().execute("INSERT INTO items (sku,name,category,subcat,color,hex,fit,price,image,pattern,ai_json,is_demo)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                 (sku, name, d.get("category"), d.get("subcat"), color, COLORS[color],
                  d.get("fit"), price, d.get("img"), d.get("pattern"),
                  json.dumps(attrs, ensure_ascii=False)))
    for part in (d.get("sizes") or "").split(","):           # "S:1,M:2,L:1"
        if ":" in part:
            sz, qty = part.split(":", 1)
            if qty.strip().isdigit():
                db().execute("INSERT INTO stock (sku,size,qty) VALUES (?,?,?)", (sku, sz.strip().upper(), int(qty)))
    db().execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                 " VALUES (?,?,?,?,?,1)",
                 (sku, d.get("fixture"), d.get("level", "중단"),
                  now().isoformat(timespec="seconds"), "staff-ai"))
    db().commit()
    return render_template("staff_ai.html", step="photo",
                           done=f"{sku} · {name} → {d.get('fixture')} {d.get('level')} 등록 완료",
                           **staff_ai_ctx())

@app.route("/staff/ai/delete/<sku>", methods=["POST"])
def staff_ai_delete(sku):
    """잘못 등록한 전시 상품 삭제 (EX로 시작하는 전시용 상품만)"""
    if sku.startswith("EX"):
        for t in ("placements", "stock", "reports"):
            db().execute(f"DELETE FROM {t} WHERE sku=?", (sku,))
        db().execute("DELETE FROM items WHERE sku=?", (sku,))
        db().commit()
    return redirect(url_for("staff_ai"))

@app.route("/info")
def info():
    """손님: 안내 (매장 · 설정 · 내 정보 · 도움말 · 사진 출처)"""
    at = request.args.get("at", "ENTRANCE")
    here = one("SELECT * FROM fixtures WHERE id=?", (at,))
    return render_template("info.html", at=at, here=here)

@app.route("/me")
def me():
    """키·몸무게 입력 (값은 휴대폰 브라우저에만 저장, 서버 저장 없음)"""
    return render_template("me.html")

@app.route("/staff/reports")
def staff_reports():
    expire_waits()
    # ① 손님 대기 중 (지금 가야 함)
    waiting = rows("""SELECT r.*, i.name, i.color, i.image, i.category, f.name fixture_name, f.zone
                      FROM reports r LEFT JOIN items i ON i.sku=r.sku LEFT JOIN fixtures f ON f.id=r.fixture_id
                      WHERE r.wait_state IN ('waiting','going') ORDER BY r.wait_at""")
    for w in waiting:
        w["mins"] = mins_since(w["wait_at"])
        w["label"] = {"none": "위치에 없음", "size": "사이즈 요청", "call": "직원 호출"}.get(w["kind"], w["kind"])
    # ② 위치 고칠 것 (선반별로 묶음)
    loc = rows("""SELECT r.sku, r.fixture_id, COUNT(DISTINCT COALESCE(r.device,'r'||r.id)) n, MIN(r.created_at) first,
                         MAX(r.created_at) last, i.name, i.color, i.image, f.name fixture_name, f.zone,
                         (SELECT p.active FROM placements p WHERE p.sku=r.sku AND p.fixture_id=r.fixture_id
                          ORDER BY p.updated_at DESC LIMIT 1) active,
                         (SELECT p.level FROM placements p WHERE p.sku=r.sku AND p.fixture_id=r.fixture_id
                          ORDER BY p.updated_at DESC LIMIT 1) level
                  FROM reports r LEFT JOIN items i ON i.sku=r.sku LEFT JOIN fixtures f ON f.id=r.fixture_id
                  WHERE r.kind='none' AND r.done=0
                  GROUP BY r.sku, r.fixture_id ORDER BY r.fixture_id, last DESC""")
    groups = {}
    for x in loc:
        x["since"] = mins_since(x["first"])
        groups.setdefault(x["fixture_id"] or "위치 없음", []).append(x)
    # ③ 최근 처리 기록
    history = rows("""SELECT r.*, i.name FROM reports r LEFT JOIN items i ON i.sku=r.sku
                      WHERE r.done=1 AND r.resolution IS NOT NULL ORDER BY r.resolved_at DESC LIMIT 8""")
    start = request.args.get("from") or "COUNTER"
    if not one("SELECT 1 x FROM fixtures WHERE id=?", (start,)): start = "COUNTER"
    fmap, order, meters = fix_map(start, groups)
    groups = {k: groups[k] for k in order + [k for k in groups if k not in order]}   # 도는 순서대로
    return render_template("reports.html", waiting=waiting, groups=groups, history=history,
                           map=fmap, route=order, meters=meters, start=start,
                           starts=[("COUNTER", "계산대"), ("ENTRANCE", "입구")] + [(f["id"], f["id"]) for f in shelves()],
                           busy_mode=setting("busy", "auto"), staff_count=setting("staff_count", "4"),
                           summary=manager_summary(), WAIT_MIN=WAIT_MIN,
                           fixtures=shelves())

@app.route("/staff/summary")
def staff_summary():
    """점장 요약: 응대 지표 · 사용률 · 순위 (신고함에서 분리)"""
    sm = manager_summary()
    m = map_data("ENTRANCE"); m.update(heat=sm["heat"], heat_max=sm["heat_max"], start=(0, 0))
    return render_template("summary.html", summary=sm, map=m)

def manager_summary(days=7):
    since = (now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    top_fx = rows("""SELECT r.fixture_id, f.name, COUNT(*) n FROM reports r LEFT JOIN fixtures f ON f.id=r.fixture_id
                     WHERE r.kind='none' AND r.created_at>=? AND r.fixture_id IS NOT NULL
                     GROUP BY r.fixture_id ORDER BY n DESC LIMIT 3""", (since,))
    top_items = rows("""SELECT r.sku, i.name, i.color, COUNT(*) n FROM reports r LEFT JOIN items i ON i.sku=r.sku
                        WHERE r.kind='none' AND r.created_at>=? GROUP BY r.sku ORDER BY n DESC LIMIT 3""", (since,))
    served = rows("SELECT wait_at, served_at FROM reports WHERE served_at IS NOT NULL AND wait_at>=?", (since,))
    fixed = rows("""SELECT created_at, resolved_at FROM reports WHERE kind='none' AND done=1
                    AND resolution IN ('재등록','위치 이동','재고 없음','오신고') AND created_at>=?""", (since,))
    def avg(pairs):
        v = [(datetime.datetime.fromisoformat(b) - datetime.datetime.fromisoformat(a)).total_seconds() / 60
             for a, b in pairs if a and b]
        return round(sum(v) / len(v), 1) if v else None
    missed = one("SELECT COUNT(*) n FROM reports WHERE wait_state='expired' AND wait_at>=?", (since,))["n"]
    found = one("SELECT COUNT(*) n FROM reports WHERE kind='found' AND created_at>=?", (since,))["n"]
    ev = {r["kind"]: r["n"] for r in rows("SELECT kind, COUNT(*) n FROM events WHERE ts>=? GROUP BY kind", (since,))}
    nones = one("SELECT COUNT(*) n FROM reports WHERE kind='none' AND created_at>=?", (since,))["n"]
    calls = one("SELECT COUNT(*) n FROM reports WHERE wait_at IS NOT NULL AND wait_at>=?", (since,))["n"]
    top_liked = rows("""SELECT l.sku, i.name, i.color, COUNT(*) n,
                               (SELECT COALESCE(SUM(qty),0) FROM stock WHERE sku=l.sku) floor,
                               (SELECT COALESCE(SUM(wh),0) FROM stock WHERE sku=l.sku) wh
                        FROM likes l JOIN items i ON i.sku=l.sku GROUP BY l.sku ORDER BY n DESC, floor ASC LIMIT 5""")
    usage = {"like": ev.get("like", 0), "search": ev.get("search", 0), "photo": ev.get("photo", 0), "tag": ev.get("tag", 0),
             "view": ev.get("view", 0) + ev.get("tag", 0), "kiosk": ev.get("kiosk", 0), "calls": calls,
             "found_rate": round(found * 100 / (found + nones)) if (found + nones) else None}
    heat = {r["fixture_id"]: r["n"] for r in rows("""SELECT fixture_id, COUNT(*) n FROM reports
                 WHERE kind='none' AND created_at>=? AND fixture_id IS NOT NULL GROUP BY fixture_id""", (since,))}
    zone_n = Counter()
    for f in rows("SELECT id, zone FROM fixtures"):
        if heat.get(f["id"]): zone_n[f["zone"]] += heat[f["id"]]
    return {"heat": heat, "heat_max": max(heat.values(), default=0), "zone_n": zone_n.most_common(),
            "usage": usage, "top_liked": top_liked, "top_fx": top_fx, "top_items": top_items, "serve_min": avg([(r["wait_at"], r["served_at"]) for r in served]),
            "fix_min": avg([(r["created_at"], r["resolved_at"]) for r in fixed]), "missed": missed, "found": found}

# ---------- 발표 시연 모드: 버튼 한 번으로 시연 상황 만들기 / 지우기 ----------
DEMO_SKU = "UQ127"          # 스카이블루 옥스포드 셔츠 (A-R1) — '여기 없어요' 시연용
DEMO_WH_SKU = "UQ018"       # 캔버스 로우 스니커즈 — 키오스크 창고 사이즈 요청 시연용
DEMO_HOT = [("A-R1", 9), ("C-H1", 7), ("D-S2", 6), ("B-T1", 5), ("A-H2", 4), ("C-W1", 3),
            ("B-W1", 2), ("D-S1", 2), ("P-T1", 2), ("A-T1", 1), ("C-H2", 1)]

def demo_clear():
    """시연으로 만든 신고·기록을 지우고, 시연 때문에 안내에서 내려간 옷을 원래 자리로 되돌린다"""
    skus = [r["sku"] for r in rows("SELECT DISTINCT sku FROM reports WHERE device LIKE 'demo%'")]
    db().execute("DELETE FROM reports WHERE device LIKE 'demo%'")
    db().execute("DELETE FROM events WHERE src='demo'")
    for sku in set(skus + [DEMO_SKU]):
        if not one("SELECT 1 x FROM placements WHERE sku=? AND active=1", (sku,)):
            last = one("SELECT id FROM placements WHERE sku=? ORDER BY id DESC LIMIT 1", (sku,))
            if last: db().execute("UPDATE placements SET active=1 WHERE id=?", (last["id"],))
    db().commit()

def demo_history():
    """지난 7일 기록 채우기: 점장 요약 · 지도 히트맵이 비어 보이지 않게 (device='demo')"""
    import random
    rnd, t0 = random.Random(7), now()
    def back(): return t0 - datetime.timedelta(days=rnd.uniform(0.2, 6.8))
    for fx, n in DEMO_HOT:
        items = [r["sku"] for r in rows("SELECT sku FROM placements WHERE fixture_id=? AND active=1", (fx,))] or [None]
        for _ in range(n):
            c = back(); r_ = c + datetime.timedelta(minutes=rnd.randint(4, 45))
            db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,done,device,resolution,resolved_at)
                            VALUES (?,?,'none',?,1,'demo',?,?)""", (rnd.choice(items), fx, c.isoformat(timespec="seconds"),
                         rnd.choice(["재등록", "재등록", "위치 이동", "오신고"]), r_.isoformat(timespec="seconds")))
    skus = [r["sku"] for r in rows("SELECT sku FROM placements WHERE active=1")]
    for _ in range(46):
        db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,done,device) VALUES (?,?,'found',?,1,'demo')",
                     (rnd.choice(skus), None, back().isoformat(timespec="seconds")))
    for i in range(13):
        w = back(); sv = w + datetime.timedelta(minutes=rnd.uniform(1.5, 7))
        db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,done,device,wait_state,wait_at,served_at,resolution,resolved_at)
                        VALUES (?,?,?,?,1,'demo',?,?,?,?,?)""",
                     (rnd.choice(skus), "ENTRANCE", "size" if i % 2 else "call", w.isoformat(timespec="seconds"),
                      "expired" if i == 12 else "served", w.isoformat(timespec="seconds"),
                      None if i == 12 else sv.isoformat(timespec="seconds"), "전달 완료", sv.isoformat(timespec="seconds")))
    for kind, n in [("search", 64), ("photo", 19), ("tag", 27), ("view", 118), ("kiosk", 41), ("call", 13)]:
        for _ in range(n):
            db().execute("INSERT INTO events (kind,sku,src,ts) VALUES (?,?,'demo',?)", (kind, None, back().isoformat(timespec="seconds")))
    db().commit()

def demo_live():
    """지금 일어나는 상황: 손님 2명이 '여기 없어요' → 안내에서 내려감 + 키오스크 창고 사이즈 요청"""
    p = one("SELECT fixture_id FROM placements WHERE sku=? AND active=1", (DEMO_SKU,))
    fx = p["fixture_id"] if p else "A-R1"
    for i, mins in ((1, 3), (2, 1)):
        db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,device) VALUES (?,?,'none',?,?)",
                     (DEMO_SKU, fx, (now() - datetime.timedelta(minutes=mins)).isoformat(timespec="seconds"), f"demo-{i}"))
    db().execute("UPDATE placements SET active=0 WHERE sku=? AND fixture_id=?", (DEMO_SKU, fx))
    for j, ofx in enumerate(["B-T1", "D-S2", "C-H1"]):      # 다른 선반에도 1건씩 → 신고함 '한 번에 도는 길'
        o = one("SELECT sku FROM placements WHERE fixture_id=? AND active=1 ORDER BY sku LIMIT 1", (ofx,))
        if o: db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,device) VALUES (?,?,'none',?,?)",
                           (o["sku"], ofx, (now() - datetime.timedelta(minutes=6 + j * 4)).isoformat(timespec="seconds"), f"demo-f{j}"))
    db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,detail,size,device,wait_state,wait_at)
                    VALUES (?,'ENTRANCE','size',?,'260 창고에서 가져다주세요 (키오스크)','260','demo-k','waiting',?)""",
                 (DEMO_WH_SKU, ts(), ts()))
    db().commit()

@app.route("/demo", methods=["GET", "POST"])
def demo():
    act, msg = request.form.get("act"), None
    if act == "clear":   demo_clear(); msg = "시연 기록을 지웠어요"
    elif act == "hist":  demo_clear(); demo_history(); msg = "지난 7일 기록을 채웠어요 — 점장 요약을 열어 보세요"
    elif act == "live":  demo_live(); msg = "손님 신고 5건(선반 4곳) · 창고 사이즈 요청 1건을 만들었어요 — 신고함을 열어 보세요"
    elif act == "all":   demo_clear(); demo_history(); demo_live(); msg = "발표 준비 끝! 아래 순서대로 열어 보세요"
    it = one("SELECT * FROM items WHERE sku=?", (DEMO_SKU,))
    p = one("SELECT fixture_id FROM placements WHERE sku=? ORDER BY active DESC, id DESC LIMIT 1", (DEMO_SKU,))
    cnt = {"hist": one("SELECT COUNT(*) n FROM reports WHERE device='demo'")["n"],
           "live": one("SELECT COUNT(*) n FROM reports WHERE device LIKE 'demo-%' AND done=0")["n"]}
    return render_template("demo.html", msg=msg, it=it, fx=(p or {}).get("fixture_id") or "A-R1",
                           wh=one("SELECT * FROM items WHERE sku=?", (DEMO_WH_SKU,)), cnt=cnt)

@app.route("/staff/reports/<int:rid>/wait", methods=["POST"])
def staff_wait_action(rid):
    """손님 대기 카드: 가는 중 / 전달 완료 / 재고 없음"""
    act = request.form.get("act")
    r = one("SELECT * FROM reports WHERE id=?", (rid,))
    if r:
        if act == "going":
            db().execute("UPDATE reports SET wait_state='going' WHERE id=?", (rid,))
        elif act in ("served", "nostock"):
            db().execute("UPDATE reports SET wait_state=?, served_at=? WHERE id=?", (act, ts(), rid))
            if r["kind"] != "none":                       # 호출·사이즈 요청은 여기서 끝
                db().execute("UPDATE reports SET done=1, resolution=?, resolved_at=? WHERE id=?",
                             ("전달 완료" if act == "served" else "재고 없음", ts(), rid))
            if act == "nostock":                           # 그 사이즈(없으면 전체) 재고 0
                if r["size"]: db().execute("UPDATE stock SET qty=0, wh=0 WHERE sku=? AND size=?", (r["sku"], r["size"]))
                else: db().execute("UPDATE stock SET qty=0, wh=0 WHERE sku=?", (r["sku"],))
        db().commit()
    return redirect(url_for("staff_reports"))

@app.route("/staff/reports/fix", methods=["POST"])
def staff_fix():
    """위치 고칠 것: 찾아서 재등록 / 다른 곳에 있었음 / 재고 없음 / 그 자리에 있음(오신고)"""
    f = request.form
    sku, fx, act = f.get("sku"), f.get("fixture") or None, f.get("act")
    last = one("SELECT * FROM placements WHERE sku=? AND fixture_id IS ? ORDER BY updated_at DESC LIMIT 1", (sku, fx))
    level = (last or {}).get("level") or "중단"
    def place(to_fx, to_lv):
        db().execute("UPDATE placements SET active=0 WHERE sku=?", (sku,))
        db().execute("""INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)
                        VALUES (?,?,?,?,'staff',1)""", (sku, to_fx, to_lv, ts()))
    if act == "reregister" and fx:
        place(fx, level); res = "재등록"
    elif act == "move" and f.get("to"):
        place(f.get("to"), f.get("level") or "중단"); res = "위치 이동"
    elif act == "nostock":
        db().execute("UPDATE stock SET qty=0, wh=0 WHERE sku=?", (sku,))
        db().execute("UPDATE placements SET active=0 WHERE sku=?", (sku,)); res = "재고 없음"
    elif act == "false" and last:
        db().execute("UPDATE placements SET active=1, confirmed_at=? WHERE id=?", (ts(), last["id"])); res = "오신고"
    else:
        return redirect(url_for("staff_reports"))
    close_loc_reports(sku, fx, res)
    db().commit()
    return redirect(url_for("staff_reports"))

# ---------- ⑪ 매장 설정 / ④ 바쁨 모드 ----------
STORE_TYPES = {"대형": "직원보다 손님이 훨씬 많은 대형 매장 (where:wear 효과 가장 큼)",
               "중형": "일반 매장", "소형": "직원이 바로 보이는 작은 매장 (키오스크·호출은 끄는 걸 권장)"}

@app.route("/staff/settings", methods=["GET", "POST"])
def staff_settings():
    if request.method == "POST":
        f = request.form
        st = f.get("store_type") if f.get("store_type") in STORE_TYPES else "대형"
        set_setting("store_type", st)
        set_setting("staff_count", max(1, int(f.get("staff_count") or 1)))
        set_setting("kiosk", "1" if f.get("kiosk") else "0")
        set_setting("busy", f.get("busy") if f.get("busy") in ("auto", "on", "off") else "auto")
        db().commit()
        return redirect(url_for("staff_settings", saved=1))
    return render_template("settings.html", s={k: setting(k) for k in ("store_type", "staff_count", "kiosk", "busy")},
                           types=STORE_TYPES, busy_now=is_busy(), saved=request.args.get("saved"))

@app.route("/staff/busy", methods=["POST"])
def staff_busy():
    set_setting("busy", request.form.get("mode", "auto")); db().commit()
    return redirect(request.referrer or url_for("staff_reports"))

# ---------- 사진 출처 (Pexels API 이용 조건) ----------
@app.route("/credits")
def credits():
    import csv
    f = BASE / "photo_credits.csv"
    rs = []
    if f.exists():
        rs = list(csv.DictReader(open(f, encoding="utf-8-sig")))
    return render_template("credits.html", rows=rs)

# ---------- 키오스크 ----------
@app.route("/kiosk")
def kiosk():
    """어르신용: 대분류 → 종류(사진) → 색 → 결과(+선택: 핏·무늬로 더 좁히기). AI 사진검색은 없음."""
    if setting("kiosk", "1") != "1":                    # ⑪ 이 매장은 키오스크를 쓰지 않음
        return render_template("kiosk_off.html")
    step = request.args.get("step", "cat")
    cat = request.args.get("cat", "")
    sub = request.args.get("sub", "")
    color = request.args.get("color", "")
    fit = request.args.get("fit", "")
    pattern = request.args.get("pattern", "")
    items, tiles, colors, kf = [], [], [], {}
    if step == "sub":
        tiles = subcat_tiles().get(cat, [])
    elif step == "color":
        pool = apply_filters(rows("SELECT * FROM items"), {"cat": cat, "sub": sub})
        c = Counter(i["color"] for i in pool)
        colors = [(name, COLORS[name], c[name]) for name in COLORS if c[name]]
    elif step == "result":
        sel = {"cat": cat, "sub": sub, "color": color, "fit": fit, "pattern": pattern}
        base = rows("SELECT * FROM items")
        items = decorate(apply_filters(base, sel))
        fc = facet_counts(base, sel)            # 핏·무늬: 지금 조건 안에 실제로 있는 값만 버튼으로
        kf = {k: fc.get(k, []) for k in ("fit", "pattern")}
        log_event("kiosk", src=f"{cat}/{sub}/{color}")
    catinfo = {}
    if step == "cat":                                    # 첫 화면 타일: 대분류별 상품 수 + 대표 사진
        for c, ts_ in subcat_tiles().items():
            if ts_: catinfo[c] = {"n": sum(t["n"] for t in ts_), "rep": ts_[0]["rep"]}
    return render_template("kiosk.html", step=step, cat=cat, sub=sub, color=color, catinfo=catinfo,
                           fit=fit, pattern=pattern, kf=kf,
                           cats=list(CATS), tiles=tiles, kcolors=colors, items=items)

@app.route("/kiosk/item/<sku>")
def kiosk_item(sku):
    it = decorate([one("SELECT * FROM items WHERE sku=?", (sku,))])[0]
    it["sizes"] = sort_sizes(it["sizes"])
    fx = it["place"]["fixture_id"] if it["place"] else None
    return render_template("kiosk_item.html", it=it, map=map_data("ENTRANCE", fx), flag=loc_flag(it))

@app.route("/kiosk/print/<sku>")
def kiosk_print(sku):
    """③ 감열식 영수증 프린터(80mm)용 종이 지도. 키오스크에서 눌러 바로 출력."""
    it = decorate([one("SELECT * FROM items WHERE sku=?", (sku,))])[0]
    fx = it["place"]["fixture_id"] if it["place"] else None
    log_event("print", sku)
    # 종이 지도에 '이 옷' QR: 행거 앞에서 찍으면 그 옷 화면이 열려 '찾는 게 없나요?'(신고·재고·직원)를 바로 쓸 수 있다
    link = f"{public_base()}/item/{sku}?at={fx or 'ENTRANCE'}&src=paper"
    return render_template("kiosk_print.html", it=it, map=map_data("ENTRANCE", fx),
                           printed=now().strftime("%m/%d %H:%M"), qr=qr_data_uri(link), qr_link=link)

def public_base():
    """폰으로 찍을 주소. WW_PUBLIC_URL이 있으면 그것, 키오스크가 localhost로 열려 있으면 노트북의 내부 IP로 바꾼다."""
    env = os.environ.get("WW_PUBLIC_URL")
    if env: return env.rstrip("/")
    base = request.host_url.rstrip("/")
    host = request.host.split(":")[0]
    if host in ("localhost", "127.0.0.1"):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]; s.close()
            port = request.host.split(":")[1] if ":" in request.host else "80"
            base = f"http://{ip}:{port}"
        except OSError:
            pass
    return base

def qr_data_uri(text):
    import base64, io, qrcode
    buf = io.BytesIO()
    qrcode.make(text, box_size=6, border=1).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))     # 맥은 5000번을 AirPlay가 쓰므로 5001
    print(f"\n  → http://localhost:{port}  (휴대폰은 http://<노트북IP>:{port}/go?at=A-H1)\n")
    app.run(host="0.0.0.0", port=port, debug=True)
