# -*- coding: utf-8 -*-
"""catalog.csv 로 진짜 매장처럼 상품 데이터를 채운다.  (실행: python import_catalog.py)

준비
  1) catalog.csv 를 엑셀로 열어 실제 매장에서 조사한 상품으로 채운다
     (sku / 이름 / 카테고리 / 종류 / 색상 / 핏 / 가격 / 사이즈별 재고 / 선반 / 단 / 몇 분 전 등록)
  2) 사진이 있으면 static/photos/<sku>.jpg 로 저장한다 (없으면 색상 그림이 자동 생성됨)
  3) python import_catalog.py          → DB를 새로 만든다 (신고·위치 기록 초기화)
     python import_catalog.py --new    → DB에 없는 상품만 추가 (기록 유지)

주의: 브랜드 홈페이지 사진을 그대로 쓰지 말 것. 직접 찍은 사진을 쓰거나 색상 그림을 그대로 둔다.
"""
import csv, sqlite3, datetime, sys, zlib
from pathlib import Path
from seed import COLORS, make_image
from store_map import write_map

BASE = Path(__file__).parent
DB = BASE / "store.db"
PHOTOS = BASE / "static" / "photos"

def find_photo(sku):
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if (PHOTOS / f"{sku}{ext}").exists():
            return f"photos/{sku}{ext}"
    return None

def add_row(db, r, now, warn, wh=False):
    """catalog.csv 한 줄 → items / stock / placements"""
    sku = r["sku"].strip().upper()
    color = r["color"].strip()
    hexcode = (r.get("hex") or "").strip() or COLORS.get(color, "#9aa0a6")
    if color not in COLORS:
        warn.append(f"{sku}: '{color}'는 검색 사전에 없는 색이에요 (search.py의 COLOR_WORDS에 추가하세요)")

    photo = find_photo(sku)
    if not photo:                                   # 사진도 주소도 없으면 색상 그림 생성
        make_image(sku, r["category"].strip(), hexcode, f'{color} {r["subcat"].strip()}')
        photo = f"img/{sku}.svg"

    db.execute("INSERT INTO items (sku,name,category,subcat,color,hex,fit,price,image,pattern)"
               " VALUES (?,?,?,?,?,?,?,?,?,?)",
               (sku, r["name"].strip(), r["category"].strip(), r["subcat"].strip(),
                color, hexcode, (r.get("fit") or "").strip(),
                int(r["price"] or 0), photo, (r.get("pattern") or "무지").strip() or "무지"))

    for part in (r.get("sizes") or "").split(","):
        if ":" in part:
            size, qty = part.split(":")
            db.execute("INSERT INTO stock (sku,size,qty,wh) VALUES (?,?,?,?)", (sku, size.strip(), int(qty),
                        zlib.crc32(f"{sku}{size.strip()}".encode()) % 4 if wh else 0))

    fx = (r.get("fixture") or "").strip()
    if fx:
        ts = now - datetime.timedelta(minutes=int(r.get("ago_min") or 0))
        db.execute("INSERT INTO placements (sku,fixture_id,level,updated_at,updated_by,active)"
                   " VALUES (?,?,?,?,?,1)",
                   (sku, fx, (r.get("level") or "중단").strip(),
                    ts.isoformat(timespec="seconds"), "csv"))

def add_new():
    """--new: 지금 DB(신고·위치 기록)는 그대로 두고, catalog.csv 에서 DB에 없는 상품만 추가한다"""
    rows = list(csv.DictReader(open(BASE / "catalog.csv", encoding="utf-8-sig")))
    db = sqlite3.connect(DB)
    have = {r[0] for r in db.execute("SELECT sku FROM items")}
    now, warn, n = datetime.datetime.now(), [], 0
    for r in rows:
        if r["sku"].strip().upper() in have: continue
        add_row(db, r, now, warn, wh=True); n += 1
    db.commit()
    print(f"새 상품 {n}개 추가 → {DB} (기존 {len(have)}개 · 신고 기록은 그대로)")
    for w in warn: print("  ⚠", w)

def main():
    rows = list(csv.DictReader(open(BASE / "catalog.csv", encoding="utf-8-sig")))
    if not rows:
        print("catalog.csv 가 비어 있어요."); return

    if DB.exists(): DB.unlink()
    db = sqlite3.connect(DB)
    db.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
    for col, typ in [("pattern", "TEXT"), ("ai_json", "TEXT"), ("is_demo", "INTEGER DEFAULT 0")]:
        if col not in {r[1] for r in db.execute("PRAGMA table_info(items)")}:
            db.execute(f"ALTER TABLE items ADD COLUMN {col} {typ}")
    write_map(db)                       # 매장 도면 (store_map.py)

    now = datetime.datetime.now()
    warn = []
    for r in rows:
        add_row(db, r, now, warn)
    db.commit()
    print(f"불러오기 완료: 상품 {len(rows)}개 → {DB}")
    for w in warn: print("  ⚠", w)

if __name__ == "__main__":
    add_new() if "--new" in sys.argv and DB.exists() else main()
