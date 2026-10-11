# -*- coding: utf-8 -*-
"""[선택 기능] CLIP으로 의미 유사도까지 반영하기.

설치가 안 돼 있으면 search.py가 알아서 건너뛴다. 정확도를 더 올리고 싶을 때만 켜면 된다.

  pip install torch transformers pillow --break-system-packages
  python clip_search.py build      # 상품 이미지 임베딩 미리 계산 (1회, 1~2분)

모델 선택
  - 한국어 그대로 검색: Bingsu/clip-vit-base-patch32-ko  (MIT)
  - 영어로 번역해서 검색: patrickjohncyh/fashion-clip    (MIT, 패션 특화·정확도 ↑)
"""
import json, os
from pathlib import Path

BASE = Path(__file__).parent
MODEL = os.environ.get("WW_CLIP_MODEL", "Bingsu/clip-vit-base-patch32-ko")
EMB = BASE / "embeddings.json"
_cache = {}

def _load():
    if "model" not in _cache:
        from transformers import AutoModel, AutoProcessor
        _cache["model"] = AutoModel.from_pretrained(MODEL)
        _cache["proc"] = AutoProcessor.from_pretrained(MODEL)
    return _cache["model"], _cache["proc"]

def build():
    """상품 이미지를 벡터로 바꿔 embeddings.json에 저장한다."""
    import sqlite3, torch
    from PIL import Image
    import cairosvg  # SVG를 PNG로 (실제 사진을 쓰면 필요 없음)
    model, proc = _load()
    db = sqlite3.connect(BASE / "store.db"); db.row_factory = sqlite3.Row
    out = {}
    for r in db.execute("SELECT sku FROM items"):
        png = cairosvg.svg2png(url=str(BASE / "static/img" / f"{r['sku']}.svg"))
        import io; im = Image.open(io.BytesIO(png)).convert("RGB")
        with torch.no_grad():
            v = model.get_image_features(**proc(images=im, return_tensors="pt"))[0]
        out[r["sku"]] = (v / v.norm()).tolist()
    EMB.write_text(json.dumps(out))
    print("임베딩 저장 완료:", len(out))

def _text_vec(q):
    import torch
    model, proc = _load()
    with torch.no_grad():
        v = model.get_text_features(**proc(text=[q], return_tensors="pt", padding=True))[0]
    return (v / v.norm()).tolist()

def rerank(query, scored):
    """속성 점수(scored)에 CLIP 유사도를 더해 순위를 다듬는다."""
    if not EMB.exists(): raise RuntimeError("임베딩 없음. python clip_search.py build 먼저")
    emb = json.loads(EMB.read_text())
    q = _text_vec(query)
    out = []
    for s, it in scored:
        v = emb.get(it["sku"])
        sim = sum(a*b for a, b in zip(q, v)) if v else 0
        out.append((s + sim * 5, it))     # 속성 점수 + CLIP 유사도(가중치 5)
    out.sort(key=lambda t: -t[0])
    return out

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build": build()
    else: print(__doc__)
