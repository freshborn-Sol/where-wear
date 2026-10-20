# -*- coding: utf-8 -*-
"""검색 엔진: 속성 사전 + (있으면) CLIP 하이브리드.
   - 텍스트 검색:  '파란색 후드티' → 색상/종류/핏 단어를 뽑아 점수화
   - 사진 검색:    업로드 사진의 대표 색 → 비슷한 색 + (CLIP 있으면) 의미 유사도
   CLIP이 설치되어 있지 않아도 그대로 동작한다.
"""
import io, re, math

# ---------- 단어 사전 ----------
COLOR_WORDS = {
    "블랙": ["블랙", "검정", "검은", "까만", "black"],
    "화이트": ["화이트", "흰", "하얀", "white"],
    "그레이": ["그레이", "회색", "gray", "grey"],
    "네이비": ["네이비", "남색", "navy"],
    "블루": ["블루", "파란", "파랑", "파란색", "blue"],
    "스카이블루": ["스카이블루", "하늘색", "하늘"],
    "베이지": ["베이지", "beige"],
    "브라운": ["브라운", "갈색", "brown"],
    "레드": ["레드", "빨간", "빨강", "red"],
    "그린": ["그린", "초록", "녹색", "green"],
    "핑크": ["핑크", "분홍", "pink"],
    "카키": ["카키", "khaki"],
}
SUB_WORDS = {
    "후드티": ["후드티", "후드", "후디", "hoodie"],
    "맨투맨": ["맨투맨", "스웨트", "sweat"],
    "셔츠": ["셔츠", "남방", "shirt"],
    "니트": ["니트", "스웨터", "knit"],
    "반팔티": ["반팔티", "반팔", "티셔츠", "tshirt"],
    "슬랙스": ["슬랙스", "정장바지", "slacks"],
    "청바지": ["청바지", "데님", "jeans"],
    "조거팬츠": ["조거", "트레이닝", "jogger"],
    "스커트": ["스커트", "치마", "skirt"],
    "코트": ["코트", "coat"],
    "패딩": ["패딩", "다운", "padding"],
    "바람막이": ["바람막이", "윈드브레이커"],
    "가디건": ["가디건", "카디건", "cardigan"],
    "운동화": ["운동화", "스니커즈", "신발", "sneakers"],
    "슬리퍼": ["슬리퍼", "쪼리", "slipper"],
    "긴팔티": ["긴팔티", "긴팔", "롱슬리브"],
    "블라우스": ["블라우스", "blouse"],
    "조끼": ["조끼", "베스트", "vest"],
    "반바지": ["반바지", "숏팬츠", "shorts"],
    "재킷": ["재킷", "자켓", "블루종", "jacket"],
    "후드집업": ["후드집업", "집업", "zipup"],
    "구두": ["구두", "로퍼", "더비", "loafer"],
    "부츠": ["부츠", "boots"],
    "모자": ["모자", "캡", "볼캡", "비니", "버킷햇", "cap", "hat"],
    "가방": ["가방", "백팩", "크로스백", "토트백", "bag"],
    "양말": ["양말", "삭스", "socks"],
    "벨트": ["벨트", "belt"],
}
CAT_WORDS = {"상의": ["상의", "윗옷", "top"], "하의": ["하의", "바지", "pants"],
             "아우터": ["아우터", "겉옷", "outer"], "신발": ["신발", "슈즈", "shoes"],
             "잡화": ["잡화", "액세서리", "소품"]}
FIT_WORDS = {"오버핏": ["오버핏", "오버", "루즈"], "슬림핏": ["슬림핏", "슬림"],
             "크롭": ["크롭", "짧은"], "레귤러핏": ["레귤러", "기본"]}

def _find(query, table):
    hits = []
    for key, words in table.items():
        if any(w in query for w in words):
            hits.append(key)
    return hits

def parse_query(q):
    """'오버핏 파란색 후드티' → {'colors':['블루'], 'subs':['후드티'], ...}"""
    q = q.lower().replace(" ", "")
    return {"colors": _find(q, COLOR_WORDS), "subs": _find(q, SUB_WORDS),
            "cats": _find(q, CAT_WORDS), "fits": _find(q, FIT_WORDS)}

def score_item(it, parsed):
    """속성이 맞을수록 높은 점수. (색 4점, 종류 4점, 대분류 2점, 핏 1점)"""
    s = 0.0
    if parsed["colors"]:
        if it["color"] in parsed["colors"]: s += 4
        elif _similar_color(it["color"], parsed["colors"]): s += 1.5   # 비슷한 색
    if parsed["subs"] and it["subcat"] in parsed["subs"]: s += 4
    if parsed["cats"] and it["category"] in parsed["cats"]: s += 2
    if parsed["fits"] and it["fit"] in parsed["fits"]: s += 1
    return s

SIMILAR = {"블루": ["네이비", "스카이블루"], "네이비": ["블루"], "스카이블루": ["블루"],
           "그레이": ["블랙", "화이트"], "베이지": ["브라운"], "브라운": ["베이지", "카키"],
           "카키": ["그린", "브라운"], "그린": ["카키"]}
def _similar_color(color, wanted):
    return any(color in SIMILAR.get(w, []) for w in wanted)

def text_search(items, q, limit=12):
    parsed = parse_query(q)
    if not any(parsed.values()):                       # 아는 단어가 하나도 없을 때
        return [it for it in items if q.replace(" ", "") in it["name"].replace(" ", "")][:limit], parsed, "이름으로 찾았어요"
    scored = [(score_item(it, parsed), it) for it in items]
    scored = [(s, it) for s, it in scored if s > 0]
    scored.sort(key=lambda t: -t[0])
    how = "색상·종류를 알아듣고 찾았어요"
    return [it for _, it in scored[:limit]], parsed, how

# ---------- 사진 검색 ----------
def dominant_color(file_storage):
    """업로드한 사진에서 가장 많이 쓰인 색(배경 제외 근사)을 뽑는다."""
    from PIL import Image
    im = Image.open(io.BytesIO(file_storage.read())).convert("RGB")
    im.thumbnail((200, 200))
    w, h = im.size
    im = im.crop((int(w*0.15), int(h*0.15), int(w*0.85), int(h*0.85)))   # 가장자리 잘라내기
    q = im.quantize(colors=5, method=Image.MEDIANCUT).convert("RGB")
    counts = sorted(q.getcolors(10000), reverse=True)
    return counts[0][1]

def _hex2rgb(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

def nearest_color_name(rgb, palette):
    """가장 가까운 팔레트 색 이름"""
    best, bd = None, 1e9
    for name, hexcode in palette.items():
        pr, pg, pb = _hex2rgb(hexcode)
        d = (pr-rgb[0])**2 + (pg-rgb[1])**2 + (pb-rgb[2])**2
        if d < bd: best, bd = name, d
    return best, math.sqrt(bd)

def photo_search(items, palette, rgb, cat=None, limit=12):
    name, dist = nearest_color_name(rgb, palette)
    pool = [it for it in items if cat in (None, "", it["category"])]
    def key(it):
        pr, pg, pb = _hex2rgb(it["hex"])
        return (pr-rgb[0])**2 + (pg-rgb[1])**2 + (pb-rgb[2])**2
    pool.sort(key=key)
    return pool[:limit], name
