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
    return dict(imgsrc=imgsrc, with_args=with_args)

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
        it["sizes"] = rows("SELECT size, qty FROM stock WHERE sku=? ORDER BY size", (it["sku"],))
        out.append(it)
    return out

# ---------- 길찾기 (BFS) ----------
def path_between(start, goal):
    adj = {}
    for e in rows("SELECT * FROM edges"):
        adj.setdefault(e["a"], []).append(e["b"])
    if start not in adj or goal not in adj: return []
    q, seen = deque([[start]]), {start}
    while q:
        p = q.popleft()
        if p[-1] == goal: return p
        for nx in adj.get(p[-1], []):
            if nx not in seen:
                seen.add(nx); q.append(p + [nx])
    return []

def map_data(at, target_fixture=None):
    """도면 그리기에 필요한 값 묶음"""
    nodes = {n["id"]: n for n in rows("SELECT * FROM nodes")}
    pts = []
    if target_fixture:
        for nid in path_between(at, target_fixture):
            if nid in nodes: pts.append((nodes[nid]["x"], nodes[nid]["y"]))
    return {"fixtures": rows("SELECT * FROM fixtures"), "at": at,
            "target": target_fixture,
            "path": " ".join(f"{x},{y}" for x, y in pts)}

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
    fx = it["place"]["fixture_id"] if it["place"] else None
    return render_template("item.html", at=at, it=it, map=map_data(at, fx))

# ---------- 신고 / 직원 호출 ----------
@app.route("/api/report", methods=["POST"])
def report():
    d = request.get_json(force=True)
    sku, fx, kind = d.get("sku"), d.get("fixture"), d.get("kind", "none")
    db().execute("INSERT INTO reports (sku,fixture_id,kind,created_at) VALUES (?,?,?,?)",
                 (sku, fx, kind, now().isoformat(timespec="seconds")))
    msg = "직원에게 알렸어요"
    if kind == "none":
        n = one("SELECT COUNT(*) c FROM reports WHERE sku=? AND fixture_id=? AND kind='none' AND done=0",
                (sku, fx))["c"]
        if n >= 2:      # 같은 자리 신고가 2번 쌓이면 그 위치를 자동으로 내린다
            db().execute("UPDATE placements SET active=0 WHERE sku=? AND fixture_id=?", (sku, fx))
            msg = "신고가 쌓여서 이 위치를 목록에서 내렸어요"
    db().commit()
    return jsonify(ok=True, message=msg)

# ---------- 직원 화면 ----------
@app.route("/staff")
def staff():
    return render_template("staff.html",
                           fixtures=rows("SELECT * FROM fixtures WHERE id!='ENTRANCE'"),
                           items=rows("SELECT sku, name FROM items ORDER BY sku"))

@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json(force=True)
    sku, fx, lv = d.get("sku", "").upper(), d.get("fixture"), d.get("level", "중단")
    it = one("SELECT * FROM items WHERE sku=?", (sku,))
    if not it: return jsonify(ok=False, message=f"모르는 코드: {sku}"), 400
    if not one("SELECT 1 FROM fixtures WHERE id=?", (fx,)):
        return jsonify(ok=False, message=f"모르는 선반: {fx}"), 400
    db().execute("UPDATE placements SET active=0 WHERE sku=?", (sku,))   # 이전 위치는 내림
    db().execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                 " VALUES (?,?,?,?,?,1)", (sku, fx, lv, now().isoformat(timespec="seconds"), "staff"))
    db().execute("UPDATE reports SET done=1 WHERE sku=?", (sku,))        # 관련 신고 처리
    db().commit()
    return jsonify(ok=True, message=f"{it['name']} → {fx} {lv}")

# ---------- 직원: 실물 옷을 사진으로 등록 (전시회용) ----------
def next_demo_sku():
    n = one("SELECT COUNT(*) c FROM items WHERE sku LIKE 'EX%'")["c"]
    while one("SELECT 1 FROM items WHERE sku=?", (f"EX{n+1:03d}",)): n += 1
    return f"EX{n+1:03d}"

def staff_ai_ctx(**kw):
    return dict(fixtures=rows("SELECT * FROM fixtures WHERE id!='ENTRANCE'"),
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
                db().execute("INSERT INTO stock VALUES (?,?,?)", (sku, sz.strip().upper(), int(qty)))
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

@app.route("/staff/reports")
def staff_reports():
    rs = rows("""SELECT r.*, i.name FROM reports r LEFT JOIN items i ON i.sku=r.sku
                 ORDER BY r.done, r.created_at DESC LIMIT 50""")
    return render_template("reports.html", reports=rs)

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
    return render_template("kiosk.html", step=step, cat=cat, sub=sub, color=color,
                           fit=fit, pattern=pattern, kf=kf,
                           cats=list(CATS), tiles=tiles, kcolors=colors, items=items)

@app.route("/kiosk/item/<sku>")
def kiosk_item(sku):
    it = decorate([one("SELECT * FROM items WHERE sku=?", (sku,))])[0]
    fx = it["place"]["fixture_id"] if it["place"] else None
    return render_template("kiosk_item.html", it=it, map=map_data("ENTRANCE", fx))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))     # 맥은 5000번을 AirPlay가 쓰므로 5001
    print(f"\n  → http://localhost:{port}  (휴대폰은 http://<노트북IP>:{port}/go?at=A-H1)\n")
    app.run(host="0.0.0.0", port=port, debug=True)
