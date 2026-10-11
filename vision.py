# -*- coding: utf-8 -*-
"""사진 → Vision AI(Gemini) → 옷 특징(JSON) → 매장 DB와 비교해 비슷한 옷 순위.

  흐름
    1) analyze(사진 바이트)  : 사진을 줄여서 Gemini에 보내고, 정해진 단어 목록 안에서만
                               특징을 골라 JSON으로 받는다.  (호출 1번)
    2) rank(items, 특징)      : 우리 코드가 DB의 옷들과 특징을 비교해 점수를 매긴다.
                               (AI는 '특징 추출'만, '비교'는 코드가 한다 → 결과가 일정함)

  API 키 : 환경변수 GEMINI_API_KEY  또는  같은 폴더의 gemini_key.txt  (둘 중 하나)
  모델   : 환경변수 GEMINI_MODEL  (기본 gemini-3.1-flash-lite)
  표준 라이브러리(urllib)만 써서 추가 설치가 필요 없다. 사진 줄이기는 Pillow(이미 설치됨).
"""
import base64, hashlib, io, json, os, time, urllib.error, urllib.request
from pathlib import Path

BASE = Path(__file__).parent
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
CACHE_FILE = BASE / "ai_cache.json"        # 같은 사진을 다시 올리면 API를 안 부른다
TIMEOUT = 20

# ---------- AI가 고를 수 있는 단어 목록 (이 밖의 단어는 못 쓰게 강제) ----------
CATEGORIES = ["상의", "하의", "아우터", "신발", "기타"]
SUBCATS = {
    "상의":  ["후드티", "맨투맨", "셔츠", "니트", "반팔티", "긴팔티", "블라우스", "조끼"],
    "하의":  ["슬랙스", "청바지", "조거팬츠", "반바지", "스커트"],
    "아우터": ["코트", "패딩", "바람막이", "가디건", "재킷", "후드집업"],
    "신발":  ["운동화", "슬리퍼", "구두", "부츠"],
    "기타":  ["원피스", "모자", "가방", "기타"],
}
ALL_SUBS = [s for v in SUBCATS.values() for s in v]
COLORS = ["블랙", "화이트", "그레이", "네이비", "블루", "스카이블루",
          "베이지", "브라운", "레드", "그린", "핑크", "카키"]     # seed.COLORS 와 같은 12색
PATTERNS = ["무지", "스트라이프", "체크", "로고·그래픽", "꽃무늬", "기타"]
FITS = ["오버핏", "레귤러핏", "슬림핏", "크롭", "알수없음"]

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_clothing": {"type": "BOOLEAN"},
        "category":    {"type": "STRING", "enum": CATEGORIES},
        "subcat":      {"type": "STRING", "enum": ALL_SUBS},
        "color":       {"type": "STRING", "enum": COLORS},
        "pattern":     {"type": "STRING", "enum": PATTERNS},
        "fit":         {"type": "STRING", "enum": FITS},
        "desc":        {"type": "STRING"},
    },
    "required": ["is_clothing", "category", "subcat", "color", "pattern", "fit", "desc"],
}

PROMPT = """너는 의류 매장의 상품 분류 담당자다. 사진 속 가장 크게 보이는 옷 한 벌만 보고 특징을 고른다.
- 사람이 입고 있으면 사람은 무시하고 옷만 본다. 여러 벌이면 가장 크고 가운데 있는 것.
- color는 옷 몸판의 주된 색 하나. 조명 때문에 생긴 그림자·반사는 무시.
- 짙은 남색은 네이비, 밝은 하늘색은 스카이블루, 아이보리·크림은 화이트, 차콜은 그레이.
- 핏을 사진으로 판단하기 어려우면 알수없음.
- 옷이 아니면 is_clothing=false 로 하고 나머지는 가장 가까운 값을 아무거나 넣는다.
- desc는 한국어 20자 이내로 눈에 띄는 특징 (예: "가슴 로고가 있는 검정 후드").
반드시 지정된 JSON 형식으로만 답한다."""


class VisionError(Exception):
    """AI 호출 실패. message는 화면에 그대로 보여줄 수 있는 한국어."""


# ---------- API 키 ----------
def api_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k and (BASE / "gemini_key.txt").exists():
        k = (BASE / "gemini_key.txt").read_text(encoding="utf-8").strip()
    return k


# ---------- 사진 준비: 회전 보정 + 768px로 줄이기 (토큰·시간 절약) ----------
def prepare(image_bytes):
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(image_bytes))
    im = ImageOps.exif_transpose(im).convert("RGB")      # 폰 사진이 옆으로 눕는 문제 방지
    im.thumbnail((768, 768))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ---------- 캐시 ----------
def _cache_load():
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _cache_save(c):
    try:
        CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ---------- Gemini 호출 ----------
def _call_gemini(jpeg_bytes, key):
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(jpeg_bytes).decode()}},
            {"text": PROMPT},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "responseSchema": SCHEMA},
    }
    req = urllib.request.Request(
        ENDPOINT.format(m=MODEL), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        msg = {400: "요청 형식 오류(모델 이름·사진 확인)", 403: "API 키가 잘못됐거나 권한이 없어요",
               404: f"모델 '{MODEL}'을 찾을 수 없어요", 429: "AI 사용 한도를 잠시 넘었어요",
               }.get(e.code, f"AI 서버 오류 {e.code}")
        raise VisionError(msg) from VisionError(detail)
    except Exception as e:                                # 인터넷 끊김, 시간 초과 등
        raise VisionError("AI 서버에 연결하지 못했어요") from e

    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = next(p["text"] for p in parts if "text" in p and not p.get("thought"))
        return json.loads(text)
    except Exception as e:
        raise VisionError("AI 응답을 읽지 못했어요") from e


def analyze(image_bytes):
    """사진 → {'category','subcat','color','pattern','fit','desc','is_clothing', '_ms', '_cached'}"""
    key = api_key()
    if not key:
        raise VisionError("API 키가 없어요 (GEMINI_API_KEY)")
    jpeg = prepare(image_bytes)
    h = hashlib.sha1(jpeg).hexdigest()
    cache = _cache_load()
    if h in cache:
        return {**cache[h], "_cached": True, "_ms": 0, "_hash": h}
    t = time.time()
    attrs = _call_gemini(jpeg, key)
    attrs = normalize(attrs)
    cache[h] = attrs
    _cache_save(cache)
    return {**attrs, "_cached": False, "_ms": int((time.time() - t) * 1000), "_hash": h}


def normalize(a):
    """목록 밖의 값이 오면 안전한 기본값으로."""
    a = dict(a or {})
    a["category"] = a.get("category") if a.get("category") in CATEGORIES else "기타"
    a["subcat"] = a.get("subcat") if a.get("subcat") in ALL_SUBS else "기타"
    a["color"] = a.get("color") if a.get("color") in COLORS else "그레이"
    a["pattern"] = a.get("pattern") if a.get("pattern") in PATTERNS else "무지"
    a["fit"] = a.get("fit") if a.get("fit") in FITS else "알수없음"
    a["desc"] = (a.get("desc") or "")[:40]
    a["is_clothing"] = bool(a.get("is_clothing", True))
    return a


# ---------- 비교 · 점수 ----------
SIMILAR_COLOR = {
    "블랙": ["네이비", "그레이"], "그레이": ["블랙", "화이트"], "화이트": ["베이지", "그레이"],
    "네이비": ["블루", "블랙"], "블루": ["네이비", "스카이블루"], "스카이블루": ["블루"],
    "베이지": ["브라운", "화이트"], "브라운": ["베이지", "카키"], "카키": ["그린", "브라운"],
    "그린": ["카키"], "레드": ["핑크"], "핑크": ["레드"],
}
SIMILAR_SUB = [  # 같은 무리에 있으면 '비슷한 종류'로 부분 점수
    {"후드티", "맨투맨", "후드집업"}, {"반팔티", "긴팔티"}, {"셔츠", "블라우스"},
    {"니트", "가디건"}, {"코트", "재킷"}, {"패딩", "바람막이"},
    {"슬랙스", "청바지", "조거팬츠"}, {"운동화", "구두", "부츠"},
]
W = {"subcat": 40, "color": 25, "pattern": 15, "category": 10, "fit": 10}   # 합 100


def item_attrs(it):
    """DB 상품의 특징. 등록 때 AI로 뽑아 둔 값(ai_json)이 있으면 그걸 우선 쓴다."""
    try:
        ai = json.loads(it.get("ai_json") or "{}")
    except Exception:
        ai = {}
    return {
        "category": ai.get("category") or it.get("category"),
        "subcat":   ai.get("subcat")   or it.get("subcat"),
        "color":    ai.get("color")    or it.get("color"),
        "pattern":  ai.get("pattern")  or it.get("pattern") or "무지",
        "fit":      ai.get("fit")      or it.get("fit") or "알수없음",
    }


def score(q, a):
    """q: 사진에서 뽑은 특징, a: 상품 특징 → (0~100점, 맞은 항목 목록)"""
    s, hits = 0.0, []
    if q["subcat"] == a["subcat"]:
        s += W["subcat"]; hits.append(a["subcat"])
    elif any(q["subcat"] in g and a["subcat"] in g for g in SIMILAR_SUB):
        s += W["subcat"] * 0.45; hits.append(f"비슷한 종류({a['subcat']})")
    if q["color"] == a["color"]:
        s += W["color"]; hits.append(a["color"])
    elif a["color"] in SIMILAR_COLOR.get(q["color"], []):
        s += W["color"] * 0.45; hits.append(f"비슷한 색({a['color']})")
    if q["pattern"] == a["pattern"]:
        s += W["pattern"]; hits.append(a["pattern"])
    if q["category"] == a["category"]:
        s += W["category"]
    if "알수없음" in (q["fit"], a["fit"]):
        s += W["fit"] * 0.5
    elif q["fit"] == a["fit"]:
        s += W["fit"]; hits.append(a["fit"])
    return round(s), hits


def rank(items, q, limit=5):
    """상품 목록을 점수순으로. 동점이면 전시 실물 → 위치 등록된 것 → 최근 등록 순."""
    out = []
    for it in items:
        sc, hits = score(q, item_attrs(it))
        out.append({**it, "score": sc, "hits": hits})
    out.sort(key=lambda it: (-it["score"], -(it.get("is_demo") or 0),
                             0 if it.get("place") else 1))
    return out[:limit]


def verdict(sc):
    if sc >= 80: return ("같은 옷일 가능성이 높아요", "high")
    if sc >= 55: return ("가장 비슷한 옷이에요", "mid")
    return ("똑같은 옷은 없지만, 가장 가까운 옷이에요", "low")
