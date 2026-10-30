# -*- coding: utf-8 -*-
"""선반 QR과 옷 태그 QR을 만들고, 바로 인쇄할 수 있는 HTML도 함께 만든다.

실행
    python make_qr.py                       # http://localhost:5001 기준
    python make_qr.py http://192.168.0.12:5001   # 폰으로 찍으려면 노트북 IP를 적는다

    (노트북 IP 확인:  ipconfig getifaddr en0 )

결과
    qr/shelf_A-H1.png ...   선반에 붙이는 QR  → 찍으면 우리 서비스가 열린다
    qr/item_UQ001.png ...   옷 태그 QR        → 직원이 등록할 때 찍는다
    qr/print_shelves.html   선반 QR 인쇄용 (브라우저에서 열고 ⌘P)
    qr/print_items.html     옷 태그 인쇄용

실제 매장에서는 옷 태그 QR 대신 옷에 이미 붙어 있는 바코드를 읽으면 된다.
"""
import base64, sqlite3, sys
from pathlib import Path
import qrcode

BASE = Path(__file__).parent
OUT = BASE / "qr"; OUT.mkdir(exist_ok=True)
host = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5001").rstrip("/")

def save(data, path, box=10):
    img = qrcode.make(data, box_size=box, border=2)
    img.save(path)
    return base64.b64encode(path.read_bytes()).decode()

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{title}</title><style>
@page{{size:A4;margin:12mm}}
body{{font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;margin:0}}
h1{{font-size:15pt;margin:0 0 8px}} p.sub{{color:#666;font-size:10pt;margin:0 0 14px}}
.grid{{display:grid;grid-template-columns:repeat({cols},1fr);gap:{gap}mm}}
.card{{border:1.5px dashed #bbb;border-radius:8px;padding:{pad}mm;text-align:center;
       page-break-inside:avoid}}
.card img{{width:100%;max-width:{qr}mm}}
.id{{font-weight:800;font-size:{idsz}pt;margin-top:4px}}
.nm{{font-size:{nmsz}pt;color:#444}}
.hint{{font-size:9pt;color:#1677E8;margin-top:3px}}
</style></head><body><h1>{title}</h1><p class="sub">{sub}</p>
<div class="grid">{cards}</div></body></html>"""

db = sqlite3.connect(BASE / "store.db"); db.row_factory = sqlite3.Row

# ---------- 선반 QR ----------
cards = []
for r in db.execute("SELECT * FROM fixtures WHERE kind NOT IN ('계산대','피팅룸','창고','기둥')"):
    b64 = save(f"{host}/go?at={r['id']}", OUT / f"shelf_{r['id']}.png")
    hint = "키오스크 자리" if r["id"] == "ENTRANCE" else "찍으면 옷 위치를 찾을 수 있어요"
    cards.append(f'<div class="card"><img src="data:image/png;base64,{b64}">'
                 f'<div class="id">{r["id"]}</div><div class="nm">{r["name"]}</div>'
                 f'<div class="hint">{hint}</div></div>')
(OUT / "print_shelves.html").write_text(PAGE.format(
    title="where:wear 선반 QR", sub=f"각 집기에 붙이세요 · 서버 주소: {host}",
    cols=2, gap=8, pad=6, qr=70, idsz=16, nmsz=11, cards="".join(cards)), encoding="utf-8")

# ---------- 옷 태그 QR ----------
cards = []
for r in db.execute("SELECT sku, name FROM items ORDER BY sku"):
    b64 = save(f"{host}/item/{r['sku']}?src=tag", OUT / f"item_{r['sku']}.png", box=6)   # 손님: 찍으면 재고 확인 / 직원: 등록
    cards.append(f'<div class="card"><img src="data:image/png;base64,{b64}">'
                 f'<div class="id">{r["sku"]}</div><div class="nm">{r["name"]}</div></div>')
(OUT / "print_items.html").write_text(PAGE.format(
    title="where:wear 옷 태그 QR", sub="옷 태그에 붙이세요 · 손님이 찍으면 사이즈별 재고, 직원 화면에서 찍으면 위치 등록",
    cols=4, gap=5, pad=3, qr=38, idsz=11, nmsz=8, cards="".join(cards)), encoding="utf-8")

print(f"QR 생성 완료 → {OUT}")
print("  인쇄: qr/print_shelves.html 를 브라우저로 열고 ⌘P")
print(f"  서버 주소: {host}   (폰으로 찍으려면 노트북 IP여야 합니다)")
