# -*- coding: utf-8 -*-
"""where:wear 프로토타입 웹 서버  (실행: python app.py → http://localhost:5000)

화면
  /go?at=A-H1    손님: 선반 QR로 들어오는 시작점 (검색·필터·사진검색)
  /item/WW001    상품 상세 + 2D 길안내 + 갱신 시각 + 없어요/직원호출
  /kiosk         어르신용 키오스크 (큰 글씨·3터치·글자입력 없음)
  /staff         직원: 선반 QR 1번 → 옷 QR 연속 스캔으로 위치 등록
  /staff/reports 직원: 신고·호출 목록
"""
import datetime, json, os, re, sqlite3, time, uuid
from collections import Counter, deque
from urllib.parse import urlencode
from pathlib import Path
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import search as S
import i18n
import vision as V
from seed import COLORS, CATS

BASE = Path(__file__).parent
DBFILE = Path(os.environ.get("WW_DB", BASE / "store.db"))
UPLOADS = BASE / "static" / "uploads"
STORE_NAME = os.environ.get("WW_STORE", "유니클로 명동점")   # 고객 화면(안내)에 보이는 매장 이름
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024     # 사진 15MB까지

def _secret():
    """로그인 세션 서명용 열쇠: 처음 실행할 때 flask_secret.key 로 만들어 두고 계속 씀 (*.key 는 깃허브에 안 올라감)"""
    if os.environ.get("WW_SECRET"): return os.environ["WW_SECRET"]
    f = BASE / "flask_secret.key"
    if not f.exists():
        import secrets
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()
app.secret_key = _secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30))

DEFAULT_STAFF = "김준구,류한솔,이준혁"      # 직원 이름 고르기 기본 명단 (설정에서 바꿈)

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
                     ("resolution", "TEXT"), ("resolved_at", "TEXT"),
                     ("escalated_at", "TEXT"),      # 2분 동안 아무도 안 받아서 전체 직원에게 다시 알린 시각
                     ("staff", "TEXT"),             # 가는 중 / '제가 갈게요'를 누른 직원 이름
                     ("resolved_by", "TEXT")]:      # 처리한 직원 이름
        if col not in rcols:
            con.execute(f"ALTER TABLE reports ADD COLUMN {col} {typ}")
    if "seg" not in {r[1] for r in con.execute("PRAGMA table_info(events)")}:
        con.execute("ALTER TABLE events ADD COLUMN seg TEXT")     # 검색한 손님의 성별·나이대 (예: F20) — MY에 적은 경우만
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
    # 직원 휴대폰 잠금화면 알림 구독 (Web Push)
    con.execute("CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, created TEXT, agent TEXT)")
    # ④⑪ 매장 설정 / ⑦ 진열 점검일
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in [("store_type", "대형"), ("staff_count", "4"), ("kiosk", "1"), ("busy", "auto"),
                 ("last_check", datetime.date.today().isoformat()), ("staff_names", DEFAULT_STAFF)]:
        con.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
    # ⑩ 사용률 지표
    con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, sku TEXT, src TEXT, ts TEXT)")
    # 찜목록: 로그인 없이 휴대폰별 익명 id(device)로 저장
    con.execute("CREATE TABLE IF NOT EXISTS likes (device TEXT, sku TEXT, ts TEXT, PRIMARY KEY (device, sku))")
    # 피팅룸 반납: 반납받을 때 태그 찍기(returned_at) → 제자리에 걸 때 선반에서 다시 찍기(rehung_at). 위치(placements)는 그대로
    con.execute("""CREATE TABLE IF NOT EXISTS fitting_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT,
                   fixture_id TEXT, level TEXT, returned_at TEXT, returned_by TEXT, rehung_at TEXT, rehung_by TEXT,
                   demo INTEGER DEFAULT 0)""")
    # 직원이 지운 옷: 되살릴 수 있게 상품·재고·바코드를 통째로 보관
    con.execute("CREATE TABLE IF NOT EXISTS deleted_items (sku TEXT PRIMARY KEY, data TEXT, deleted_at TEXT, deleted_by TEXT)")
    # 손님 로그인 (QR): 비밀번호는 해시로만 저장, profile = MY 정보(키·몸무게·내 사이즈·설정) JSON
    con.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE,
                   pw TEXT, created TEXT, profile TEXT)""")
    try: con.execute("ALTER TABLE users ADD COLUMN nickname TEXT")   # 닉네임 ('~님'으로 부를 이름)
    except sqlite3.OperationalError: pass
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
def is_large(): return setting("store_type", "대형") == "대형"
CROWD_N = 3                          # 대형 매장: 기다리는 손님이 이만큼 넘으면 손님 화면에 '조금 늦을 수 있어요'
def waiting_n(): return one("SELECT COUNT(*) n FROM reports WHERE wait_state IN ('waiting','going')")["n"]
def is_busy():
    """바쁨 모드: 켜기/끄기, 자동이면 '직원 2명 이하' 또는 '기다리는 손님 수 ≥ 직원 수'
       대형 매장은 늘 바빠서 바쁨 모드를 쓰지 않음 (대신 붐빔 안내 crowd)"""
    if is_large(): return False
    mode = setting("busy", "auto")
    if mode in ("on", "off"): return mode == "on"
    staff = int(setting("staff_count", "4") or 4)
    waiting = one("SELECT COUNT(*) n FROM reports WHERE wait_state IN ('waiting','going')")["n"]
    return staff <= 2 or waiting >= staff

def cur_staff():
    """이 휴대폰을 쓰는 직원 이름 (로그인 없음 · 직원 화면에서 한 번 고르면 쿠키 ww_staff 에 저장)"""
    from urllib.parse import unquote
    return unquote(request.cookies.get("ww_staff") or "").strip()[:12]
def staff_names():
    return [n.strip() for n in setting("staff_names", DEFAULT_STAFF).split(",") if n.strip()]

# ---------- ⑩ 사용률 기록 ----------
def cur_seg():
    """MY에 적은 성별·나이대 (휴대폰이 쿠키 ww_seg로 보냄). 예: 'F20' = 20대 여성"""
    v = (request.cookies.get("ww_seg") or "").upper()
    return v if re.fullmatch(r"[MF](10|20|30|40|50)", v) else None

def log_event(kind, sku=None, src=None):
    try:
        seg = cur_seg() if kind == "search" else None
        db().execute("INSERT INTO events (kind,sku,src,ts,seg) VALUES (?,?,?,?,?)", (kind, sku, src, now().isoformat(timespec="seconds"), seg))
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
    staff_badge, crowd = 0, False
    try:
        wn = waiting_n()
        crowd = is_large() and wn >= CROWD_N               # 대형 매장 붐빔 안내
        if request.path.startswith("/staff"): staff_badge = wn   # 직원 탭바 '신고함' 숫자 = 기다리는 손님 수
    except Exception: pass
    me_user, me_profile = None, None
    if not request.path.startswith("/staff") and session.get("uid"):
        try:
            u = one("SELECT username, nickname, profile FROM users WHERE id=?", (session["uid"],))
            if u: me_user, me_profile = u["nickname"] or u["username"], json.loads(u["profile"] or "null")
        except Exception: pass
    sname, snames = "", []
    if request.path.startswith("/staff"):
        try: sname, snames = cur_staff(), staff_names()
        except Exception: pass
    return dict(imgsrc=imgsrc, with_args=with_args, store_name=STORE_NAME, busy=busy, staff_badge=staff_badge,
                crowd=crowd, staff_name=sname, staff_names=snames, me_user=me_user, me_profile=me_profile,
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

def decorate(items, at=None):
    """상품 목록에 위치·신선도·재고를 붙인다. at 을 주면 거기서 걷는 거리도"""
    out = []
    for it in items:
        p = placement_of(it["sku"])
        it = dict(it)
        it["place"] = p
        it["walk"] = walk(at, p["fixture_id"]) if (at and p) else None
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

def route_steps(pts, zones, target):
    """꺾이는 점마다 '오른쪽으로 꺾어 12m' 같은 안내 문장 (종이 지도용). 처음엔 입구에서 매장 안쪽(위)을 보고 선다"""
    if len(pts) < 2: return [], []
    def unit(a_, b_):
        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
        return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
    def near_zone(p_):
        best = None
        for z in zones:
            dx = max(z["x"] - p_[0], 0, p_[0] - (z["x"] + z["w"])); dy = max(z["y"] - p_[1], 0, p_[1] - (z["y"] + z["h"]))
            d = dx + dy
            if best is None or d < best[0]: best = (d, z)
        return f"{best[1]['id']}구역({best[1]['name']})" if best and best[0] < 60 else None
    segs = []                                  # [방향, 길이, 끝점] — 짧은 꺾임(2m 미만)은 앞 구간에 합침
    for a_, b_ in zip(pts, pts[1:]):
        d = unit(a_, b_); ln = abs(b_[0] - a_[0]) + abs(b_[1] - a_[1])
        if segs and (segs[-1][0] == d or ln < 2 * PX_PER_M):
            segs[-1][1] += ln; segs[-1][2] = b_
            if segs[-1][0] != d and segs[-1][1] - ln < 2 * PX_PER_M: segs[-1][0] = d
        else: segs.append([d, ln, b_])
    if len(segs) > 1 and segs[-1][1] < 3 * PX_PER_M:     # 마지막 3m 미만 꺾임은 '도착' 안내로 대신
        segs.pop()
    steps, turns, head = [], [], (0, -1)       # 입구에서 안쪽(위)을 보고 시작
    for i, (d, ln, end) in enumerate(segs):
        cr = head[0] * d[1] - head[1] * d[0]
        turn = "앞으로" if d == head else ("오른쪽으로 꺾어" if cr > 0 else "왼쪽으로 꺾어" if cr < 0 else "뒤로 돌아")
        if i == 0: turn = "입구에서 " + ("앞으로" if d == (0, -1) else ("오른쪽으로" if d == (1, 0) else "왼쪽으로"))
        m = max(1, round(ln / PX_PER_M))
        z = near_zone(end)
        steps.append({"no": i + 1, "turn": turn, "m": m, "by": z if (not steps or steps[-1]["zone"] != z) else None, "zone": z})
        if i > 0: turns.append({"no": i + 1, "x": segs[i - 1][2][0], "y": segs[i - 1][2][1]})
        head = d
    if target:                                 # 도착: 찾는 집기가 진행 방향의 어느 쪽인지
        f = one("SELECT * FROM fixtures WHERE id=?", (target,))
        if f:
            ex, ey = segs[-1][2]; tx, ty = f["x"] + f["w"] / 2 - ex, f["y"] + f["h"] / 2 - ey
            cr = head[0] * ty - head[1] * tx
            dot = head[0] * tx + head[1] * ty
            side = "바로 앞" if abs(cr) < 25 and dot > 0 else ("오른쪽" if cr > 0 else "왼쪽")
            steps.append({"no": 0, "turn": side, "m": 0, "by": None, "zone": None, "arrive": True})
    return steps, turns

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
    steps, turns = route_steps(_simplify(pts[:-1]) if len(pts) > 2 else [], zones, target_fixture)
    fixtures = rows("SELECT * FROM fixtures")
    W = max([f["x"] + f["w"] for f in fixtures] + [620]) + 20
    H = max([f["y"] + f["h"] for f in fixtures] + [470])
    start = pts[0] if pts else (pos.get(at) or (0, 0))   # '나' 표시: 지금 선 자리(통로)
    return {"fixtures": fixtures, "zones": zones, "at": at, "target": target_fixture, "W": W, "H": H + 20, "start": start,
            "steps": steps, "turns": turns,
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
    return m, order, round(_plen(nodes) / PX_PER_M) if nodes else 0

PX_PER_M = 20          # 도면 20 ≈ 1m (매장 가로 860 ≈ 43m)
_WALK = {}
def walk(at, fx):
    """at → fx 걷는 거리(m)·시간(초). 같은 (출발, 도착)은 기억해 둔다"""
    if not at or not fx: return None
    key = (_GRAPH.get("n"), at, fx)
    if key not in _WALK:
        pth = path_between(at, fx)
        m = round(_plen(pth) / PX_PER_M) if pth else None
        _WALK[key] = {"m": max(m, 1), "sec": max(5, round(m / 1.1 / 5) * 5)} if m is not None else None
    return _WALK[key]

def direction_text(fx_id):
    """입구에서 본 방향을 쉬운 말로 (키오스크 · 종이 지도용): '들어와서 오른쪽 가운데'"""
    f = one("SELECT * FROM fixtures WHERE id=?", (fx_id,))
    e = one("SELECT * FROM fixtures WHERE id='ENTRANCE'")
    if not f or not e: return ""
    cx, cy = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
    ex = e["x"] + e["w"] / 2
    side = "왼쪽" if cx < ex - 120 else ("오른쪽" if cx > ex + 120 else "정면")
    depth = "바로 앞" if cy > 580 else ("가운데" if cy > 270 else "가장 안쪽")
    return f"입구로 들어와서 {side} {depth}" if side != "정면" else f"입구로 들어와서 정면 {depth}"

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
# ---------- 언어 (모드별로 따로: 손님 QR · 키오스크 · 직원) ----------
LANG_COOKIE = {"q": "ww_lang_q", "k": "ww_lang_k", "s": "ww_lang_s"}

def mode_of(path):
    if path.startswith("/kiosk"): return "k"
    if path.startswith(("/staff", "/demo", "/api/register")): return "s"
    return "q"

def cur_lang():
    path = request.path
    if path.startswith("/api/"):                          # API는 부른 화면(Referer)의 모드를 따른다
        from urllib.parse import urlsplit
        path = urlsplit(request.referrer or "").path or path
    m = mode_of(path)
    v = request.cookies.get(LANG_COOKIE[m])
    if v in ("ko", "en"): return v
    if m == "q":                                          # 손님 휴대폰: 처음엔 휴대폰 언어를 따름
        best = request.accept_languages.best_match(["ko", "en"])
        return "en" if best == "en" else "ko"
    return "ko"

@app.context_processor
def _lang_ctx():
    try: return {"LANG": cur_lang(), "LMODE": mode_of(request.path)}
    except Exception: return {"LANG": "ko", "LMODE": "q"}

@app.route("/lang")
def set_lang():
    """?m=q|k|s &to=ko|en &next=돌아갈 주소"""
    m = request.args.get("m", "q"); to = request.args.get("to", "ko")
    nxt = request.args.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//"): nxt = "/"
    r = redirect(nxt)
    if m in LANG_COOKIE and to in ("ko", "en"):
        r.set_cookie(LANG_COOKIE[m], to, max_age=(None if m == "k" else 31536000), samesite="Lax")
    return r

@app.after_request
def _translate(r):
    try:
        if r.direct_passthrough or r.status_code >= 300 or cur_lang() != "en": return r
        ct = r.content_type or ""
        if ct.startswith("text/html"):
            r.set_data(i18n.html(r.get_data(as_text=True)))
        elif ct.startswith("application/json"):
            d = r.get_json(silent=True)
            if d is not None: r.set_data(json.dumps(i18n.json_obj(d), ensure_ascii=False))
        r.headers["Content-Language"] = "en"
        r.vary.add("Cookie")
    except Exception as e:
        app.logger.warning("i18n: %s", e)
    return r

@app.route("/favicon.ico")
def favicon():
    """주소창·탭·방문 기록에 뜨는 아이콘 (브라우저가 /favicon.ico를 따로 찾음)"""
    r = app.send_static_file("logo/favicon.ico"); r.headers["Cache-Control"] = "no-cache"; return r

@app.route("/")
def root(): return redirect(url_for("go", at="ENTRANCE"))

@app.route("/go")
def go():
    at = request.args.get("at", "ENTRANCE")
    here = one("SELECT * FROM fixtures WHERE id=?", (at,))
    seg = cur_seg()
    popular, rising, by_seg = search_trends(seg)
    hero, ranking = home_hero(), home_ranking(at)
    for it in ranking: it["sizes"] = sort_sizes(it["sizes"])
    tiles = subcat_tiles()
    return render_template("home.html", popular=popular, rising=rising, seg=seg, by_seg=by_seg, hero=hero, ranking=ranking,
                           seg_label=seg_label(seg), at=at, here=here, tiles=tiles,
                           slides=home_slides(at, hero), chips=home_chips(tiles), mm=mini_map(at),
                           tloc={w: term_place(w) for w in popular + rising}, splace=sub_places(),
                           now_hm=now().strftime("%H:%M"),
                           tab=request.args.get("tab", "상의"), cats=list(CATS), colors=COLORS)

# ---------- 홈 (참고 디자인 반영): 배너 슬라이드 · 바로가기 칩 · 한눈에 보는 매장 지도 ----------
def _zone_of(fx_id):
    f = one("SELECT zone FROM fixtures WHERE id=?", (fx_id,)) if fx_id else None
    return f["zone"] if f else None

def _hashtags(fx_ids, n=3):
    if not fx_ids: return ""
    q = ",".join("?" * len(fx_ids))
    subs = rows(f"""SELECT i.subcat, COUNT(*) c FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1
                    WHERE p.fixture_id IN ({q}) GROUP BY i.subcat ORDER BY c DESC LIMIT {n}""", tuple(fx_ids))
    return " ".join("#" + r["subcat"] for r in subs)

def home_slides(at, hero):
    """배너: 신상품 매대 · 할인 매대 · 아우터 구역 (+ 맨 끝 사진으로 찾기). 거리는 지금 QR 자리 기준"""
    out = []
    for h in hero:
        w = walk(at, h["fx"])
        out.append({"href": f"/search?at={at}&fx={h['fx']}", "img": h["rep"], "tag": "신상" if h["tag"] == "NEW" else "할인",
                    "title": "이번 주 신상품,\n입구 앞에 모았어요" if h["tag"] == "NEW" else "할인 매대에서\n가볍게 골라 보세요",
                    "loc": "P구역" + (f" · 여기서 {w['m']}m" if w else ""), "tags": _hashtags([h["fx"]]), "n": h["n"]})
    cfx = [f["id"] for f in rows("SELECT id FROM fixtures WHERE zone='C'")]
    if cfx:
        q = ",".join("?" * len(cfx))
        rep = one(f"""SELECT i.* FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1 WHERE p.fixture_id IN ({q})
                      ORDER BY (i.image LIKE 'photos/%') DESC, i.price DESC LIMIT 1""", tuple(cfx))
        if rep:
            w = walk(at, "C-H1")
            out.append({"href": f"/search?at={at}&cat=아우터", "img": rep, "tag": "아우터",
                        "title": "따뜻한 아우터는\nC구역에 모여 있어요", "loc": "C구역" + (f" · 여기서 {w['m']}m" if w else ""),
                        "tags": _hashtags(cfx), "n": None})
    return out

def home_chips(tiles):
    out = []
    for c in CATS:
        ts = tiles.get(c) or []
        if ts: out.append({"label": c, "href": f"/search?cat={c}", "img": ts[0]["rep"]})
    rep = lambda fx: one("""SELECT i.* FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1 WHERE p.fixture_id=?
                            ORDER BY (i.image LIKE 'photos/%') DESC LIMIT 1""", (fx,))
    out += [{"label": "신상", "href": "/search?fx=P-T1", "img": rep("P-T1")},
            {"label": "세일", "href": "/search?fx=P-T2", "img": rep("P-T2")},
            {"label": "피팅룸", "href": "/map?to=FIT", "icon": "door"},
            {"label": "계산대", "href": "/map?to=COUNTER", "icon": "card"}]
    return out

ZONE_HREF = {"A": "/search?cat=상의", "B": "/search?cat=하의", "C": "/search?cat=아우터", "D": "/search?cat=신발", "P": "/search?fx=P-T1"}
ZONE_LABEL = {"P": "신상 · 세일"}

def mini_map(at):
    """홈 '지금 매장 한눈에 보기': 구역 상자만 간단히 (위치는 실제 도면 좌표를 %로)"""
    fixtures = rows("SELECT * FROM fixtures")
    W = max([f["x"] + f["w"] for f in fixtures] + [620]) + 20
    H = max([f["y"] + f["h"] for f in fixtures] + [470]) + 20
    pc = lambda r: {"l": round(r["x"] / W * 100, 2), "t": round(r["y"] / H * 100, 2),
                    "w": round(r["w"] / W * 100, 2), "h": round(r["h"] / H * 100, 2)}
    zones = [{**z, **pc(z), "label": ZONE_LABEL.get(z["id"], z["name"]), "href": ZONE_HREF.get(z["id"], "/search")}
             for z in rows("SELECT * FROM zones")]
    fac = [{**f, **pc(f), "label": {"FIT": "피팅룸", "COUNTER": "계산대", "STOCK": "창고"}[f["id"]]}
           for f in fixtures if f["id"] in ("FIT", "COUNTER", "STOCK")]
    ent = next((f for f in fixtures if f["id"] == "ENTRANCE"), None)
    me = next((f for f in fixtures if f["id"] == at), None) or ent
    here = {"x": round((me["x"] + me["w"] / 2) / W * 100, 2), "y": round((me["y"] + me["h"] / 2) / H * 100, 2)} if me else None
    return {"W": W, "H": H, "zones": zones, "fac": fac, "ent": {**ent, **pc(ent)} if ent else None,
            "here": here, "here_zone": me["zone"] if me else None}

def term_place(q):
    """인기 검색어 옆 위치(선반 코드): 그 검색어로 가장 잘 맞는 옷이 걸린 곳"""
    try: hits, _, _ = S.text_search(rows("SELECT * FROM items"), q, limit=5)
    except Exception: return None
    for it in hits:
        pl = placement_of(it["sku"])
        if pl: return pl["fixture_id"]
    return None

def sub_places():
    """소분류마다 가장 많이 걸린 선반 (종류별 찾기 타일 아래 위치 표시)"""
    out = {}
    for r in rows("""SELECT i.category, i.subcat, p.fixture_id, COUNT(*) n FROM items i
                     JOIN placements p ON p.sku=i.sku AND p.active=1
                     GROUP BY i.category, i.subcat, p.fixture_id ORDER BY n DESC"""):
        out.setdefault(f"{r['category']}/{r['subcat']}", r["fixture_id"])
    return out

@app.route("/map")
def store_map_page():
    """하단 가운데 '매장지도': 전체 도면 + 시설(피팅룸 · 계산대 · 매대)까지 길 안내"""
    at = request.args.get("at", "ENTRANCE")
    to = request.args.get("to", "").strip() or None
    tofx = one("SELECT * FROM fixtures WHERE id=?", (to,)) if to else None
    if not tofx: to = None
    here = one("SELECT * FROM fixtures WHERE id=?", (at,))
    counts = {r["zone"]: r["n"] for r in rows("""SELECT f.zone, COUNT(DISTINCT p.sku) n FROM placements p
                                                 JOIN fixtures f ON f.id=p.fixture_id WHERE p.active=1 GROUP BY f.zone""")}
    zones = [{**z, "label": ZONE_LABEL.get(z["id"], z["name"]), "href": ZONE_HREF.get(z["id"], "/search"), "n": counts.get(z["id"], 0)}
             for z in rows("SELECT * FROM zones")]
    return render_template("storemap.html", at=at, here=here, to=to, tofx=tofx, map=map_data(at, to),
                           walk=walk(at, to) if to else None, zones=zones,
                           dirtext=direction_text(to) if to else "")

@app.route("/cats")
def cats_page():
    """하단 '카테고리': 종류별 찾기만 크게"""
    at = request.args.get("at", "ENTRANCE")
    return render_template("cats.html", at=at, tiles=subcat_tiles(), splace=sub_places(),
                           tab=request.args.get("tab", "상의"), cats=list(CATS))

# ---------- 홈 배너 · 매장 인기 랭킹 ----------
def home_hero():
    """입구 추천존(P구역) 매대를 배너로: 신상품 · 할인. 사진은 그 매대에 걸린 옷"""
    out = []
    for fx, tag, title, sub in (("P-T1", "NEW", "이번 주 신상품", "입구 바로 앞 신상품 매대"),
                                ("P-T2", "SALE", "할인 매대", "들어와서 오른쪽 할인 매대")):
        its = rows("""SELECT i.* FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1
                      WHERE p.fixture_id=? ORDER BY i.price DESC""", (fx,))
        if its: out.append({"fx": fx, "tag": tag, "title": title, "sub": sub, "n": len(its), "rep": its[0]})
    return out

def home_ranking(at, n=10):
    """이 매장 인기 TOP: 최근 7일 조회 + 찜(×3). 기록이 없으면 재고 많은 순"""
    since = (now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    score = {r["sku"]: r["n"] for r in rows("""SELECT sku, COUNT(*) n FROM events WHERE kind IN ('view','tag')
                                               AND sku IS NOT NULL AND ts>=? GROUP BY sku""", (since,))}
    for r in rows("SELECT sku, COUNT(*) n FROM likes GROUP BY sku"): score[r["sku"]] = score.get(r["sku"], 0) + 3 * r["n"]
    stock = {r["sku"]: r["n"] for r in rows("SELECT sku, SUM(qty) n FROM stock GROUP BY sku")}
    items = [it for it in rows("SELECT * FROM items WHERE COALESCE(is_demo,0)=0")]
    items.sort(key=lambda it: (-score.get(it["sku"], 0), -stock.get(it["sku"], 0), it["sku"]))
    return decorate(items[:n], at)

# ---------- 인기 · 급상승 검색어 (성별·나이대별) ----------
SEG_DEFAULT = {   # 검색 기록이 아직 적을 때 보여줄 기본 검색어 (인기, 급상승)
    None: (["검정 후드티", "와이드 청바지", "오버핏 맨투맨", "숏 패딩", "볼캡", "흰 운동화"],
           ["바람막이", "가디건", "니트", "코트", "후드집업", "부츠"]),
    "M":  (["검정 후드티", "오버핏 맨투맨", "와이드 청바지", "숏 패딩", "조거팬츠", "흰 운동화"],
           ["바람막이", "후드집업", "니트", "볼캡", "코트", "부츠"]),
    "F":  (["와이드 청바지", "가디건", "니트", "스커트", "블라우스", "숏 패딩"],
           ["코트", "후드집업", "부츠", "가방", "맨투맨", "바람막이"]),
    "M40": (["셔츠", "슬랙스", "니트", "코트", "패딩", "구두"], ["가디건", "바람막이", "조끼", "벨트", "운동화", "재킷"]),
    "F40": (["가디건", "블라우스", "슬랙스", "코트", "니트", "패딩"], ["스커트", "부츠", "가방", "재킷", "셔츠", "조끼"]),
}

def seg_label(seg):
    if not seg: return None
    return f"{'50대 이상' if seg[1:] == '50' else seg[1:] + '대'} {'남성' if seg[0] == 'M' else '여성'}"

def search_trends(seg, n=6):
    """인기 = 최근 14일 많이 찾은 순, 급상승 = 최근 하루가 그 전 13일 하루 평균보다 많이 늘어난 순.
       MY에 성별·나이를 적었으면 같은 성별·나이대 손님 기록으로 (기록이 적으면 성별만 → 전체 순으로 넓힘)."""
    t = now()
    d14 = (t - datetime.timedelta(days=14)).isoformat(timespec="seconds")
    d1 = (t - datetime.timedelta(days=1)).isoformat(timespec="seconds")
    ok = lambda q: any(S.parse_query(q).values())            # 알아듣는 검색어만 (오타·장난 입력 제외)
    def fetch(cond, args):
        rs = rows(f"""SELECT src, SUM(ts>=?) recent, COUNT(*) n FROM events WHERE kind='search' AND src IS NOT NULL
                      AND src!='' AND src!='demo' AND ts>=? {cond} GROUP BY src""", (d1, d14, *args))
        return [r for r in rs if ok(r["src"])]
    # 기록이 충분한 가장 좁은 범위부터 (같은 성별·나이대 → 같은 성별). 그래도 적으면 그 성별·나이대 기본 검색어로 채움
    scopes = [("AND seg=?", (seg,)), ("AND seg LIKE ?", (seg[0] + "%",))] if seg else [("", ())]
    data = []
    for cond, args in scopes:
        data = fetch(cond, args)
        if sum(r["n"] for r in data) >= 10: break
    popular = [r["src"] for r in sorted(data, key=lambda r: -r["n"])][:n]
    def growth(r):
        before = (r["n"] - r["recent"]) / 13
        return (r["recent"] + 1) / (before + 1)
    top3 = popular[:3]                       # 늘 1~3위인 검색어는 '급상승'에서 뺌
    rising = [r["src"] for r in sorted([r for r in data if r["recent"] >= 2 and growth(r) >= 1.5 and r["src"] not in top3],
                                       key=lambda r: (-growth(r), -r["recent"]))][:n]
    dkey = seg if seg in SEG_DEFAULT else (seg[0] + ("40" if seg[1:] in ("40", "50") else "") if seg else None)
    dkey = dkey if dkey in SEG_DEFAULT else (seg[0] if seg else None)
    dp, dr = SEG_DEFAULT[dkey]
    popular += [w for w in dp if w not in popular][:n - len(popular)]
    rising += [w for w in dr if w not in rising and w not in popular[:3]][:n - len(rising)]
    return popular, rising, bool(seg)

def smart_search(items, q, limit=999):
    """글자 · 음성 검색: ① 단어 사전(이름 + 생김새 설명) ② 그래도 종류를 모르겠으면 Gemini가 설명을 해석
       → (결과, 알아들은 조건, 안내 문구)"""
    res, parsed, note = S.text_search(items, q, limit=limit)
    if parsed["subs"] or (not any(parsed.values()) and res):       # 종류를 알아들었거나 상품 이름으로 찾음
        return res, parsed, note
    if any(parsed.values()) and len(q.replace(" ", "")) <= 6:      # '블랙', '검정 바지'처럼 짧은 말은 AI 없이
        return res, parsed, note
    try: a = V.interpret(q)
    except Exception: a = None
    if not a or a.get("none") or not (a.get("subcat") or a.get("category")):
        return res, parsed, note
    p2 = {"colors": [a["color"]] if a.get("color") else parsed["colors"], "subs": [a["subcat"]] if a.get("subcat") else [],
          "cats": [a["category"]] if a.get("category") and not a.get("subcat") else [], "fits": [a["fit"]] if a.get("fit") else parsed["fits"]}
    scored = sorted(((S.score_item(it, p2), it) for it in items), key=lambda t: -t[0])
    res2 = [it for sc, it in scored if sc > 0][:limit]
    if not res2: return res, parsed, note
    words = " · ".join(v for v in (a.get("color"), a.get("subcat") or a.get("category"), a.get("fit")) if v)
    return res2, p2, f"설명을 알아듣고 찾았어요 · {words}"

@app.route("/search")
def search():
    at = request.args.get("at", "ENTRANCE")
    q = request.args.get("q", "").strip()
    sel = {k: request.args.get(k, "").strip() for k in FACET_COL}
    base = rows("SELECT * FROM items")
    note = ""
    exact_ids = None
    if q:
        base, parsed, note = smart_search(base, q)
        exact_ids = {it["sku"] for it in base if S.is_exact(it, parsed)}
        log_event("search", src=q[:40])
    items = decorate(apply_filters(base, sel), at)
    fx = request.args.get("fx", "").strip()               # 홈 배너: 특정 매대만 (신상품 · 할인)
    fxrow = one("SELECT * FROM fixtures WHERE id=?", (fx,)) if fx else None
    if fxrow: items = [it for it in items if it["place"] and it["place"]["fixture_id"] == fx]
    if not q:
        picked = [v for v in (sel["cat"], sel["sub"], sel["color"], sel["fit"], sel["pattern"]) if v]
        note = " · ".join(([fxrow["name"]] if fxrow else []) + picked) if (picked or fxrow) else "전체 상품"
    near = lambda it: (it["place"] is None, (it["walk"] or {}).get("m", 999))
    if exact_ids is not None and exact_ids and len(exact_ids) < len(items):
        more = [it for it in items if it["sku"] not in exact_ids]
        items = sorted([it for it in items if it["sku"] in exact_ids], key=near)
    else:
        more, items = [], sorted(items, key=near)
    return render_template("results.html", at=at, items=items, more=more, q=q, sel=sel,
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
        note = f"사진 색 '{cname}'으로 찾았어요"
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
    return render_template("item.html", src=src, at=at, it=it, map=map_data(at, fx), walk=walk(at, fx),
                           flag=loc_flag(it), fitret=fitting_open(sku), similar=similar_items(it), **help_data(it))

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
    if n: return ("warn", "직원이 위치 확인 중이에요")
    c = p.get("confirmed_at")
    if c and c >= (p.get("updated_at") or "") and mins_since(c) < 360:
        m = mins_since(c)
        when = "방금" if m < 1 else (f"{m}분 전" if m < 60 else f"{m//60}시간 전")
        return ("ok", f"{when} 다른 손님이 이 자리에서 찾았어요")
    return None

def similar_items(it, limit=3):
    """대안: 같은 종류 · 위치 있음 · 재고 있음. 같은 색 → 같은 핏 순"""
    cand = rows("""SELECT i.* FROM items i
                   WHERE i.subcat=? AND i.sku!=? AND i.name!=?
                     AND EXISTS (SELECT 1 FROM placements p WHERE p.sku=i.sku AND p.active=1)
                     AND (SELECT COALESCE(SUM(qty),0) FROM stock s WHERE s.sku=i.sku) > 0
                   ORDER BY (i.color=?) DESC, (i.fit=?) DESC, i.sku LIMIT ?""",
                (it["subcat"], it["sku"], it["name"], it["color"], it["fit"], limit))
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

def close_loc_reports(sku, fx, resolution, by=None):
    q = "UPDATE reports SET done=1, resolution=?, resolved_at=?, resolved_by=COALESCE(?, staff) WHERE sku=? AND kind='none' AND done=0"
    args = [resolution, ts(), by or None, sku]
    if fx: q += " AND fixture_id=?"; args.append(fx)
    db().execute(q, args)

# ---------- 손님: 신고 / 호출 ----------
# ---------- 직원 잠금화면 알림 (Web Push · webpush.py) ----------
import threading
try:
    import webpush as WP                     # 필요: pip install cryptography
except Exception as _e:                      # 없어도 앱은 그대로 돌아간다 (알림만 꺼짐)
    WP = None
ESCALATE_MIN = 2                             # 이 시간 동안 아무도 '가는 중'을 안 누르면 전체 직원에게 다시 알림

def _push_all(data):
    """구독한 모든 직원 휴대폰에 보내기 (손님 화면이 기다리지 않게 뒤에서)"""
    if not WP: return
    con = sqlite3.connect(DBFILE); con.row_factory = sqlite3.Row
    subs = [dict(r) for r in con.execute("SELECT endpoint, p256dh, auth FROM push_subs")]
    con.close()
    def run():
        gone = [sub["endpoint"] for sub in subs if WP.send(sub, data) in (404, 410)]
        if gone:
            c = sqlite3.connect(DBFILE); c.executemany("DELETE FROM push_subs WHERE endpoint=?", [(e,) for e in gone]); c.commit(); c.close()
    threading.Thread(target=run, daemon=True).start()

def notify_report(rid, again=False):
    """신고 접수 알림 문장 만들기 → 전체 직원에게"""
    con = sqlite3.connect(DBFILE); con.row_factory = sqlite3.Row
    r = con.execute("""SELECT r.*, i.name, i.color, f.name fxname FROM reports r LEFT JOIN items i ON i.sku=r.sku
                       LEFT JOIN fixtures f ON f.id=r.fixture_id WHERE r.id=?""", (rid,)).fetchone()
    con.close()
    if not r: return
    where = "매장 입구 · 키오스크 앞" if r["fixture_id"] == "ENTRANCE" else (r["fixture_id"] or "위치 없음")
    what = f"{r['name'] or ''}{(' (' + r['color'] + ')') if r['color'] else ''}{(' · ' + r['size']) if r['size'] else ''}"
    if again:
        title = f"⚠ {ESCALATE_MIN}분째 아무도 받지 않았어요"
        body = f"{where} · {what} — 가까운 직원이 '가는 중'을 눌러 주세요"
    elif r["wait_state"] in ("waiting", "going"):
        title = {"size": "사이즈 요청", "call": "직원 호출"}.get(r["kind"], "손님이 기다려요") + f" · {where}"
        body = what + (f" · {r['detail']}" if r["detail"] and r["kind"] == "call" else "")
    else:
        title = f"위치 신고 · {where}"
        body = f"{what} — 손님이 '여기 없어요'를 눌렀어요"
    _push_all({"title": title, "body": body, "tag": f"r{rid}", "url": "/staff/reports" + ("#wait" if r["wait_state"] else "#fix")})

def escalate_waits(con=None):
    """기다리는 요청 중 2분 넘게 아무도 안 받은 것 → 전체 직원에게 한 번 더"""
    con = con or sqlite3.connect(DBFILE)
    cut = (now() - datetime.timedelta(minutes=ESCALATE_MIN)).isoformat(timespec="seconds")
    ids = [r[0] for r in con.execute("""SELECT id FROM reports WHERE wait_state='waiting' AND wait_at<=?
                                          AND escalated_at IS NULL""", (cut,))]
    for rid in ids:
        con.execute("UPDATE reports SET escalated_at=? WHERE id=?", (now().isoformat(timespec="seconds"), rid))
    con.commit()
    for rid in ids: notify_report(rid, again=True)
    return ids

def _watcher():
    while True:
        try: escalate_waits()
        except Exception: pass
        time.sleep(15)
_WATCH = {"on": False}
@app.before_request
def _start_watcher():
    if not _WATCH["on"]:
        _WATCH["on"] = True
        threading.Thread(target=_watcher, daemon=True).start()

@app.route("/sw.js")
def service_worker():
    r = app.send_static_file("sw.js")
    r.headers["Service-Worker-Allowed"] = "/"; r.headers["Cache-Control"] = "no-cache"
    return r

@app.route("/api/push/key")
def push_key():
    if not WP: return jsonify(ok=False, message="서버에 cryptography 패키지가 없어요 (pip install cryptography)")
    return jsonify(ok=True, key=WP.vapid()[1])

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    d = request.get_json(force=True) or {}
    k = d.get("keys") or {}
    if not d.get("endpoint") or not k.get("p256dh") or not k.get("auth"): return jsonify(ok=False), 400
    db().execute("INSERT OR REPLACE INTO push_subs VALUES (?,?,?,?,?)",
                 (d["endpoint"], k["p256dh"], k["auth"], ts(), (request.headers.get("User-Agent") or "")[:120]))
    db().commit()
    return jsonify(ok=True, count=one("SELECT COUNT(*) n FROM push_subs")["n"])

@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    d = request.get_json(force=True) or {}
    db().execute("DELETE FROM push_subs WHERE endpoint=?", (d.get("endpoint", ""),)); db().commit()
    return jsonify(ok=True)

@app.route("/api/push/test", methods=["POST"])
def push_test():
    _push_all({"title": "알림 테스트", "body": "이 휴대폰에 신고 알림이 이렇게 떠요", "tag": "test", "url": "/staff/reports"})
    return jsonify(ok=True)

@app.route("/api/report", methods=["POST"])
def report():
    d = request.get_json(force=True)
    sku, fx, kind = d.get("sku"), d.get("fixture") or None, d.get("kind", "none")
    detail, size, dev = (d.get("detail") or "")[:40], (d.get("size") or "")[:6], (d.get("device") or "")[:40] or None
    if kind not in ("none", "size", "call"): kind = "call"

    if kind == "none":
        # 같은 기기가 같은 옷을 이미 신고했으면 새로 만들지 않음
        new_none = False
        old = one("""SELECT id FROM reports WHERE sku=? AND kind='none' AND done=0 AND device=?""", (sku, dev)) if dev else None
        if old:
            rid, msg = old["id"], "이미 알려주셨어요. 직원이 확인할게요"
        else:
            rid = db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,device) VALUES (?,?,?,?,?)",
                               (sku, fx, "none", ts(), dev)).lastrowid
            msg = "알려주셔서 고마워요"
            new_none = True
        delisted = False
        if fx and open_none(sku, fx) >= 2:     # 서로 다른 손님 2명이 신고 → 안내에서 내림
            db().execute("UPDATE placements SET active=0 WHERE sku=? AND fixture_id=?", (sku, fx))
            delisted = True
        db().commit()
        if new_none: notify_report(rid)
        return jsonify(ok=True, id=rid, message=msg, delisted=delisted, stock=stock_total(sku), wh=wh_total(sku), busy=is_busy())

    # 호출·사이즈 요청: 손님이 그 자리에서 기다림
    rid = db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,detail,size,device,wait_state,wait_at)
                          VALUES (?,?,?,?,?,?,?,'waiting',?)""",
                       (sku, fx, kind, ts(), detail, size, dev, ts())).lastrowid
    db().commit()
    log_event("call", sku, kind)
    notify_report(rid)
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
    notify_report(rid)
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
    p = one("SELECT confirmed_at FROM placements WHERE sku=? AND fixture_id=? AND active=1", (sku, fx))
    closed = [r["id"] for r in rows("""SELECT id FROM reports WHERE sku=? AND fixture_id=? AND kind='none' AND done=0
                                         AND wait_state IN ('', 'expired')""", (sku, fx))]
    db().execute("UPDATE placements SET confirmed_at=? WHERE sku=? AND fixture_id=? AND active=1", (ts(), sku, fx))
    if closed:
        db().execute(f"UPDATE reports SET done=1, resolution='손님이 찾음', resolved_at=? WHERE id IN ({','.join('?' * len(closed))})",
                     [ts()] + closed)
    undo = json.dumps({"prev": p["confirmed_at"] if p else None, "closed": closed})   # 되돌리기에 쓸 이전 상태
    rid = db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,device,done,resolution,resolved_at,detail)
                          VALUES (?,?,'found',?,?,1,'손님이 찾음',?,?)""", (sku, fx, ts(), d.get("device"), ts(), undo)).lastrowid   # 점장 요약용 기록
    db().commit()
    return jsonify(ok=True, id=rid, message="고마워요!")

@app.route("/api/found/undo", methods=["POST"])
def found_undo():
    """'찾았어요'를 잘못 눌렀을 때: 확인 시각 · 취소된 신고 · 기록을 누르기 전으로 되돌림 (같은 휴대폰 · 30분 안)"""
    d = request.get_json(force=True)
    r = one("SELECT * FROM reports WHERE id=? AND kind='found'", (d.get("id"),))
    if not r or (r["device"] or "") != (d.get("device") or "") or mins_since(r["created_at"]) > 30:
        return jsonify(ok=False, message="되돌릴 수 없어요"), 400
    try: u = json.loads(r["detail"] or "{}")
    except ValueError: u = {}
    db().execute("UPDATE placements SET confirmed_at=? WHERE sku=? AND fixture_id=? AND active=1", (u.get("prev"), r["sku"], r["fixture_id"]))
    for cid in u.get("closed") or []:
        db().execute("UPDATE reports SET done=0, resolution=NULL, resolved_at=NULL WHERE id=? AND resolution='손님이 찾음'", (cid,))
    db().execute("DELETE FROM reports WHERE id=?", (r["id"],))
    db().commit()
    return jsonify(ok=True, message="되돌렸어요")

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
    fix_n = one("SELECT COUNT(DISTINCT sku) n FROM reports WHERE kind='none' AND done=0")["n"]   # 손님 '없어요' → 신고함에서 고침
    return render_template("staff.html",
                           fixtures=shelves(),
                           items=rows("SELECT sku, name, color, subcat FROM items ORDER BY name, color"),
                           priority=priority_list(limit=None), fix_n=fix_n,
                           fit_n=one("SELECT COUNT(*) n FROM fitting_returns WHERE rehung_at IS NULL")["n"],
                           samples=rows("""SELECT b.code, b.season, i.sku, i.name, i.color FROM barcodes b JOIN items i ON i.sku=b.sku
                                           WHERE i.sku IN ('UQ003','UQ004','UQ073') ORDER BY i.sku, b.season"""))

def priority_list(limit=10):
    """⑦ 다시 찍을 옷 = 안내할 위치가 없는 옷 (자주 찾는 옷부터).
       손님이 '없어요'라고 한 옷은 신고함 '위치 고칠 것'에서만 처리해 두 곳에 겹쳐 나오지 않게 함"""
    since = (now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    out = []
    for it in rows("SELECT sku, name, color, image FROM items"):
        if placement_of(it["sku"]): continue
        if one("SELECT 1 x FROM reports WHERE sku=? AND kind='none' AND done=0", (it["sku"],)): continue
        views = one("SELECT COUNT(*) n FROM events WHERE sku=? AND kind IN ('view','tag') AND ts>=?", (it["sku"], since))["n"]
        why = ["위치 없음"] + ([f"최근 7일 조회 {views}회"] if views else [])
        out.append({**it, "place": None, "views": views, "why": why, "group": "noloc", "score": views})
    out.sort(key=lambda x: -x["score"])
    return out[:limit] if limit else out

@app.route("/staff/confirm/<sku>", methods=["POST"])
def staff_confirm(sku):
    """⑦ '그대로 맞아요': 다시 안 찍고 현재 위치의 등록 시각만 새로"""
    p = placement_of(sku)
    if p:
        db().execute("UPDATE placements SET updated_at=?, updated_by='staff-check' WHERE id=?", (ts(), p["id"]))
        close_loc_reports(sku, p["fixture_id"], "재등록", cur_staff())
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
    undo, prev_fx = [], None
    for t in targets:
        old = one("SELECT id, fixture_id, level FROM placements WHERE sku=? AND active=1 ORDER BY id DESC LIMIT 1", (t["sku"],))
        if t["sku"] == it["sku"] and old: prev_fx = f"{old['fixture_id']} {old['level']}"
        db().execute("UPDATE placements SET active=0 WHERE sku=?", (t["sku"],))   # 이전 위치는 내림
        nid = db().execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                           " VALUES (?,?,?,?,?,1)", (t["sku"], fx, lv, ts(), "staff")).lastrowid
        close_loc_reports(t["sku"], None, "재등록", cur_staff())                 # 관련 위치 신고 처리
        undo.append([nid, old["id"] if old else None])
    # 피팅룸에서 반납받은 옷을 제자리에 다시 걸며 찍음 → 반납 표시 1벌 지움 (찍은 그 옷만)
    fr = one("SELECT id FROM fitting_returns WHERE sku=? AND rehung_at IS NULL ORDER BY returned_at LIMIT 1", (it["sku"],))
    if fr: db().execute("UPDATE fitting_returns SET rehung_at=?, rehung_by=? WHERE id=?", (ts(), cur_staff() or "staff", fr["id"]))
    db().commit()
    sizes = rows("SELECT size FROM stock WHERE sku=?", (it["sku"],))
    colors = " · ".join(t["color"] for t in targets)
    note = f" (시즌 바코드 {season} → 같은 상품으로 인식)" if season else ""
    fxr = one("SELECT name FROM fixtures WHERE id=?", (fx,))
    return jsonify(ok=True, count=len(targets), undo=undo, name=it["name"], colors=colors, sizes=len(sizes), rehung=bool(fr),
                   fixture=fx, fixture_name=fxr["name"] if fxr else fx, level=lv, prev=prev_fx, season=season,
                   image=url_for("static", filename=it["image"]) if it.get("image") else "",
                   message=f"{it['name']} [{colors}] 사이즈 {len(sizes)}종 → {fx} {lv}{note}")

@app.route("/api/register/undo", methods=["POST"])
def register_undo():
    """방금 등록 되돌리기: 새 위치를 지우고 예전 위치를 다시 안내"""
    pairs = (request.get_json(force=True) or {}).get("undo") or []
    n = 0
    for new_id, old_id in pairs:
        r = one("SELECT sku FROM placements WHERE id=?", (new_id,))
        if not r: continue
        db().execute("DELETE FROM placements WHERE id=?", (new_id,))
        if old_id: db().execute("UPDATE placements SET active=1 WHERE id=?", (old_id,))
        n += 1
    db().commit()
    return jsonify(ok=True, count=n, message=f"{n}건 되돌렸어요")

# ---------- 직원: 실물 옷을 사진으로 등록 (전시회용) ----------
def next_demo_sku():
    n = one("SELECT COUNT(*) c FROM items WHERE sku LIKE 'EX%'")["c"]
    while one("SELECT 1 FROM items WHERE sku=?", (f"EX{n+1:03d}",)) or one("SELECT 1 FROM deleted_items WHERE sku=?", (f"EX{n+1:03d}",)): n += 1
    return f"EX{n+1:03d}"

def staff_ai_ctx(**kw):
    return dict(fixtures=shelves(),
                demos=decorate(rows("SELECT * FROM items WHERE is_demo=1 ORDER BY sku")),
                V=V, **kw)

# ---------- 직원: 옷 목록 · 정보 수정 ----------
@app.route("/staff/items")
def staff_items():
    """옷 목록: 종류별(상의·하의…) 또는 선반별(A-H1…)로 보기"""
    q = (request.args.get("q") or "").strip()
    view = request.args.get("view", "cat")
    cat, fx, zone = request.args.get("cat", ""), request.args.get("fx", ""), request.args.get("zone", "")
    lv = request.args.get("lv", "") if request.args.get("lv", "") in ("상단", "중단", "하단") else ""
    items = decorate(rows("SELECT * FROM items ORDER BY category, name, color"))
    if q:
        words = q.lower().split()
        items = [i for i in items if all(w in f"{i['sku']} {i['name']} {i['color']} {i['subcat']}".lower() for w in words)]
    for it in items:
        it["floor"] = sum(z["qty"] for z in it["sizes"]); it["wh"] = sum(z["wh"] for z in it["sizes"])
    LV = {"상단": 0, "중단": 1, "하단": 2}
    groups, shelves_n, zones = [], [], []
    if view == "shelf":
        by = {}
        for it in items: by.setdefault(it["place"]["fixture_id"] if it["place"] else "", []).append(it)
        allsh = [(f["id"], f["name"], len(by.get(f["id"], [])), f["zone"]) for f in shelves() if by.get(f["id"])]
        if by.get(""): allsh.append(("none", "위치 없음", len(by[""]), "none"))
        zn = {z["id"]: z["name"] for z in rows("SELECT id, name FROM zones")}
        zones = []                                       # 알파벳(구역)별: A 상의 · B 하의 …
        for zid in sorted({z for *_, z in allsh if z != "none"}):
            zones.append((zid, zn.get(zid, ""), sum(n for _, _, n, z in allsh if z == zid)))
        if fx and not zone: zone = next((z for i, _, _, z in allsh if i == fx), "")
        shelves_n = [(i, nm, n) for i, nm, n, z in allsh if not zone or z == zone]
        for fid, fname, n in shelves_n:
            if fx and fx != fid: continue
            lst = sorted(by["" if fid == "none" else fid], key=lambda i: (LV.get(i["place"]["level"], 9) if i["place"] else 9, i["name"]))
            if lv: lst = [i for i in lst if i["place"] and i["place"]["level"] == lv]
            if not lst: continue
            levels = []                                   # 선반 안에서 상단 · 중단 · 하단으로 나눔
            for i in lst:
                k = i["place"]["level"] if i["place"] else ""
                if not levels or levels[-1][0] != k: levels.append((k, []))
                levels[-1][1].append(i)
            groups.append({"id": fid, "name": fname, "items": lst, "levels": levels})
        items = [i for g_ in groups for i in g_["items"]]
    elif cat:
        items = [i for i in items if i["category"] == cat]
    counts = Counter(r["category"] for r in rows("SELECT category FROM items"))
    trash = []
    for r in rows("SELECT * FROM deleted_items ORDER BY deleted_at DESC"):
        d = json.loads(r["data"]); trash.append({**d["item"], "deleted_at": r["deleted_at"], "deleted_by": r["deleted_by"],
                                                  "ago": mins_since(r["deleted_at"])})
    if view == "trash":
        items = []
        if q: trash = [t for t in trash if all(w in f"{t['sku']} {t['name']} {t['color']} {t['subcat']}".lower() for w in q.lower().split())]
    deleted = request.args.get("deleted")
    return render_template("staff_items.html", items=items, groups=groups, shelves_n=shelves_n, view=view, fx=fx,
                           trash=trash, deleted=next((t for t in trash if t["sku"] == deleted), None) if deleted else None,
                           restored=request.args.get("restored"),
                           zones=zones, zone=zone, lv=lv, nonecount=sum(1 for i in items if not i["place"]) if view == "shelf" else 0,
                           q=q, cat=cat, cats=[(c, counts[c]) for c in CATS if counts[c]],
                           total=sum(counts.values()), saved=request.args.get("saved"))

@app.route("/staff/items/<sku>", methods=["GET", "POST"])
def staff_item_edit(sku):
    it = one("SELECT * FROM items WHERE sku=?", (sku,))
    if not it: return "없는 상품", 404
    if request.method == "POST":
        f = request.form
        try: price = max(0, int((f.get("price") or "0").replace(",", "")))
        except ValueError: price = it["price"]
        color = f.get("color") or it["color"]
        db().execute("""UPDATE items SET name=?, price=?, category=?, subcat=?, color=?, hex=?, fit=?, pattern=? WHERE sku=?""",
                     ((f.get("name") or it["name"]).strip(), price, f.get("category") or it["category"], f.get("subcat") or it["subcat"],
                      color, COLORS.get(color, it["hex"]), f.get("fit", it["fit"] or ""), f.get("pattern") or it["pattern"], sku))
        for z in rows("SELECT size FROM stock WHERE sku=?", (sku,)):
            def num(k, d):
                try: return max(0, int(f.get(k, d)))
                except (TypeError, ValueError): return d
            db().execute("UPDATE stock SET qty=?, wh=? WHERE sku=? AND size=?",
                         (num(f"qty_{z['size']}", 0), num(f"wh_{z['size']}", 0), sku, z["size"]))
        fx, lv = f.get("fixture"), f.get("level") or "중단"
        cur = placement_of(sku)
        if fx and (not cur or cur["fixture_id"] != fx or cur["level"] != lv):      # 위치가 바뀌면 새로 등록
            db().execute("UPDATE placements SET active=0 WHERE sku=?", (sku,))
            db().execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active) VALUES (?,?,?,?,?,1)",
                         (sku, fx, lv, ts(), "staff-edit"))
            close_loc_reports(sku, None, "위치 이동", cur_staff())
        db().commit()
        back = request.args.get("back") or "/staff/items"
        if not back.startswith("/staff/items"): back = "/staff/items"
        return redirect(back + ("&" if "?" in back else "?") + f"saved={sku}#i-{sku}")
    it = decorate([it])[0]
    it["sizes"] = sort_sizes(it["sizes"])
    return render_template("staff_item_edit.html", it=it, fixtures=shelves(), colors=COLORS, cats=list(CATS), V=V,
                           fits=["오버핏", "레귤러핏", "슬림핏", "크롭"], back=request.args.get("back", "/staff/items"))

@app.route("/staff/items/<sku>/delete", methods=["POST"])
def staff_item_delete(sku):
    """옷 삭제: 손님 화면·검색·키오스크에서 빠짐. 상품·재고·바코드는 deleted_items 에 보관해 되살릴 수 있음"""
    it = one("SELECT * FROM items WHERE sku=?", (sku,))
    if not it: return redirect(url_for("staff_items"))
    p = placement_of(sku)
    data = {"item": it, "stock": rows("SELECT * FROM stock WHERE sku=?", (sku,)),
            "barcodes": rows("SELECT * FROM barcodes WHERE sku=?", (sku,)), "placement": p["id"] if p else None}
    db().execute("INSERT OR REPLACE INTO deleted_items VALUES (?,?,?,?)", (sku, json.dumps(data, ensure_ascii=False), ts(), cur_staff()))
    for t in ("stock", "barcodes"): db().execute(f"DELETE FROM {t} WHERE sku=?", (sku,))
    db().execute("UPDATE placements SET active=0 WHERE sku=?", (sku,))
    db().execute("""UPDATE reports SET done=1, resolution='상품 삭제', resolved_at=?, resolved_by=?,
                      wait_state=CASE WHEN wait_state IN ('waiting','going') THEN 'expired' ELSE wait_state END
                    WHERE sku=? AND (done=0 OR wait_state IN ('waiting','going'))""", (ts(), cur_staff() or None, sku))
    db().execute("UPDATE fitting_returns SET rehung_at=?, rehung_by='상품 삭제' WHERE sku=? AND rehung_at IS NULL", (ts(), sku))
    db().execute("DELETE FROM items WHERE sku=?", (sku,))
    db().commit()
    return redirect(url_for("staff_items", deleted=sku))

@app.route("/staff/items/<sku>/restore", methods=["POST"])
def staff_item_restore(sku):
    """삭제한 옷 되살리기: 상품·재고·바코드와 마지막 위치를 그대로 돌려놓음"""
    d = one("SELECT * FROM deleted_items WHERE sku=?", (sku,))
    if d and not one("SELECT 1 x FROM items WHERE sku=?", (sku,)):
        data = json.loads(d["data"])
        def put(table, r, verb="INSERT"):
            cols = list(r)
            db().execute(f"{verb} INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])
        put("items", data["item"])
        for r in data.get("stock", []): put("stock", r)
        for r in data.get("barcodes", []): put("barcodes", r, "INSERT OR IGNORE")
        if data.get("placement") and not one("SELECT 1 x FROM placements WHERE sku=? AND active=1", (sku,)):
            db().execute("UPDATE placements SET active=1 WHERE id=?", (data["placement"],))
        db().execute("DELETE FROM deleted_items WHERE sku=?", (sku,))
        db().commit()
    return redirect(url_for("staff_items", restored=sku) + f"#i-{sku}")

# ---------- 직원: 피팅룸 반납 ----------
def fitting_open(sku):
    """피팅룸에 반납돼 아직 제자리에 다시 걸지 않은 벌 수"""
    return one("SELECT COUNT(*) n FROM fitting_returns WHERE sku=? AND rehung_at IS NULL", (sku,))["n"]

def open_returns():
    """제자리로 돌려놓을 옷 (선반 순서 → 오래된 것부터)"""
    rs = rows("""SELECT fr.*, i.name, i.color, i.image, f.name fixture_name FROM fitting_returns fr
                 JOIN items i ON i.sku=fr.sku LEFT JOIN fixtures f ON f.id=fr.fixture_id
                 WHERE fr.rehung_at IS NULL ORDER BY fr.fixture_id IS NULL, fr.fixture_id, fr.returned_at""")
    for r in rs: r["mins"] = mins_since(r["returned_at"])
    return rs

@app.route("/staff/fitting")
def staff_fitting():
    return render_template("fitting.html", rets=open_returns(),
                           items=rows("SELECT sku, name, color, subcat FROM items ORDER BY name, color"))

@app.route("/api/fitting/return", methods=["POST"])
def fitting_return():
    """피팅룸 반납: 옷 태그를 찍으면 기록만 남김. 위치는 그대로, 손님 화면에 '피팅룸에 반납된 옷이 있어요'"""
    code = (request.get_json(force=True) or {}).get("sku", "")
    it, _ = resolve_code(code)
    if not it: return jsonify(ok=False, message=f"모르는 코드: {code}"), 400
    p = placement_of(it["sku"])
    rid = db().execute("INSERT INTO fitting_returns (sku,fixture_id,level,returned_at,returned_by) VALUES (?,?,?,?,?)",
                       (it["sku"], p["fixture_id"] if p else None, p["level"] if p else None, ts(), cur_staff() or None)).lastrowid
    db().commit()
    return jsonify(ok=True, id=rid, sku=it["sku"], name=it["name"], color=it["color"], n=fitting_open(it["sku"]),
                   fixture=p["fixture_id"] if p else "", level=p["level"] if p else "",
                   fixture_name=p["fixture_name"] if p else "",
                   image=url_for("static", filename=it["image"]) if it.get("image") else "",
                   message=f"{it['name']} ({it['color']}) 반납 → 제자리 {p['fixture_id'] + ' ' + p['level'] if p else '위치 없음'}")

@app.route("/api/fitting/undo", methods=["POST"])
def fitting_undo():
    rid = (request.get_json(force=True) or {}).get("id")
    db().execute("DELETE FROM fitting_returns WHERE id=? AND rehung_at IS NULL", (rid,)); db().commit()
    return jsonify(ok=True, message="되돌렸어요")

@app.route("/staff/fitting/<int:rid>/done", methods=["POST"])
def fitting_done(rid):
    """스캔이 안 될 때만: 제자리에 걸었다고 직접 처리"""
    db().execute("UPDATE fitting_returns SET rehung_at=?, rehung_by=? WHERE id=? AND rehung_at IS NULL",
                 (ts(), cur_staff() or "staff", rid)); db().commit()
    back = request.form.get("back") or "/staff/fitting"
    return redirect(back if back.startswith("/staff") else "/staff/fitting")

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

# ---------- 손님 로그인 · 내 사이즈 저장 ----------
USER_RX = re.compile(r"[A-Za-z0-9_]{4,20}")
_FAILS = {}                                   # 로그인 실패 기록 (아이디·IP별) → 5번 틀리면 5분 잠금
PROFILE_KEYS = {"h": int, "w": int, "foot": int, "age": int, "pref": str, "g": str, "top": str, "bottom": str, "found_home": bool}

def clean_profile(p):
    out = {}
    for k, typ in PROFILE_KEYS.items():
        v = (p or {}).get(k)
        if v in (None, ""): continue
        try: out[k] = typ(v) if typ is not str else str(v)[:6]
        except (TypeError, ValueError): pass
    allowed = {"pref": ("tight", "normal", "loose"), "g": ("F", "M"), "top": SIZE_ORDER + ["XXL"], "bottom": SIZE_ORDER + ["XXL"]}
    for k, ok in allowed.items():
        if k in out and out[k] not in ok: out.pop(k)
    for k, (lo, hi) in {"h": (100, 230), "w": (20, 200), "foot": (150, 350), "age": (5, 110)}.items():
        if k in out and not lo <= out[k] <= hi: out.pop(k)
    return out

def _safe_next(n):
    n = n or ""
    return n if n.startswith("/") and not n.startswith("//") else "/go?at=ENTRANCE"

def _locked(key):
    t = [x for x in _FAILS.get(key, []) if time.time() - x < 300]
    _FAILS[key] = t
    return len(t) >= 5

@app.route("/login", methods=["GET", "POST"])
def login():
    nxt, err = _safe_next(request.values.get("next")), ""
    if request.method == "POST":
        name, pw = (request.form.get("username") or "").strip(), request.form.get("password") or ""
        key = f"{name.lower()}|{request.remote_addr}"
        if _locked(key): err = "여러 번 틀려서 5분 동안 잠겼어요"
        else:
            u = one("SELECT * FROM users WHERE username=?", (name,))
            if u and check_password_hash(u["pw"], pw):
                session.clear(); session.permanent = True; session["uid"] = u["id"]
                _FAILS.pop(key, None)
                return redirect(nxt)
            _FAILS.setdefault(key, []).append(time.time())
            err = "아이디 또는 비밀번호가 맞지 않아요"
    return render_template("login.html", mode="login", nxt=nxt, err=err, at=request.args.get("at", "ENTRANCE"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    nxt, err = _safe_next(request.values.get("next")), ""
    if request.method == "POST":
        f = request.form
        name, pw = (f.get("username") or "").strip(), f.get("password") or ""
        nick = " ".join((f.get("nickname") or "").split())
        if not 1 <= len(nick) <= 12: err = "닉네임은 1~12자로 적어 주세요"
        elif not USER_RX.fullmatch(name): err = "아이디는 영어 · 숫자 · _ 로 4~20자예요"
        elif len(pw) < 8: err = "비밀번호는 8자 이상으로 해 주세요"
        elif pw != f.get("password2"): err = "비밀번호가 서로 달라요"
        elif one("SELECT 1 x FROM users WHERE username=?", (name,)): err = "이미 있는 아이디예요"
        else:
            try: prof = clean_profile(json.loads(f.get("profile") or "null"))   # 이 휴대폰에 저장해 둔 MY 정보를 그대로 가져감
            except ValueError: prof = {}
            uid = db().execute("INSERT INTO users (username, nickname, pw, created, profile) VALUES (?,?,?,?,?)",
                               (name, nick, generate_password_hash(pw), ts(), json.dumps(prof, ensure_ascii=False))).lastrowid
            db().commit()
            session.clear(); session.permanent = True; session["uid"] = uid
            return redirect(nxt)
    return render_template("login.html", mode="signup", nxt=nxt, err=err, at=request.args.get("at", "ENTRANCE"))

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(_safe_next(request.form.get("next")))

@app.route("/api/me", methods=["GET", "POST"])
def api_me():
    """로그인한 손님의 MY 정보 불러오기 / 저장 (키 · 몸무게 · 내 사이즈 · '찾았어요 → 처음 화면' 설정)"""
    uid = session.get("uid")
    if not uid: return jsonify(ok=False, login=False)
    if request.method == "POST":
        prof = clean_profile((request.get_json(force=True) or {}).get("profile"))
        db().execute("UPDATE users SET profile=? WHERE id=?", (json.dumps(prof, ensure_ascii=False), uid)); db().commit()
        return jsonify(ok=True, login=True, profile=prof)
    u = one("SELECT username, nickname, profile FROM users WHERE id=?", (uid,))
    if not u: session.clear(); return jsonify(ok=False, login=False)
    return jsonify(ok=True, login=True, user=u["nickname"] or u["username"], profile=json.loads(u["profile"] or "null"))

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
    loc = rows("""SELECT r.sku, r.fixture_id, COUNT(DISTINCT COALESCE(r.device,'r'||r.id)) n, MIN(r.created_at) first, MAX(r.staff) staff,
                         MAX(r.created_at) last, i.name, i.color, i.image, f.name fixture_name, f.zone,
                         (SELECT p.active FROM placements p WHERE p.sku=r.sku AND p.fixture_id=r.fixture_id
                          ORDER BY p.updated_at DESC LIMIT 1) active,
                         (SELECT p.level FROM placements p WHERE p.sku=r.sku AND p.fixture_id=r.fixture_id
                          ORDER BY p.updated_at DESC LIMIT 1) level
                  FROM reports r LEFT JOIN items i ON i.sku=r.sku LEFT JOIN fixtures f ON f.id=r.fixture_id
                  WHERE r.kind='none' AND r.done=0
                  GROUP BY r.sku, r.fixture_id ORDER BY r.fixture_id, last DESC""")
    groups, claims = {}, {}
    for x in loc:
        x["since"] = mins_since(x["first"])
        k = x["fixture_id"] or "위치 없음"
        groups.setdefault(k, []).append(x)
        if x["staff"] and k not in claims: claims[k] = x["staff"]     # '제가 갈게요' 누른 직원
    # ③ 최근 처리 기록
    history = rows("""SELECT r.*, i.name FROM reports r LEFT JOIN items i ON i.sku=r.sku
                      WHERE r.done=1 AND r.resolution IS NOT NULL ORDER BY r.resolved_at DESC LIMIT 8""")
    start = request.args.get("from") or "COUNTER"
    if not one("SELECT 1 x FROM fixtures WHERE id=?", (start,)): start = "COUNTER"
    fmap, order, meters = fix_map(start, groups)
    groups = {k: groups[k] for k in order + [k for k in groups if k not in order]}   # 도는 순서대로
    return render_template("reports.html", waiting=waiting, groups=groups, history=history, claims=claims,
                           map=fmap, route=order, meters=meters, start=start, show_route=bool(request.args.get("from")),
                           rets=open_returns(), large=is_large(), CROWD_N=CROWD_N,
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

def _week(since, until):
    """기간 [since, until) 의 핵심 지표"""
    w = (since, until)
    def n(sql): return one(sql, w)["n"]
    def avg(pairs):
        v = [(datetime.datetime.fromisoformat(b) - datetime.datetime.fromisoformat(a)).total_seconds() / 60
             for a, b in pairs if a and b]
        return round(sum(v) / len(v), 1) if v else None
    found = n("SELECT COUNT(*) n FROM reports WHERE kind='found' AND created_at>=? AND created_at<?")
    nones = n("SELECT COUNT(*) n FROM reports WHERE kind='none' AND created_at>=? AND created_at<?")
    ev = {r["kind"]: r["n"] for r in rows("SELECT kind, COUNT(*) n FROM events WHERE ts>=? AND ts<? GROUP BY kind", w)}
    return {
        "found": found, "nones": nones,
        "found_rate": round(found * 100 / (found + nones)) if (found + nones) else None,
        "calls": n("SELECT COUNT(*) n FROM reports WHERE wait_at IS NOT NULL AND wait_at>=? AND wait_at<?"),
        "missed": n("SELECT COUNT(*) n FROM reports WHERE wait_state='expired' AND wait_at>=? AND wait_at<?"),
        "serve_min": avg([(r["wait_at"], r["served_at"]) for r in rows(
            "SELECT wait_at, served_at FROM reports WHERE served_at IS NOT NULL AND wait_at>=? AND wait_at<?", w)]),
        "fix_min": avg([(r["created_at"], r["resolved_at"]) for r in rows(
            """SELECT created_at, resolved_at FROM reports WHERE kind='none' AND done=1
               AND resolution IN ('재등록','위치 이동','재고 없음','오신고') AND created_at>=? AND created_at<?""", w)]),
        "search": ev.get("search", 0), "photo": ev.get("photo", 0), "tag": ev.get("tag", 0),
        "view": ev.get("view", 0) + ev.get("tag", 0), "kiosk": ev.get("kiosk", 0), "like": ev.get("like", 0),
    }

def manager_summary(days=7):
    t = now()
    since = (t - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    prev = (t - datetime.timedelta(days=days * 2)).isoformat(timespec="seconds")
    cur, last = _week(since, t.isoformat(timespec="seconds")), _week(prev, since)
    top_fx = rows("""SELECT r.fixture_id, f.name, f.zone, COUNT(*) n FROM reports r LEFT JOIN fixtures f ON f.id=r.fixture_id
                     WHERE r.kind='none' AND r.created_at>=? AND r.fixture_id IS NOT NULL
                     GROUP BY r.fixture_id ORDER BY n DESC LIMIT 3""", (since,))
    top_items = rows("""SELECT r.sku, i.name, i.color, i.image, COUNT(*) n FROM reports r JOIN items i ON i.sku=r.sku
                        WHERE r.kind='none' AND r.created_at>=? GROUP BY r.sku ORDER BY n DESC LIMIT 3""", (since,))
    top_liked = rows("""SELECT l.sku, i.name, i.color, i.image, COUNT(*) n,
                               (SELECT COALESCE(SUM(qty),0) FROM stock WHERE sku=l.sku) floor,
                               (SELECT COALESCE(SUM(wh),0) FROM stock WHERE sku=l.sku) wh
                        FROM likes l JOIN items i ON i.sku=l.sku GROUP BY l.sku ORDER BY n DESC, floor ASC LIMIT 5""")
    top_tried = rows("""SELECT fr.sku, i.name, i.color, i.image, COUNT(*) n FROM fitting_returns fr JOIN items i ON i.sku=fr.sku
                        WHERE fr.returned_at>=? GROUP BY fr.sku ORDER BY n DESC LIMIT 5""", (since,))   # 입어 보기만 하고 안 산 옷
    heat = {r["fixture_id"]: r["n"] for r in rows("""SELECT fixture_id, COUNT(*) n FROM reports
                 WHERE kind='none' AND created_at>=? AND fixture_id IS NOT NULL GROUP BY fixture_id""", (since,))}
    zone_n = Counter()
    for f in rows("SELECT id, zone FROM fixtures"):
        if heat.get(f["id"]): zone_n[f["zone"]] += heat[f["id"]]
    open_fix = one("SELECT COUNT(DISTINCT fixture_id) n FROM reports WHERE kind='none' AND done=0 AND fixture_id IS NOT NULL")["n"]
    waiting = one("SELECT COUNT(*) n FROM reports WHERE wait_state IN ('waiting','going')")["n"]
    # 이번 주 할 일 (중요한 것부터 3개)
    acts = []
    if waiting:
        acts.append({"tone": "r", "icon": "bell", "t": f"지금 기다리는 손님 {waiting}명", "d": "신고함에서 '가는 중'을 눌러 주세요", "href": "/staff/reports#wait", "btn": "신고함"})
    if open_fix:
        acts.append({"tone": "a", "icon": "run", "t": f"위치 고칠 선반 {open_fix}곳", "d": "한 번에 도는 길로 돌면서 고쳐요", "href": "/staff/reports#fix", "btn": "동선 보기"})
    if top_fx:
        f0 = top_fx[0]
        acts.append({"tone": "a", "icon": "pin", "t": f"{f0['fixture_id']} 진열·라벨 점검",
                     "d": f"이번 주 '없어요' {f0['n']}건 · 매장에서 가장 많아요", "href": "#heat", "btn": "지도"})
    low = [x for x in top_liked if x["floor"] + x["wh"] <= 3]
    if low:
        acts.append({"tone": "b", "icon": "box", "t": f"{low[0]['name']} 보충",
                     "d": f"찜 {low[0]['n']}회인데 재고 {low[0]['floor']}+창고 {low[0]['wh']}벌", "href": "#rank", "btn": "순위"})
    if cur["missed"]:
        acts.append({"tone": "r", "icon": "alert", "t": f"놓친 호출 {cur['missed']}건",
                     "d": "바쁜 시간에 근무 인원이나 바쁨 모드를 확인해요", "href": "/staff/settings", "btn": "설정"})
    if cur["serve_min"] and cur["serve_min"] > 5:
        acts.append({"tone": "a", "icon": "clock", "t": f"호출 응답 평균 {cur['serve_min']}분",
                     "d": "5분 안쪽이 목표예요", "href": "/staff/reports", "btn": "신고함"})
    fr = cur["found_rate"]
    grade = (None if fr is None else ("ok", "좋아요", "손님 대부분이 직원 없이 옷을 찾아요") if fr >= 70 else
             ("a", "보통이에요", "아직 열 명 중 서너 명은 못 찾아요 → 자주 못 찾는 자리부터") if fr >= 50 else
             ("r", "점검이 필요해요", "손님 절반 이상이 못 찾아요 → 위치 다시 찍기부터"))
    def delta(k, good_up):
        a_, b_ = cur.get(k), last.get(k)
        if a_ is None or b_ is None or b_ == 0 and a_ == 0: return None
        d = round(a_ - b_, 1)
        if d == 0: return {"txt": "지난주와 같음", "tone": "n"}
        better = (d > 0) == good_up
        unit = "%p" if k == "found_rate" else ("분" if k.endswith("_min") else "")
        return {"txt": f"지난주보다 {'▲' if d > 0 else '▼'} {abs(d):g}{unit}", "tone": "ok" if better else "r"}
    deltas = {k: delta(k, up) for k, up in [("found_rate", True), ("serve_min", False), ("fix_min", False),
                                            ("missed", False), ("calls", False), ("nones", False)]}
    usage = dict(cur, calls=cur["calls"])
    return {"cur": cur, "last": last, "deltas": deltas, "grade": grade, "acts": acts[:3], "open_fix": open_fix, "waiting": waiting,
            "heat": heat, "heat_max": max(heat.values(), default=0), "zone_n": zone_n.most_common(),
            "usage": usage, "top_liked": top_liked, "top_tried": top_tried, "top_fx": top_fx, "top_items": top_items,
            "serve_min": cur["serve_min"], "fix_min": cur["fix_min"], "missed": cur["missed"], "found": cur["found"]}

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
    db().execute("DELETE FROM fitting_returns WHERE demo=1")
    for sku in set(skus + [DEMO_SKU]):
        if not one("SELECT 1 x FROM placements WHERE sku=? AND active=1", (sku,)):
            last = one("SELECT id FROM placements WHERE sku=? ORDER BY id DESC LIMIT 1", (sku,))
            if last: db().execute("UPDATE placements SET active=1 WHERE id=?", (last["id"],))
    db().commit()

def demo_history():
    """지난 2주 기록 채우기: 점장 요약(지난주와 비교) · 지도 히트맵이 비어 보이지 않게 (device='demo')
    지난주는 서비스 도입 첫 주라 못 찾는 손님이 많고, 이번 주는 나아진 모습"""
    import random
    rnd, t0 = random.Random(7), now()
    skus = [r["sku"] for r in rows("SELECT sku FROM placements WHERE active=1")]
    WEEKS = [  # (며칠 전 범위, '없어요' 배수, 혼자 찾음, 호출 수, 놓친 호출, 응답 분, 수정 분, 사용 배수)
        ((0.2, 6.8), 1.0, 70, 13, 1, (1.5, 7), (4, 45), 1.0),
        ((7.2, 13.8), 1.5, 36, 21, 3, (3, 11), (15, 90), 0.6)]
    for (d0, d1), mul, n_found, n_call, n_miss, (s0, s1), (f0, f1), use in WEEKS:
        def back(): return t0 - datetime.timedelta(days=rnd.uniform(d0, d1))
        for fx, n in DEMO_HOT:
            items = [r["sku"] for r in rows("SELECT sku FROM placements WHERE fixture_id=? AND active=1", (fx,))] or [None]
            for _ in range(round(n * mul)):
                c = back(); r_ = c + datetime.timedelta(minutes=rnd.randint(f0, f1))
                db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,done,device,resolution,resolved_at)
                                VALUES (?,?,'none',?,1,'demo',?,?)""", (rnd.choice(items), fx, c.isoformat(timespec="seconds"),
                             rnd.choice(["재등록", "재등록", "위치 이동", "오신고"]), r_.isoformat(timespec="seconds")))
        for _ in range(n_found):
            db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at,done,device) VALUES (?,?,'found',?,1,'demo')",
                         (rnd.choice(skus), None, back().isoformat(timespec="seconds")))
        for i in range(n_call):
            w = back(); sv = w + datetime.timedelta(minutes=rnd.uniform(s0, s1)); miss = i < n_miss
            db().execute("""INSERT INTO reports (sku,fixture_id,kind,created_at,done,device,wait_state,wait_at,served_at,resolution,resolved_at)
                            VALUES (?,?,?,?,1,'demo',?,?,?,?,?)""",
                         (rnd.choice(skus), "ENTRANCE", "size" if i % 2 else "call", w.isoformat(timespec="seconds"),
                          "expired" if miss else "served", w.isoformat(timespec="seconds"),
                          None if miss else sv.isoformat(timespec="seconds"), "전달 완료", sv.isoformat(timespec="seconds")))
        tried = [r["sku"] for r in rows("SELECT sku FROM items WHERE category IN ('상의','하의','아우터') ORDER BY sku LIMIT 40")]
        for k in range(round(30 * use)):                      # 피팅룸 반납 (입어 보기만 하고 안 산 옷) — 몇 벌에 몰리게
            sku = tried[min(int(rnd.expovariate(0.25)), len(tried) - 1)] if tried else None
            r0 = back()
            if sku: db().execute("""INSERT INTO fitting_returns (sku,fixture_id,level,returned_at,returned_by,rehung_at,rehung_by,demo)
                                   SELECT ?, fixture_id, level, ?, '시연', ?, '시연', 1 FROM placements WHERE sku=? AND active=1 LIMIT 1""",
                                 (sku, r0.isoformat(timespec="seconds"), (r0 + datetime.timedelta(minutes=rnd.randint(5, 40))).isoformat(timespec="seconds"), sku))
        for kind, n in [("search", 64), ("photo", 19), ("tag", 27), ("view", 118), ("kiosk", 41), ("call", 13)]:
            for _ in range(round(n * use)):
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
    for k, ofx in enumerate(["A-H1", "B-H1"]):            # 피팅룸에서 반납받은 옷 2벌 → '제자리로 돌려놓을 옷'
        o = one("""SELECT p.sku, p.level FROM placements p JOIN items i ON i.sku=p.sku
                   WHERE p.fixture_id=? AND p.active=1 AND COALESCE(i.is_demo,0)=0 ORDER BY p.sku LIMIT 1""", (ofx,))
        if o: db().execute("""INSERT INTO fitting_returns (sku,fixture_id,level,returned_at,returned_by,demo)
                              VALUES (?,?,?,?,'김준구',1)""", (o["sku"], ofx, o["level"], (now() - datetime.timedelta(minutes=4 + k * 7)).isoformat(timespec="seconds")))
    db().commit()
    last = one("SELECT MAX(id) n FROM reports")["n"]
    if last: notify_report(last)

@app.route("/demo", methods=["GET", "POST"])
def demo():
    act, msg = request.form.get("act"), None
    if act == "clear":   demo_clear(); msg = "시연 기록을 지웠어요"
    elif act == "hist":  demo_clear(); demo_history(); msg = "지난 2주 기록을 채웠어요 — 점장 요약을 열어 보세요"
    elif act == "live":  demo_live(); msg = "손님 신고 5건(선반 4곳) · 창고 사이즈 요청 1건 · 피팅룸 반납 2벌을 만들었어요 — 신고함을 열어 보세요"
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
        me = cur_staff() or None
        if act == "going":
            db().execute("UPDATE reports SET wait_state='going', staff=? WHERE id=?", (me, rid))
        elif act in ("served", "nostock"):
            db().execute("UPDATE reports SET wait_state=?, served_at=?, staff=COALESCE(staff, ?) WHERE id=?", (act, ts(), me, rid))
            if r["kind"] != "none":                       # 호출·사이즈 요청은 여기서 끝
                db().execute("UPDATE reports SET done=1, resolution=?, resolved_at=?, resolved_by=? WHERE id=?",
                             ("전달 완료" if act == "served" else "재고 없음", ts(), me, rid))
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
    if not sku or not one("SELECT 1 x FROM items WHERE sku=?", (sku,)): return redirect(url_for("staff_reports"))
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
    close_loc_reports(sku, fx, res, cur_staff())
    db().commit()
    return redirect(url_for("staff_reports"))

@app.route("/staff/reports/claim", methods=["POST"])
def staff_claim():
    """위치 고칠 것: '제가 갈게요' → 그 선반의 열린 신고에 직원 이름을 붙임 (다른 직원 화면에 'OO 처리 중')"""
    fx = request.form.get("fixture") or None
    db().execute("UPDATE reports SET staff=? WHERE kind='none' AND done=0 AND fixture_id IS ?", (cur_staff() or "직원", fx))
    db().commit()
    return redirect(url_for("staff_reports") + "#fix")

# ---------- ⑪ 매장 설정 / ④ 바쁨 모드 ----------
STORE_TYPES = {"대형": "손님이 많은 대형 매장",
               "중형": "일반 매장", "소형": "직원이 바로 보이는 작은 매장"}

@app.route("/staff/settings", methods=["GET", "POST"])
def staff_settings():
    if request.method == "POST":
        f = request.form
        st = f.get("store_type") if f.get("store_type") in STORE_TYPES else "대형"
        set_setting("store_type", st)
        set_setting("staff_count", max(1, int(f.get("staff_count") or 1)))
        set_setting("kiosk", "1" if f.get("kiosk") else "0")
        set_setting("busy", f.get("busy") if f.get("busy") in ("auto", "on", "off") else "auto")
        if "staff_names" in f:
            names = [n.strip()[:12] for n in re.split(r"[,，\n]", f.get("staff_names", "")) if n.strip()]
            set_setting("staff_names", ",".join(dict.fromkeys(names)) or DEFAULT_STAFF)
        db().commit()
        return redirect(url_for("staff_settings", saved=1))
    return render_template("settings.html", s={k: setting(k) for k in ("store_type", "staff_count", "kiosk", "busy")}, CROWD_N=CROWD_N,
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
    """어르신용: 대분류 → 종류(사진) → 결과(+선택: 색·핏·무늬로 더 좁히기), 또는 이름으로 찾기(화면 키보드 · 말). AI 사진검색은 없음."""
    if setting("kiosk", "1") != "1":                    # ⑪ 이 매장은 키오스크를 쓰지 않음
        return render_template("kiosk_off.html")
    step = request.args.get("step", "cat")
    cat = request.args.get("cat", "")
    sub = request.args.get("sub", "")
    color = request.args.get("color", "")
    fit = request.args.get("fit", "")
    pattern = request.args.get("pattern", "")
    pz = request.args.get("pz", "")                     # 신상 · 세일 (입구 P구역 매대)
    q = request.args.get("q", "").strip()[:40]          # 이름으로 찾기 (화면 키보드 · 말로 찾기 · 인기 검색어)
    items, tiles, colors, kf, popular = [], [], [], {}, []
    if step == "search":
        pop, rise, _ = search_trends(None, n=8)
        popular = list(dict.fromkeys(pop + rise))[:12]
    elif step == "result" and q:
        base, parsed, _ = smart_search(rows("SELECT * FROM items"), q)
        exact = [it for it in base if S.is_exact(it, parsed)]
        base = exact if exact else base[:30]                # 딱 맞는 옷이 있으면 그것만 (키오스크는 짧게)
        sel = {"color": color, "fit": fit, "pattern": pattern}
        items = decorate(apply_filters(base, sel))
        fc = facet_counts(base, sel)
        kf = {k: fc.get(k, []) for k in ("color", "fit", "pattern")}
        log_event("search", src=q)
        log_event("kiosk", src=f"q/{q}")
    elif step == "result" and pz:
        items = decorate(rows("""SELECT i.* FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1
                                 WHERE p.fixture_id IN ('P-T1','P-T2') ORDER BY p.fixture_id, i.price DESC"""))
        log_event("kiosk", src="P/신상·세일")
    elif step == "sub":
        tiles = subcat_tiles().get(cat, [])
    elif step == "color":
        pool = apply_filters(rows("SELECT * FROM items"), {"cat": cat, "sub": sub})
        c = Counter(i["color"] for i in pool)
        colors = [(name, COLORS[name], c[name]) for name in COLORS if c[name]]
    elif step == "result":
        sel = {"cat": cat, "sub": sub, "color": color, "fit": fit, "pattern": pattern}
        base = rows("SELECT * FROM items")
        items = decorate(apply_filters(base, sel))
        fc = facet_counts(base, sel)            # 색·핏·무늬: 지금 조건 안에 실제로 있는 값만 버튼으로 (색 단계는 결과 화면으로 합침)
        kf = {k: fc.get(k, []) for k in ("color", "fit", "pattern")}
        log_event("kiosk", src=f"{cat}/{sub}/{color}")
    catinfo, mm, czone = {}, None, cat_zones()
    if step == "cat":                                    # 첫 화면 타일: 대분류별 상품 수 + 대표 사진
        for c, ts_ in subcat_tiles().items():
            if ts_: catinfo[c] = {"n": sum(t["n"] for t in ts_), "rep": ts_[0]["rep"]}
        p_rep = one("""SELECT i.* FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1
                       WHERE p.fixture_id IN ('P-T1','P-T2') ORDER BY (i.image LIKE 'photos/%') DESC, p.fixture_id LIMIT 1""")
        p_n = one("""SELECT COUNT(DISTINCT p.sku) n FROM placements p WHERE p.active=1 AND p.fixture_id IN ('P-T1','P-T2')""")["n"]
        if p_n: catinfo["신상 · 세일"] = {"n": p_n, "rep": p_rep, "pz": True}
        mm = mini_map("ENTRANCE")
    return render_template("kiosk.html", step=step, cat=cat, sub=sub, color=color, catinfo=catinfo,
                           fit=fit, pattern=pattern, kf=kf, pz=pz, mm=mm, czone=czone, q=q, popular=popular, colormap=COLORS,
                           splace=sub_places() if step == "sub" else {},
                           cats=list(CATS), tiles=tiles, kcolors=colors, items=items)

@app.route("/kiosk/item/<sku>")
def kiosk_item(sku):
    row = one("SELECT * FROM items WHERE sku=?", (sku,))
    if not row: return redirect(url_for("kiosk"))           # 직원이 삭제한 옷
    it = decorate([row])[0]
    it["sizes"] = sort_sizes(it["sizes"])
    fx = it["place"]["fixture_id"] if it["place"] else None
    link = f"{public_base()}/item/{sku}?at=ENTRANCE&src=kiosk"   # 휴대폰으로 받기: 찍으면 이 옷 위치 화면 → 지도 사진 저장 · 카톡
    return render_template("kiosk_item.html", it=it, map=map_data("ENTRANCE", fx), flag=loc_flag(it),
                           dirtext=direction_text(fx) if fx else "", walk=walk("ENTRANCE", fx),
                           phone_qr=qr_data_uri(link), phone_link=link, fitret=fitting_open(sku))

KIOSK_PLACES = {"FIT": ("피팅룸", "door", "옷을 입어 볼 수 있어요"), "COUNTER": ("계산대", "card", "계산 · 교환 · 환불"),
                "P-T1": ("신상품 매대", "sparkle", "이번 주 새로 들어온 옷"), "P-T2": ("할인 매대", "tag", "할인하는 옷")}

@app.route("/kiosk/place/<fx>")
def kiosk_place(fx):
    """키오스크 '매장 한눈에 보기'에서 피팅룸 · 계산대 · 매대를 누르면: 입구에서 가는 길"""
    if fx not in KIOSK_PLACES or not one("SELECT id FROM fixtures WHERE id=?", (fx,)):
        return redirect("/kiosk")
    name, ic, desc = KIOSK_PLACES[fx]
    log_event("kiosk", src=f"place/{fx}")
    return render_template("kiosk_place.html", fx=fx, name=name, ic=ic, desc=desc, map=map_data("ENTRANCE", fx),
                           dirtext=direction_text(fx), walk=walk("ENTRANCE", fx))

def cat_zones():
    """대분류마다 옷이 가장 많이 걸린 구역 (키오스크 타일 위 'A구역' 표시)"""
    out = {}
    for r in rows("""SELECT i.category, f.zone, COUNT(*) n FROM items i JOIN placements p ON p.sku=i.sku AND p.active=1
                     JOIN fixtures f ON f.id=p.fixture_id WHERE f.zone IS NOT NULL AND f.zone!='P'
                     GROUP BY i.category, f.zone ORDER BY n DESC"""):
        out.setdefault(r["category"], r["zone"])
    return out

@app.route("/kiosk/print/<sku>")
def kiosk_print(sku):
    """③ 감열식 영수증 프린터(80mm)용 종이 지도. 키오스크에서 눌러 바로 출력."""
    it = decorate([one("SELECT * FROM items WHERE sku=?", (sku,))])[0]
    it["sizes"] = sort_sizes(it["sizes"])
    fx = it["place"]["fixture_id"] if it["place"] else None
    log_event("print", sku)
    # 종이 지도에 '이 옷' QR: 행거 앞에서 찍으면 그 옷 화면이 열려 '찾는 게 없나요?'(신고·재고·직원)를 바로 쓸 수 있다
    link = f"{public_base()}/item/{sku}?at={fx or 'ENTRANCE'}&src=paper"
    return render_template("kiosk_print.html", it=it, map=map_data("ENTRANCE", fx), dirtext=direction_text(fx) if fx else "",
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
