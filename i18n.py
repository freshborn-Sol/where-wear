# -*- coding: utf-8 -*-
"""where:wear 영어 화면 (손님 QR · 키오스크 · 직원 모드별로 따로 고름)

템플릿은 한국어 그대로 두고, 응답을 보내기 직전에 화면 글자만 영어로 바꾼다.
  1) 문장 통째로 (PHRASES)  2) 숫자가 들어간 문장 (PATTERNS)  3) 낱말 단위 (WORDS: 색·종류·상품명 낱말)
링크 주소·폼 값·스크립트 안의 데이터(예: '상의', '오버핏')는 건드리지 않아서 검색·필터가 그대로 동작한다.
"""
import re
import html as _h

H = re.compile(r"[가-힣]")

# ---------------------------------------------------------------- 낱말 (색 · 종류 · 핏 · 무늬 · 단 · 상품명)
WORDS = {
    # 색
    "블랙": "Black", "화이트": "White", "그레이": "Gray", "네이비": "Navy", "블루": "Blue", "스카이블루": "Sky Blue",
    "베이지": "Beige", "브라운": "Brown", "레드": "Red", "그린": "Green", "핑크": "Pink", "카키": "Khaki",
    "검정": "Black", "흰": "White",
    # 큰 종류
    "상의": "Tops", "하의": "Bottoms", "아우터": "Outerwear", "신발": "Shoes", "잡화": "Accessories", "신발·잡화": "Shoes & Accessories",
    # 세부 종류
    "후드티": "Hoodie", "맨투맨": "Sweatshirt", "셔츠": "Shirt", "니트": "Knit", "반팔티": "T-shirt", "슬랙스": "Slacks",
    "청바지": "Jeans", "조거팬츠": "Joggers", "스커트": "Skirt", "코트": "Coat", "패딩": "Puffer", "바람막이": "Windbreaker",
    "가디건": "Cardigan", "운동화": "Sneakers", "슬리퍼": "Slippers", "긴팔티": "Long-sleeve Tee", "블라우스": "Blouse",
    "조끼": "Vest", "반바지": "Shorts", "재킷": "Jacket", "후드집업": "Zip-up Hoodie", "구두": "Dress Shoes", "부츠": "Boots",
    "모자": "Hat", "가방": "Bag", "양말": "Socks", "벨트": "Belt", "볼캡": "Ball Cap",
    # 핏 · 무늬
    "오버핏": "Oversized", "슬림핏": "Slim Fit", "크롭": "Cropped", "레귤러핏": "Regular Fit",
    "무지": "Solid", "스트라이프": "Stripe", "체크": "Check", "로고·그래픽": "Logo/Graphic", "꽃무늬": "Floral", "기타": "Other",
    "핏": "Fit", "무늬": "Pattern", "패턴": "Pattern", "핏·무늬": "Fit & Pattern",
    # 단
    "신상품": "New arrivals", "신상": "New", "상단": "Upper", "중단": "Middle", "하단": "Lower", "상": "Up", "중": "Mid", "하": "Low",
    # 상품명 낱말
    "3팩": "3-Pack", "UV": "UV", "감탄팬츠": "Comfort Pants", "경량": "Light", "골지": "Ribbed", "그래픽": "Graphic",
    "기모": "Fleece-lined", "긴팔": "Long-sleeve", "나일론": "Nylon", "다운": "Down", "더비": "Derby", "데님": "Denim",
    "데일리": "Daily", "드라이": "Dry", "라운드": "Round", "라이더": "Rider", "램스울": "Lambswool", "러닝": "Running",
    "러닝화": "Running Shoes", "레귤러": "Regular", "레더": "Leather", "레이온": "Rayon", "레트로": "Retro", "로고": "Logo",
    "로우": "Low", "로퍼": "Loafers", "롱": "Long", "롱슬리브": "Long Sleeve", "리넨": "Linen", "린넨": "Linen",
    "메리노": "Merino", "메리제인": "Mary Jane", "메쉬": "Mesh", "미니": "Mini", "미디": "Midi", "반집업": "Half-zip",
    "반팔": "Short-sleeve", "백팩": "Backpack", "버킷햇": "Bucket Hat", "버튼다운": "Button-down", "베이직": "Basic",
    "보더": "Border", "부츠컷": "Bootcut", "브이넥": "V-neck", "블렌드": "Blend", "블루종": "Blouson", "비니": "Beanie",
    "빅프린트": "Big Print", "삭스": "Socks", "새틴": "Satin", "샌들": "Sandals", "셀비지": "Selvedge", "셔켓": "Shacket",
    "소프트": "Soft", "소프트터치": "Soft-touch", "숏": "Short", "수피마": "Supima", "슈즈": "Shoes", "스니커즈": "Sneakers",
    "스마트": "Smart", "스웨이드": "Suede", "스웨트": "Sweat", "스웨트셔츠": "Sweatshirt", "스트레이트": "Straight",
    "스트레치": "Stretch", "슬라이드": "Slide", "슬럽": "Slub", "슬림": "Slim", "싱글": "Single", "앵클": "Ankle",
    "에어리": "Airy", "오버사이즈": "Oversized", "오버셔츠": "Overshirt", "옥스포드": "Oxford", "와이드": "Wide",
    "와플": "Waffle", "울": "Wool", "울트라": "Ultra", "워싱": "Washed", "워커": "Worker", "자수": "Embroidered",
    "조거": "Jogger", "진": "Jeans", "집업": "Zip-up", "체스터": "Chester", "첼시": "Chelsea", "치노": "Chino",
    "카고": "Cargo", "캔버스": "Canvas", "케이블": "Cable", "코듀로이": "Corduroy", "코치": "Coach", "코튼": "Cotton",
    "쿠셔닝": "Cushioned", "쿠션": "Cushion", "크로스백": "Crossbody Bag", "크루": "Crew", "크루넥": "Crewneck",
    "터틀넥": "Turtleneck", "턱": "Tuck", "테일러드": "Tailored", "토트백": "Tote Bag", "트랙": "Track", "트러커": "Trucker",
    "트레일": "Trail", "트렌치": "Trench", "티셔츠": "T-shirt", "팬츠": "Pants", "퍼퍼": "Puffer", "페니": "Penny",
    "포켓": "Pocket", "포켓터블": "Packable", "프린트": "Print", "프릴": "Frill", "플라워": "Flower", "플란넬": "Flannel",
    "플랫폼": "Platform", "플리스": "Fleece", "플리츠": "Pleated", "피그먼트": "Pigment", "하이탑": "High-top",
    "하프집업": "Half-zip", "헤비웨이트": "Heavyweight", "후드": "Hooded", "후리스": "Fleece", "이승헌": "Lee Seung-heon",
    # 매장 · 집기
    "행거": "Rack", "매대": "Table", "마네킹": "Mannequin", "선반": "Shelf", "벽면": "Wall", "진열대": "Stand",
    "입구": "Entrance", "계산대": "Checkout", "기둥": "Pillar", "피팅룸": "Fitting Room", "탈의실": "Fitting Room",
    "창고": "Stockroom", "매장": "Store", "직원": "Staff", "손님": "Customer", "전체": "All", "옷": "Clothes",
    "나": "You", "출발": "Start", "도착": "Arrive",
}

# ---------------------------------------------------------------- 문장 통째로
PHRASES = {
    # 공통 · 탭
    "검색": "Search", "찜": "Saved", "MY": "MY", "안내": "Info", "찾기": "Search", "뒤로": "Back", "닫기": "Close", "메뉴": "Menu",
    "확인": "OK", "저장": "Save", "저장하기": "Save", "삭제": "Delete", "지우기": "Clear", "수정": "Edit", "취소": "Cancel",
    "등록": "Register", "옷 목록": "Items", "신고함": "Requests", "설정": "Settings", "직원 메뉴": "Staff menu",
    "현 위치 ·": "You are at ·", "검색 결과": "Search results", "처음으로": "Home", "목록으로": "Back to list",
    "출처": "Credits", "상품 사진": "Product photos", "상품 사진 출처": "Product photo credits", "도움말": "Help",
    "예) 파란색 후드티, 오버핏 맨투맨": "e.g. blue hoodie, oversized sweatshirt", "사진으로 찾기": "Search by photo",
    "AI가 사진 속 옷을 분석하고 있어요…": "AI is analyzing the clothes in your photo…", "🤖 AI가 옷을 분석하고 있어요…": "🤖 AI is analyzing the item…",
    "옷 종류 · 색 알아보기": "Detecting type & color", "무늬 · 핏 살펴보기": "Checking pattern & fit", "매장 상품과 비교하기": "Matching store items",
    # QR 첫 화면
    "인기 검색어": "Popular", "급상승": "Trending", "전체 손님 기준": "All customers", "최근 검색": "Recent searches",
    "종류": "Category", "전체 보기": "View all", "상의 전체": "All tops", "하의 전체": "All bottoms", "아우터 전체": "All outerwear",
    "신발 전체": "All shoes", "잡화 전체": "All accessories", "남성": "Men", "여성": "Women",
    "10대 남성 기준": "Men in their teens", "20대 남성 기준": "Men in their 20s", "30대 남성 기준": "Men in their 30s",
    "40대 남성 기준": "Men in their 40s", "50대 이상 남성 기준": "Men 50+", "10대 여성 기준": "Women in their teens",
    "20대 여성 기준": "Women in their 20s", "30대 여성 기준": "Women in their 30s", "40대 여성 기준": "Women in their 40s",
    "50대 이상 여성 기준": "Women 50+",
    "검정 후드티": "black hoodie", "와이드 청바지": "wide jeans", "오버핏 맨투맨": "oversized sweatshirt", "숏 패딩": "short puffer",
    "흰 운동화": "white sneakers", "크롭 니트": "cropped knit",
    # 검색 결과
    "색상": "Color", "색": "Color", "가까운 순": "Nearest first", "색상·종류를 알아듣고 찾았어요": "Matched by color & type",
    "이름으로 찾았어요": "Matched by name", "전체 상품": "All items", "딱 맞는 옷": "Exact matches", "비슷한 옷": "Similar items",
    "조건에 맞는 옷이 없어요": "No items match", "위에서 조건을 하나 빼거나, 이렇게 찾아보세요": "Remove a filter above, or try these",
    "조건 지우기": "Clear filters", "위치 미등록": "No location yet", "재고 없음": "Out of stock", "위치 없음": "No location",
    "위치 정보 없음": "No location info", "모두 해제": "Clear all",
    # 상품 화면
    "가는 길": "Route", "사이즈별 재고": "Stock by size", "사이즈": "Size", "찾았어요!": "Found it!", "찾는 게 없나요?": "Can't find it?",
    "찜하기": "Save", "찜 해제": "Unsave", "어떤 게 안 되나요?": "What's wrong?", "다른 색 · 비슷한 옷": "Other colors · Similar",
    "여기에 옷이 없어요": "It's not here", "직원에게 물어보기": "Ask staff", "직원 호출": "Call staff",
    "다른 색을 보고 싶어요": "I want another color", "다른 색 위치 · 비슷한 옷 추천": "Other color locations · similar picks",
    "재고 확인 · 직원 도움": "Check stock · staff help", "직원에게 알렸어요. 이 자리에서 잠시만 기다려 주세요.": "Staff has been notified. Please wait here.",
    "직원에게 알렸어요. 이 자리에서 잠시만 기다려 주세요": "Staff has been notified. Please wait here.",
    "직원이 가고 있어요!": "Staff is on the way!", "직원이 도착했어요": "Staff has arrived",
    "매장에 재고가 없어요 · 비슷한 옷을 확인해 보세요": "Out of stock in store · see similar items",
    "직원이 바빠요 · 계산대로 와 주세요": "Staff is busy · please come to the checkout",
    "방금 요청": "Just requested", "분째 기다리는 중": " min waiting", "고마워요!": "Thank you!",
    " (이 위치는 안내에서 내렸어요)": " (this location was removed from guidance)",
    "찜목록에 담았어요 · 첫 화면 아래 ‘찜’ 탭에서 모아 볼 수 있어요": "Saved · see it in the ‘Saved’ tab at the bottom",
    "찜목록에 담았어요": "Saved", "찜목록에서 뺐어요": "Removed from saved", "찜목록": "Saved",
    "하트를 누르면 여기에 모여요": "Tap the heart to save items here", "아직 찜한 옷이 없어요": "No saved items yet",
    "옷 찾으러 가기": "Find clothes", "많이 찜한 옷": "Most saved",
    "추천 사이즈": "Suggested size", "키·몸무게 등록": "Add height & weight", "하고 추천 사이즈 보기": " to see your size",
    "지금 없어요": "Not available", "발 사이즈": "Foot size", "를 입력하면 추천해요": " to get a suggestion", "신발은 ": "For shoes, enter your ",
    " · 오버핏이라 한 치수 작게": " · oversized, so one size down", " · 오버핏이라 평소 사이즈로도 넉넉해요": " · oversized, your usual size fits loose",
    " · 넉넉하게 입는 걸 좋아해서 한 치수 크게": " · you like it loose, one size up",
    "그 자리에 있음": "It's there", "다른 곳에 있었음": "It was elsewhere", "잘 모르겠어요": "Not sure",
    "직원에게 직접 물어볼게요": "I'll ask staff myself", "직원에게 찾아 달라고 하기": "Ask staff to find it",
    "괜찮아요, 다른 옷 볼게요": "That's OK, I'll look at others", "사이즈를 고르면 직원이 찾아 드려요": "Pick a size and staff will find it",
    "골라 주시면 직원이 미리 알고 와요": "Choose one so staff knows before coming", "그냥 와 주세요": "Just come please",
    "사이즈·핏 상담": "Size & fit advice", "세탁·소재 문의": "Care & material", "탈의실 위치": "Fitting room location",
    "직원에게 입고 일정 물어보기": "Ask staff about restock", "비슷한 옷 중 S 사이즈가 있는 것": "Similar items in size S",
    "이 옷은 S 사이즈가 매장에도 창고에도 없어요.": "Size S is not in store or stockroom.",
    "직원이 창고에서 가져다 드려요": "Staff will bring it from the stockroom", "창고에만 있는 사이즈": "Size only in stockroom",
    "창고 사이즈 요청": "Stockroom size request", "창고만": "Stockroom only", "바로 근처예요": "It's right nearby",
    "직원이 이 선반으로 와요": "Staff will come to this shelf", "잠시만 기다려 주세요": "Please wait a moment",
    "직원이 가는 중": "Staff on the way", "손님이 기다리는 중": "Customer waiting", "직원에게 알림": "Notify staff",
    "많음": "Many", "적음": "Few", "없음": "None", "도착": "Arrive", "출발": "Start", "등록 안 함": "Not set",
    "상단 · 위 칸": "Upper · top row", "중단 · 가운데 칸": "Middle · middle row", "하단 · 아래 칸": "Lower · bottom row",
    "상단 (맨 위 칸)": "Upper (top row)", "중단 (가운데 칸)": "Middle (middle row)", "하단 (맨 아래 칸)": "Lower (bottom row)",
    "맨 위 칸": "top row", "가운데 칸": "middle row", "맨 아래 칸": "bottom row", "위 칸": "top row", "아래 칸": "bottom row",
    "QR 위치": "QR location", "입구로 들어와서 왼쪽 가운데": "From the entrance, left middle",
    "입구로 들어와서 정면 가장 안쪽": "From the entrance, straight to the back",
    # MY · 안내
    "MY · 사이즈·성별·나이": "MY · size, gender, age", "이 휴대폰에만": "Saved only on this phone", "저장돼요": "",
    "성별": "Gender", "· 검색어 기준": "· for search trends", "나이": "Age", "세": "yrs", "키": "Height", "몸무게": "Weight",
    "선택 · 신발 추천용": "Optional · for shoe sizes", "평소 옷을 어떻게 입나요?": "How do you usually wear clothes?",
    "딱 맞게": "Fitted", "보통": "Regular", "넉넉하게": "Loose", "내 정보 지우기": "Clear my info", "내 정보": "My info",
    "기본 정보": "Basics", "언어": "Language", "한국어": "한국어", "글자 크기": "Text size", "크게": "Large",
    "이용 방법": "How to use", "지금 이용 중인 매장": "Current store", "유니클로 명동점": "UNIQLO Myeongdong",
    "매장 안 옷 위치 안내 서비스": "In-store clothing locator", "무엇이 궁금하세요?": "What do you need?",
    "찾는 옷을 글자로 검색하거나 사진을 찍어요.": "Search by text or take a photo of what you want.",
    "상품을 누르면 몇 번 행거 · 몇 번째 칸인지와 가는 길이 나와요.": "Tap an item to see its rack, row and the route there.",
    "를 눌러 다른 색 · 재고 · 직원 도움을 받아요.": " for other colors, stock and staff help.",
    "where:wear의 상품 사진은": "where:wear product photos are from",
    "에서 제공받았어요. 각 사진의 촬영자는 아래와 같아요.": ". Photographers are listed below.",
    # 키오스크
    "옷 찾기": "Find clothes", "세부 종류": "Type", "위치": "Location", "무엇을 찾으세요?": "What are you looking for?",
    "종류만 고르면 옷이 있는 자리를 알려드려요": "Pick a category and we'll show where it is",
    "찾은 위치는 종이 지도로 뽑아 갈 수 있어요": "You can print the location on a paper map",
    "잘 모르겠어요 ": "Not sure ", "모든 상의": "All tops", "모든 하의": "All bottoms", "모든 아우터": "All outerwear",
    "모든 신발": "All shoes", "모든 잡화": "All accessories", "모든 색 상의": "Tops, any color", "모든 색 하의": "Bottoms, any color",
    "모든 색 아우터": "Outerwear, any color", "모든 색 신발": "Shoes, any color", "모든 색 잡화": "Accessories, any color",
    "어떤 색인가요?": "Which color?", "어떤 종류인가요?": "Which type?", "색 상관없이 모두 보기": "Show all colors",
    "종류 다시 고르기": "Choose category again", "세부 종류 다시": "Choose type again", "색 다시 고르기": "Choose color again",
    "옷 사진을 누르면 있는 곳을 크게 보여드려요": "Tap a photo to see where it is",
    "종이 지도 받기": "Print paper map", "종이 지도를 뽑고 있어요": "Printing your paper map",
    "키오스크 아래 출력구에서 가져가세요": "Take it from the slot below the kiosk", "못 찾으면 가까운 직원에게 물어보세요": "If you can't find it, ask nearby staff",
    "계속 보시겠어요?": "Still there?", "초 뒤에 처음 화면으로 돌아가요": " s until returning to the start", "계속 볼게요": "Keep browsing",
    "누르면 직원이 여기로 가져다 드려요": "Tap and staff will bring it here", "사이즈 · 이 자리(매장 입구 키오스크)에서": "Size · at this spot (entrance kiosk)",
    "핏·무늬": "Fit & Pattern", "전시 실물": "On display", "추천": "Pick", "입구": "Entrance", "지도": "Map",
    "이 매장은 키오스크를 쓰지 않아요": "This store doesn't use the kiosk", "휴대폰으로 선반 QR을 찍어 주세요": "Scan a shelf QR with your phone",
    "키오스크에서 옷 찾기": "Find clothes at the kiosk",
    # 직원 · 등록
    "직원": "Staff", "바코드 모드": "Barcode", "사진 모드": "Photo", "선반 QR을 찍으세요": "Scan the shelf QR",
    "옷 태그(바코드)를 찍으세요": "Scan the item tag (barcode)", "· 같은 상품은 한 번만": "· once per product", "미선택": "Not set",
    "선반의 QR을 네모 안에 맞춰 주세요": "Fit the shelf QR inside the frame", "옷 태그 바코드를 가로로 맞춰 주세요": "Hold the tag barcode horizontally",
    "다른 색상도 함께 등록": "Register other colors too", "직접 등록": "Manual entry", "단": "Row",
    "옷 이름이나 색으로 찾기": "Find by name or color", "예) 후드 블랙, 청바지, UQ013": "e.g. hood black, jeans, UQ013",
    "두 글자 이상 입력하면 아래에 나와요 · 누르면 바로 등록": "Type 2+ letters to see items · tap to register",
    "맞는 옷이 없어요": "No matching items", "바코드 직접 입력": "Enter barcode", "시즌마다 바코드가 달라도 같은 상품으로 묶여요. 예:": "Season barcodes map to the same product. e.g.",
    "최근 등록": "Recently registered", "아직 등록한 옷이 없어요": "Nothing registered yet", "등록하지 못했어요": "Couldn't register",
    "바코드를 다시 찍거나 아래 '직접 등록'에서 이름으로 찾아 주세요": "Scan again or search by name in 'Manual entry' below",
    "이 선반에 이번에 ": "Registered on this shelf: ", "벌 등록했어요": " items", "✓ 등록됐어요": "✓ Registered", "되돌리기 ": "Undo ",
    "색)": " colors)", "처음 등록": "First registration", "같은 선반 · 위치 확인 시각만 새로": "Same shelf · check time updated",
    "예전 위치 ": "Moved from ", "에서 옮김": "", " · 사이즈 ": " · ", "종 함께": " sizes", "↩ 되돌렸어요": "↩ Undone",
    " 은(는) 예전 위치로 다시 안내돼요": " is guided to its previous location again", "카메라를 쓸 수 없어요 (": "Camera unavailable (",
    ").<br>아래 '직접 등록'을 눌러 주세요.": ").<br>Tap 'Manual entry' below.", "찍히면 진동": "Vibrates on scan",
    "다시 찍을 옷": "Items to rescan", "'없어요' 신고": "'Not here' reports", "손님이 못 찾았다고 한 옷": "Customers couldn't find these",
    "안내할 위치가 아직 없는 옷": "No location registered yet", "오래된 위치": "Stale location", "그대로 맞아요": "Still correct",
    "다시 찍기": "Rescan", "진열 점검할 때예요": "Time to check displays", "점검 완료": "Done checking",
    "걸어둘 선반을 고르고": "Pick the shelf to hang it on", "옷을 정면에서 찍으면 AI가 특징을 채워요": "Shoot the item from the front and AI fills in details",
    "촬영하기": "Take photo", "사진 고르기": "Choose photo", "종류 · 색 · 무늬 · 핏을 채우는 중이에요": "Filling in type, color, pattern & fit",
    "확인·수정 후 저장": "Review, edit & save", "옷 정보 수정": "Edit item", "상품명": "Product name", "가격 (원)": "Price (₩)",
    "분류": "Category", "직원 · 사진으로 상품 등록": "Staff · register by photo", "직원 · 위치 등록": "Staff · register location",
    "직원 · 신고 · 호출 목록": "Staff · reports & calls", "종류별": "By type", "선반별": "By shelf", "모든 단": "All rows",
    "전체 선반": "All shelves", "이름 · 색 · 상품번호로 찾기": "Find by name · color · code", "맞는 옷이 없어요 ": "No matching items",
    # 신고함
    "손님 대기": "Waiting", "위치 고칠 것": "Fix location", "처리 기록": "History", "기다리는 손님이 없어요.": "No customers waiting.",
    "가는 중": "Going", "전달 완료": "Delivered", "찾아서 재등록": "Found & re-registered", "오신고": "False report",
    "손님 QR: 옷이 그 자리에 없어요": "Customer QR: item isn't there", "새 손님 요청이 들어왔어요": "New customer request",
    "🔔 새 요청 · 신고함": "🔔 New request · Requests", "잠금화면 신고 알림 켜기": "Turn on lock-screen alerts",
    "잠금화면 신고 알림 켜짐": "Lock-screen alerts on", "알림을 껐어요": "Alerts turned off",
    "휴대폰 설정에서 알림을 허용해 주세요": "Allow notifications in phone settings", "켜졌어요 · 테스트 알림을 보냈어요": "On · test alert sent",
    "신고가 들어오면 기본 알림음과 함께 잠금화면에 떠요": "New reports appear on the lock screen with the default sound",
    "https 공유 주소(공유링크켜기)로 열어야 켤 수 있어요": "Open via the https share link to enable",
    "https 공유 주소를 사파리로 열고 [공유 → 홈 화면에 추가] 후 그 아이콘으로 열면 켤 수 있어요": "Open the https link in Safari, Share → Add to Home Screen, then open from that icon",
    "분 ": " min ", "초째": " s", "자동 새로고침": "Auto refresh", "직원 신고함에서 처리": "Handled in staff requests",
    "기다리는 손님 → '가는 중' → '전달 완료', 위치 고칠 것 → '찾아서 재등록'": "Waiting → 'Going' → 'Delivered'; Fix location → 'Found & re-registered'",
    "안내에서 내려감": "Removed from guidance", "손님이 찾음": "Customer found it", "이동 등록": "Moved",
    "지금 꺼짐": "Off now", "바쁨 모드 꺼짐": "Busy mode off", "바쁨 모드": "Busy mode", "켜기": "On", "끄기": "Off", "자동": "Auto",
    # 점장 요약
    "점장 요약": "Manager summary", "점검이 필요해요": "Needs attention", "직원 없이 옷을 찾았어요": "found items without staff",
    "손님 절반 이상이 못 찾아요 → 위치 다시 찍기부터": "Over half can't find items → start by rescanning locations",
    "지금 할 일": "To do now", "중요한 것부터": "Most important first", "자주 못 찾는 자리": "Hard-to-find spots",
    "진할수록 '없어요'가 많아요": "Darker = more 'Not here'", "동선 보기": "Route", "선반에 한 번 가서 한꺼번에 고쳐요": "Fix them all in one trip",
    "한 번에 도는 길": "One-trip route", "한 번에 도는 길로 돌면서 고쳐요": "Fix them along the one-trip route",
    "빨리 고칠수록 다음 손님이 헛걸음 안 해요": "Fix fast so the next customer doesn't walk for nothing",
    "응대 속도": "Response time", "호출 → 손님에게 도착": "Call → arrived at customer", "지난주와 비교": "vs last week",
    "줄면 손님이 혼자 잘 찾는다는 뜻": "Lower means customers find things on their own", "살펴볼 옷": "Items to check",
    "'없어요'가 많은 옷": "Most 'Not here'", "'없어요' → 위치 고침": "'Not here' → location fixed",
    "→ 진열 위치·선반 라벨을 먼저 점검하세요": "→ check display spots and shelf labels first", "아래 빨간 카드부터 확인하세요": "Start with the red cards below",
    "진열·라벨 점검": "Check display & labels", "일주일 동안 쌓인 신고를 매장 지도에 색으로 보여 줘요 → 진열을 바꿀 곳": "A week of reports colored on the map → where to change displays",
    "점장 요약 · 자주 못 찾는 자리": "Manager summary · hard-to-find spots",
    "가장 적게 걷는 순서예요 (아래 목록도 이 순서)": "Shortest walking order (list below follows it)",
    # 설정
    "매장 설정": "Store settings", "매장 유형": "Store type", "대형": "Large", "중형": "Medium", "소형": "Small",
    "대형 매장": "Large store", "중형 매장": "Medium store", "소형 매장": "Small store", "일반 매장": "Regular store",
    "손님이 많은 대형 매장": "Large, busy store", "직원이 바로 보이는 작은 매장": "Small store, staff always visible",
    "지금 근무하는 직원 수": "Staff on duty now", "한 명 줄이기": "One fewer", "한 명 늘리기": "One more",
    "직원이 적거나 손님이 몰리면 켜져요": "Turns on when staff is short or it gets busy", "끄면 '직원에게 문의'만 보여요": "When off, only 'Ask staff' shows",
    "항상 직원 호출 가능": "Staff call always available", "직원 호출 대신 계산대로 안내": "Guide to checkout instead of calling",
    "이 매장에서 키오스크 사용": "Use kiosk in this store", "응답": "Response",
    # 시연
    "발표 시연 모드": "Demo mode", "🎬 발표 시연 모드 (시연 상황 만들기 · 지우기)": "🎬 Demo mode (create · clear demo data)",
    "🎬 한 번에 발표 준비": "🎬 One-click demo setup", "시연 준비": "Demo setup", "시연 순서": "Demo order",
    "시연용 (매장 · 직원 화면)": "For demo (store · staff)", "시연 기록 모두 지우기 (원래대로)": "Clear all demo data (reset)",
    "시연용 기록은 따로 표시돼서, 지우기를 누르면 진짜 기록은 그대로 남아요": "Demo data is tagged, so clearing keeps real data",
    "각 버튼은 새 탭으로 열려요 · 발표 화면 옆에 띄워 두세요": "Each button opens a new tab · keep it beside your slides",
    "지금 손님 신고 만들기": "Create a customer report now", "손님 화면 열기": "Open customer view", "손님 화면으로 보기": "View as customer",
    "키오스크 열기": "Open kiosk", "신고함 열기": "Open requests", "점장 요약 열기": "Open manager summary",
    "입구 키오스크 화면": "Entrance kiosk", "키오스크 상품 화면": "Kiosk item screen", "기록 중…": "Recording…",
    "입구 키오스크에서 종류 → 색 → 위치를 고르고, 종이 지도를 뽑아요": "At the kiosk pick category → color → location and print a map",
    "캔버스 로우 스니커즈 화면에서 \"가져다 주세요\"를 누르면 직원 신고함에 바로 떠요": "Tap \"Bring it\" on Canvas Low Sneakers and it shows in staff requests",
}

# ---------------------------------------------------------------- 숫자가 들어간 문장
def _p(rx, fn): return (re.compile(rx), fn)
PATTERNS = [
    _p(r"([A-Z])구역", lambda m, t: f"Zone {m[1]}"),
    _p(r"([A-Z])구역 전체", lambda m, t: f"All of Zone {m[1]}"),
    _p(r"(\d+)분 전 등록", lambda m, t: f"Registered {m[1]} min ago"),
    _p(r"(\d+)시간 전 등록", lambda m, t: f"Registered {m[1]} h ago"),
    _p(r"(\d+)분 전", lambda m, t: f"{m[1]} min ago"),
    _p(r"(\d+)시간 전", lambda m, t: f"{m[1]} h ago"),
    _p(r"방금", lambda m, t: "just now"),
    _p(r"이 매장 인기 TOP (\d+)", lambda m, t: f"Top {m[1]} in this store"),
    _p(r"(입구에서 )?(앞으로|오른쪽으로|왼쪽으로|오른쪽으로 꺾어|왼쪽으로 꺾어|뒤로 돌아) (\d+)m",
       lambda m, t: ("From the entrance, " if m[1] else "") + {"앞으로": "go straight", "오른쪽으로": "go right", "왼쪽으로": "go left",
                     "오른쪽으로 꺾어": "turn right,", "왼쪽으로 꺾어": "turn left,", "뒤로 돌아": "turn around,"}[m[2]] + f" {m[3]} m"),
    _p(r"(왼쪽|오른쪽|바로 앞)에 (.+)", lambda m, t: {"왼쪽": "on your left: ", "오른쪽": "on your right: ", "바로 앞": "straight ahead: "}[m[1]] + t(m[2])),
    _p(r"(.+)에 있어요", lambda m, t: f"It's at {t(m[1])}"),
    _p(r"(\d+)분째", lambda m, t: f"{m[1]} min"),
    _p(r"전체 알림 보냄", lambda m, t: "Alerted all staff"),
    _p(r"'(.+)' 조건을 모두 만족", lambda m, t: f"Matches all of '{m[1]}'"),
    _p(r"([A-Z]+-?[A-Z]*\d+) (.+)", lambda m, t: f"{m[1]} {t(m[2])}"),
    _p(r"· (.+)", lambda m, t: f"· {t(m[1])}"),
    _p(r"([A-Z])구역 (.+)", lambda m, t: f"Zone {m[1]} {t(m[2])}"),
    _p(r"(\d+)번 행거", lambda m, t: f"Rack {m[1]}"),
    _p(r"원형 행거 (\d+)", lambda m, t: f"Round rack {m[1]}"),
    _p(r"([\d,]+)원", lambda m, t: f"₩{m[1]}"),
    _p(r"(\d+)개", lambda m, t: f"{m[1]}"),
    _p(r"(\d+)건", lambda m, t: f"{m[1]}"),
    _p(r"(\d+)벌", lambda m, t: f"{m[1]} pcs"),
    _p(r"(\d+)명", lambda m, t: f"{m[1]}"),
    _p(r"(\d+)종", lambda m, t: f"{m[1]} styles"),
    _p(r"(\d+)분", lambda m, t: f"{m[1]} min"),
    _p(r"분", lambda m, t: "min"),
    _p(r"건", lambda m, t: ""),
    _p(r"원", lambda m, t: "₩"),
    _p(r"이", lambda m, t: ""),
    _p(r"옷 (\d+)종", lambda m, t: f"{m[1]} styles"),
    _p(r"(.+) (\d+)개", lambda m, t: f"{t(m[1])} {m[2]}"),
    _p(r"\((.+)\)", lambda m, t: f"({t(m[1])})"),
    _p(r"✓ (.+)", lambda m, t: f"✓ {t(m[1])}"),
    _p(r"(\d+)일 전 등록", lambda m, t: f"Registered {m[1]}d ago"),
    _p(r"(\d+)분 지나면 자동 취소", lambda m, t: f"Auto-cancels after {m[1]} min"),
    _p(r"(\d+)일 넘게 다시 안 찍은 옷", lambda m, t: f"Not rescanned in {m[1]}+ days"),
    _p(r"(\d+)벌 더 보기", lambda m, t: f"Show {m[1]} more"),
    _p(r"'없어요' (\d+)건", lambda m, t: f"'Not here' ×{m[1]}"),
    _p(r"지금 안내 위치: (.+)", lambda m, t: f"Current location: {t(m[1])}"),
    _p(r"지금 안내: (.+)", lambda m, t: f"Now guided: {t(m[1])}"),
    _p(r"여기서 (\d+)m", lambda m, t: f"{m[1]} m from here"),
    _p(r"걸어서 약 (\d+)초", lambda m, t: f"about {m[1]} s walk"),
    _p(r"약 (\d+)m", lambda m, t: f"about {m[1]} m"),
    _p(r"매장 (\d+)", lambda m, t: f"Store {m[1]}"),
    _p(r"창고 (\d+)", lambda m, t: f"Stockroom {m[1]}"),
    _p(r"매장 (\d+)벌", lambda m, t: f"{m[1]} in store"),
    _p(r"창고 (\d+)벌", lambda m, t: f"{m[1]} in stockroom"),
    _p(r"매장에 (\d+)벌", lambda m, t: f"{m[1]} in store"),
    _p(r"창고에 (\d+)벌 있어요", lambda m, t: f"{m[1]} in stockroom"),
    _p(r"매장에 (\d+)벌 있어요", lambda m, t: f"{m[1]} in store"),
    _p(r"(\S+)은 창고에 (\d+)벌 있어요", lambda m, t: f"{m[1]}: {m[2]} in stockroom"),
    _p(r"(\S+) 가져다 주세요", lambda m, t: f"Bring me {m[1]}"),
    _p(r"최근 (\d+)일", lambda m, t: f"Last {m[1]} days"),
    _p(r"최근 (\d+)일 조회 (\d+)회", lambda m, t: f"{m[2]} views in {m[1]} days"),
    _p(r"신고 (\d+)명", lambda m, t: f"{m[1]} reports"),
    _p(r"첫 신고 (\d+)분 전", lambda m, t: f"first {m[1]} min ago"),
    _p(r"손님 (\d+)명 중", lambda m, t: f"Of {m[1]} customers,"),
    _p(r"직원 (\d+)명 근무 중", lambda m, t: f"{m[1]} staff on duty"),
    _p(r"놓친 호출 \((\d+)분 넘김\)", lambda m, t: f"Missed calls (over {m[1]} min)"),
    _p(r"목표 (\d+)분 이내", lambda m, t: f"Goal: under {m[1]} min"),
    _p(r"(\d+)건이 목표", lambda m, t: f"Goal: {m[1]}"),
    _p(r"지난주보다 ([▲▼]) (.+)", lambda m, t: f"{m[1]} {t(m[2])} vs last week"),
    _p(r"([\d.]+)%p", lambda m, t: f"{m[1]}%p"),
    _p(r"([\d.]+)분", lambda m, t: f"{m[1]} min"),
    _p(r"위치 고칠 선반 (\d+)곳", lambda m, t: f"Fix {m[1]} shelves"),
    _p(r"(\d+)곳", lambda m, t: f"{m[1]} stops"),
    _p(r"선반 (\d+)곳", lambda m, t: f"{m[1]} shelves"),
    _p(r"지금 신고·요청 (\d+)건", lambda m, t: f"{m[1]} open requests"),
    _p(r"쌓인 기록 (\d+)건", lambda m, t: f"{m[1]} records"),
    _p(r"이번 주 '없어요' (\d+)건", lambda m, t: f"{m[1]} 'Not here' this week"),
    _p(r"매장에서 가장 많아요", lambda m, t: "most in store"),
    _p(r"에서 가장 많이 못 찾아요 \((\d+)건\)", lambda m, t: f" is the hardest to find ({m[1]})"),
    _p(r"특히", lambda m, t: "especially"),
    _p(r"다른 색 (\d+)가지", lambda m, t: f"{m[1]} other colors"),
    _p(r"있는 곳", lambda m, t: "where"),
    _p(r"전시 실물 \((\d+)\)", lambda m, t: f"On display ({m[1]})"),
    _p(r"지난 (\d+)주 기록 채우기", lambda m, t: f"Fill last {m[1]} weeks of data"),
    _p(r"(\d+)명 이하이면 바쁨 모드가 자동으로 켜져요", lambda m, t: f"Busy mode turns on at {m[1]} staff or fewer"),
    _p(r"📊 점장 요약 보기 \(최근 (\d+)일\)", lambda m, t: f"📊 Manager summary (last {m[1]} days)"),
    _p(r"'없어요'를 (\d+)명이 누르면 안내에서 자동으로 내려가요 (.*)", lambda m, t: f"When {m[1]} people tap 'Not here', the location is removed automatically"),
    _p(r"(.+) · (.+) 앞에서 QR을 찍은 손님 화면이에요.", lambda m, t: f"{t(m[1])} · customer view after scanning the QR at {m[2]}."),
    _p(r"(.+) 화면에서 \"가져다 주세요\"를 누르면 직원 신고함에 바로 떠요", lambda m, t: f"Tap \"Bring it\" on {t(m[1])} and it shows in staff requests"),
    _p(r"Pexels에서 보기", lambda m, t: "View on Pexels"),
    _p(r"(\d+)초 뒤에 처음 화면으로 돌아가요", lambda m, t: f"Returning to start in {m[1]} s"),
    _p(r"(\d+)건 되돌렸어요", lambda m, t: f"Undid {m[1]}"),
    _p(r"모르는 코드: (.+)", lambda m, t: f"Unknown code: {m[1]}"),
    _p(r"모르는 선반: (.+)", lambda m, t: f"Unknown shelf: {m[1]}"),
    _p(r"직원에게 (\S+) 찾아 달라고 하기", lambda m, t: f"Ask staff to find {m[1]}"),
    _p(r"발 (\d+)mm 기준", lambda m, t: f"based on {m[1]} mm foot"),
    _p(r"(\d+)cm · (\d+)kg 기준", lambda m, t: f"based on {m[1]} cm · {m[2]} kg"),
]

# 집기 이름 통째로 (매장 입구(키오스크) 같은 괄호 포함)
PHRASES.update({
    "매장 입구(키오스크)": "Store entrance (kiosk)", "창고 (직원 전용)": "Stockroom (staff only)", "창고 · 직원 전용": "Stockroom · staff only",
    "벽면 선반": "Wall shelf", "데님 매대": "Denim table", "신발 벽면": "Shoe wall", "신발 진열대": "Shoe stand",
    "잡화 진열대": "Accessories stand", "신상품 매대": "New arrivals", "입구 마네킹": "Entrance mannequin", "할인 매대": "Sale table",
    "입구 추천존": "Entrance picks", "앞에서 QR을 찍은 손님 화면이에요.": "— customer view after scanning this shelf QR.", "언어 · Language": "Language", "지금 켜짐": "On now", "저장했어요": "Saved",
    "where:wear 종이 지도": "where:wear paper map", "매장 안 옷 위치 안내": "In-store clothing guide", "찾아갈 곳": "Destination",
    "● 나 → 점선을 따라 ①②③에서 꺾으면 도착": "● You → follow the dashed line and turn at ①②③ to arrive",
    "사이즈별 재고 (매장/창고)": "Stock by size (store/stockroom)", "옷이 없으면": "Not there?", "휴대폰 카메라로 이 네모를 비추세요": "Point your phone camera at this square",
    "재고 확인": "Check stock", "직원 부르기": "Call staff", "직원에게 문의": "Ask staff", "이 옷 QR": "QR for this item",
    "이번 주 신상품": "New this week", "입구 바로 앞 신상품 매대": "New arrivals table by the entrance", "할인 매대": "Sale table",
    "들어와서 오른쪽 할인 매대": "Sale table on your right as you enter", "사진 한 장으로 찾기": "Find with one photo",
    "비슷한 옷과 위치를 바로 알려 드려요": "We'll show similar items and where they are", "최근 7일 조회 · 찜 기준": "Views & saves, last 7 days",
    "이전 단계로": "Back", "English": "English", "재등록": "Re-registered", "패치": "Patch", "아직 없어요": "Not yet", "찾았으면": "If you found it, tap",
    ", 없으면": "; if not, tap", "(안 눌러도 돼요)": "(optional)", "위치 보기": "View location", "매장 도면과 길 안내": "Store map & directions",
    "거열 박": "Geoyeol Park",
})

# 키오스크 v3 (어두운 머리 · 매장 한눈에 보기 · 피팅룸/계산대 가는 길)
PHRASES.update({
    "현 위치 · 입구": "Here: Entrance", "현 위치": "You are here", "신상 · 세일": "New & Sale", "입구 바로 앞": "By the entrance",
    "매장 한눈에 보기": "Store at a glance", "구역을 누르면 그 옷을 보여 드려요": "Tap a zone to see its clothes",
    "피팅룸 가는 길": "Route to fitting rooms", "계산대 가는 길": "Route to checkout", "신상품 매대 가는 길": "Route to new arrivals",
    "할인 매대 가는 길": "Route to sale table", "옷을 입어 볼 수 있어요": "Try clothes on here", "계산 · 교환 · 환불": "Pay · exchange · refund",
    "이번 주 새로 들어온 옷": "New in this week", "할인하는 옷": "Clothes on sale", "이 매대 옷 보기": "See clothes on this table",
    "옷 보기": "See clothes", "재고 적음": "Low stock", "위치 확인 중": "Checking location", "처음 화면으로": "Back to start",
})
PATTERNS.insert(0, _p(r"입구에서 약 (\d+)m", lambda m, t: f"About {m[1]} m from the entrance"))
PATTERNS.insert(0, _p(r"걸어서 (\d+)초", lambda m, t: f"{m[1]} sec walk"))
_SIDE = {"왼쪽": "left", "오른쪽": "right", "정면": "straight ahead"}
_DEPTH = {"바로 앞": "near the front", "가운데": "middle", "가장 안쪽": "at the back"}
PATTERNS.insert(0, _p(r"입구로 들어와서 (왼쪽|오른쪽|정면) (바로 앞|가운데|가장 안쪽)",
                      lambda m, t: f"From the entrance, {_SIDE[m[1]]}, {_DEPTH[m[2]]}"))

_WORD_RX = re.compile("|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)))

def _words(s):
    """낱말 단위: 띄어쓰기로 나눈 각 낱말이 사전에 있으면 바꾼다 (상품 이름 · '블랙 상의' 같은 조합)"""
    out = []
    for tok in s.split(" "):
        if not H.search(tok): out.append(tok); continue
        if tok in PHRASES: out.append(PHRASES[tok]); continue
        if tok in WORDS: out.append(WORDS[tok]); continue
        out.append(_WORD_RX.sub(lambda m: " " + WORDS[m.group(0)] + " ", tok))
    r = re.sub(r"\s+", " ", " ".join(out)).strip()
    return re.sub(r"\s+([)\],.])", r"\1", re.sub(r"([(\[])\s+", r"\1", r))


# QR v3 홈 · 매장지도 · 카테고리 (2026.11)
PHRASES.update({
    "이번 주 신상품,": "New this week,", "입구 앞에 모았어요": "all by the entrance",
    "할인 매대에서": "Pick something light", "가볍게 골라 보세요": "from the sale table",
    "따뜻한 아우터는": "Warm outerwear is", "C구역에 모여 있어요": "all in Zone C",
    "AI 사진 검색": "AI photo search", "사진 한 장이면": "One photo is all it takes —",
    "매장에서 찾아 드려요": "we'll find it in store", "SNS에서 본 그 옷 · 캡처도 OK": "Seen it on social media? Screenshots work too",
    "세일": "Sale", "지금 매장 한눈에 보기": "The store at a glance", "크게 보기": "Bigger", "1층": "1F",
    "구역을 눌러 보세요": "Tap a zone", "여기": "Here", "매장 지도 크게 보기": "Open the big store map",
    "처음 오셨나요? 매장 이용 가이드": "First time here? How to use this store",
    "옷 찾기부터 직원 호출까지 1분이면 끝나요": "From finding clothes to calling staff — done in a minute",
    "손님, 이 옷 어때요?": "How about these?", "전체보기": "See all", "다른 손님들은 이걸 찾아요": "What other shoppers look for",
    "옷 위치 안내 프로토타입": "in-store clothing guide prototype",
    "도움이 필요하면 상품 화면의 '찾는 게 없나요?'로 직원을 불러 주세요 · 사진": "Need help? Tap 'Can't find it?' on an item to call staff · Photo",
    "홈": "Home", "카테고리": "Categories", "매장지도": "Map", "매장 지도": "Store map", "지금": "You are", "앞이에요": "now",
    "주황 점이 지금 내 위치, 점선이 가는 길이에요. 구역을 누르면 그 구역 옷을 보여 드려요.": "The orange dot is you and the dotted line is the route. Tap a zone to see its clothes.",
})
PATTERNS.insert(0, _p(r"· 손님은 (.+) 앞", lambda m, t: f"· You are at {t(m[1])}"))
PHRASES["전체 손님"] = "All shoppers"
PATTERNS.insert(0, _p(r"손님, (.+) 어디 있는지 찾으세요\?", lambda m, t: f"Looking for {t(m[1]).lower()}?"))
PATTERNS.insert(0, _p(r"(\d+:\d+) 기준", lambda m, t: f"as of {m[1]}"))
PATTERNS.insert(0, _p(r"여기서 약 (\d+)m", lambda m, t: f"about {m[1]} m from here"))


# 2026.11 피드백 반영: 말로 찾기 · 키오스크 이름으로 찾기 · 지도 사진 저장 · 휴대폰으로 받기
PHRASES.update({
    "말로 찾기": "Voice search", "‘찾았어요’를 누르면 보다 정확한 서비스를 제공해드려요!": "Tap 'Found it!' to help us keep locations accurate!", "검색": "Search", "말씀해 주세요": "Go ahead, I'm listening", "그만하기": "Stop",
    '예) "검정 후드티", "흰 운동화"': 'e.g. "black hoodie", "white sneakers"', '예) "검정 후드티"': 'e.g. "black hoodie"',
    "마이크 권한을 허용해 주세요 (설정 → 브라우저 → 마이크)": "Please allow microphone access (Settings → Browser → Microphone)",
    "잘 못 들었어요. 다시 눌러 주세요": "Didn't catch that. Tap again", "마이크를 쓸 수 없어요. 글자로 찾아 주세요": "Microphone unavailable. Please type instead",
    "‘찾았어요’를 누르면 이 위치가 맞다고 기록돼, 다음 손님 안내가 더 정확해져요": "Tapping 'Found it!' confirms this spot, so directions get more accurate for the next shopper",
    "지도 사진으로 저장 · 카톡으로 보내기": "Save map as photo · Share", "사진을 길게 눌러": "Press and hold the photo to",
    "하거나": "or", "하세요": "", "저장": "save", "공유": "share", "사진 내려받기": "Download photo", "지도 사진을 만들지 못했어요": "Couldn't create the map photo",
    "키오스크에서 받은 위치예요 · 아래": "Sent from the kiosk · Tap", "을 누르면 사진첩이나 카카오톡으로 보낼 수 있어요": "below to save it or share it",
    "이름으로 찾기": "Search by name", "글자 · 말로": "Type or speak", "찾기": "Search", "예) 검정 후드티 · 청바지": "e.g. black hoodie · jeans",
    "많이 찾는 옷": "Popular searches", "누르면 바로 찾아요": "Tap to search", "쌍자음": "Shift", "띄어쓰기": "Space", "다시 찾기": "Search again",
    "옷 고르기": "Pick", "색 · 핏 · 무늬": "Color · Fit · Pattern", "찾은 옷": "results", "세부 종류 다시": "Back to types",
    "휴대폰으로 받기": "Send to my phone", "지도 사진으로 저장": "Save map as photo", "휴대폰 카메라로 찍어 주세요": "Scan with your phone camera",
    "이 옷의 위치와 지도가 휴대폰에 열려요": "This item's location and map open on your phone", "을 누르면 사진첩에 저장하거나": "to save it to your photos or",
    "카카오톡으로 보낼 수 있어요": "send it via KakaoTalk", "‘지도 사진으로 저장’": "'Save map as photo'", "닫기": "Close",
})

def tr(s):
    """한 덩어리 글자를 영어로. 앞뒤 공백은 그대로 둔다."""
    if not s or not H.search(s): return s
    lead = s[:len(s) - len(s.lstrip())]; trail = s[len(s.rstrip()):]
    core = s.strip()
    return lead + _tr(core) + trail

EARLY = [
    _p(r"(.+) 옆까지", lambda m, t: f"to {t(m[1])}"),
    _p(r"([A-Z])구역\((.+)\)", lambda m, t: f"Zone {m[1]} ({t(m[2])})"),
    _p(r"(.+?)\s*\[(.+)\] 사이즈 (\d+)종 → (.+)", lambda m, t: f"{t(m[1])} [{t(m[2])}] {m[3]} sizes → {t(m[4])}"),
]

def _tr(core):
    if core in PHRASES: return PHRASES[core]
    for rx, fn in EARLY:
        m = rx.fullmatch(re.sub(r"\s+", " ", core))
        if m: return fn(m, _tr)
    if "\n" in core.strip():
        return "\n".join(_tr(l.strip()) if H.search(l) else l for l in core.strip().split("\n"))
    core2 = re.sub(r"\s+", " ", core)
    if core2 in PHRASES: return PHRASES[core2]
    if " · " in core2:
        return " · ".join(_tr(p) if H.search(p) else p for p in core2.split(" · "))
    for rx, fn in PATTERNS:
        m = rx.fullmatch(core2)
        if m: return fn(m, _tr)
    if " → " in core2:
        return " → ".join(_tr(p) if H.search(p) else p for p in core2.split(" → "))
    return _words(core2)

# ---------------------------------------------------------------- HTML · JSON 응답 바꾸기
_ATTRS = ("placeholder", "alt", "title", "aria-label", "data-label")
_TAG = re.compile(r"<(script|style)\b[^>]*>.*?</\1>|<!--.*?-->|<[^>]+>", re.S | re.I)
_ATTR = re.compile(r'\b(' + "|".join(_ATTRS) + r')="([^"]*)"')
_OPT = re.compile(r"<option(?![^>]*\bvalue=)([^>]*)>([^<]*[가-힣][^<]*)</option>")
_JSSTR = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"|`((?:[^`\\]|\\.)*)`")

def _js(code):
    """스크립트 안: 화면에 보이는 문장(사전에 통째로 있는 것)만 바꾸고, 데이터 값('상의', '오버핏' 등)은 그대로."""
    def rep(m):
        q = "'" if m.group(1) is not None else ('"' if m.group(2) is not None else "`")
        body = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))
        if not H.search(body): return m.group(0)
        if q == "`":       # 템플릿 문자열: 사전에 있는 조각만
            new = body
            for ko in sorted((k for k in JS_SUBS if k in body), key=len, reverse=True): new = new.replace(ko, JS_SUBS[ko])
            return q + new + q
        plain = body.replace("\\'", "'")
        if plain in PHRASES:
            return q + PHRASES[plain].replace(q, "\\" + q) + q
        for ko in sorted((k for k in JS_SUBS if k in plain), key=len, reverse=True):
            plain = plain.replace(ko, JS_SUBS[ko])
        return q + plain.replace(q, "\\" + q) + q if plain != body.replace("\\'", "'") else m.group(0)
    code = _JSSTR.sub(rep, code)
    for ko in sorted(JS_RAW, key=len, reverse=True):   # 소스 그대로 바꾸는 조각 (중첩 템플릿 문자열 등)
        code = code.replace(ko, JS_RAW[ko])
    return code

# 스크립트 안에서 조각으로 쓰이는 문장 (HTML이 섞인 것 포함)
JS_SUBS = {
    "두 글자 이상 입력하면 아래에 나와요 · 누르면 바로 등록": "Type 2+ letters to see items · tap to register",
    "맞는 옷이 없어요": "No matching items", "<span>등록</span>": "<span>Register</span>",
    "등록하지 못했어요": "Couldn't register", "✓ 등록됐어요": "✓ Registered", "되돌리기 ": "Undo ", "↩ 되돌렸어요": "↩ Undone",
    "바코드를 다시 찍거나 아래 \\'직접 등록\\'에서 이름으로 찾아 주세요": "Scan again or search by name in \\'Manual entry\\' below",
    "카메라를 쓸 수 없어요 (": "Camera unavailable (", ").<br>아래 \\'직접 등록\\'을 눌러 주세요.": ").<br>Tap \\'Manual entry\\' below.",
    "직원에게 ${sz} 찾아 달라고 하기": "Ask staff to find ${sz}", "방금 요청": "Just requested", "분째 기다리는 중": " min waiting",
    "발 ${p.foot}mm 기준": "based on ${p.foot} mm foot", "${p.h}cm · ${p.w}kg 기준": "based on ${p.h} cm · ${p.w} kg",
    " · ${ITEM.fit}이라 한 치수 크게": " · fitted cut, one size up", "추천 사이즈 <b>": "Suggested size <b>",
    "매장 ${q}벌": "${q} in store", "<b>창고에 ${w}벌</b>": "<b>${w} in stockroom</b>", "<b>지금 없어요</b>": "<b>Not available</b>",
    ">수정</a>": ">Edit</a>", "신고": "Report",
    "신발은 <a href=\"": "For shoes, enter your <a href=\"", "\">발 사이즈</a>를 입력하면 추천해요": "\">foot size</a> to get a suggestion",
    " <a href=\"": " <a href=\"", "\">키·몸무게 등록</a>하고 추천 사이즈 보기": "\">Add height & weight</a> to see your size",
}
JS_RAW = {
    "`매장 ${q}벌`": "`${q} in store`", "`<b>창고에 ${w}벌</b>`": "`<b>${w} in stockroom</b>`",
    "<small>바코드를 다시 찍거나 아래 \\'직접 등록\\'에서 이름으로 찾아 주세요</small>": "<small>Scan again or search by name in \\'Manual entry\\' below</small>",
    ").<br>아래 \\'직접 등록\\'을 눌러 주세요.</p>": ").<br>Tap \\'Manual entry\\' below.</p>",
    "' 은(는) 예전 위치로 다시 안내돼요</small>'": "' is guided to its previous location again</small>'",
    "'색)'": "' colors)'", "'처음 등록'": "'First registration'", "'같은 선반 · 위치 확인 시각만 새로'": "'Same shelf · check time updated'",
    "'예전 위치 '": "'Moved from '", "'에서 옮김'": "''", "' · 사이즈 '": "' · '", "'종 함께'": "' sizes'",
    "'이 선반에 이번에 '": "'Registered on this shelf: '", "'벌 등록했어요'": "' items'",
    "' · ${ITEM.fit}이라 한 치수 크게`": "' · fitted cut, one size up`", "` · ${ITEM.fit}이라 한 치수 크게`": "` · fitted cut, one size up`",
    "'분 '": "' min '", "'초째'": "' s'",
}
JS_SUBS.pop("신고")
JS_SUBS.pop(" <a href=\"")

def _seg(seg):
    if not H.search(seg): return seg
    return _h.escape(tr(_h.unescape(seg)), quote=False)

def html(text):
    """HTML 전체: 태그 밖 글자 + 일부 속성 + 스크립트 속 화면 문장"""
    text = text.replace('<html lang="ko">', '<html lang="en">')
    text = _OPT.sub(lambda m: f'<option value="{m[2].strip()}"{m[1]}>{m[2]}</option>', text)   # 값은 한국어로 유지
    out, pos = [], 0
    for m in _TAG.finditer(text):
        seg = text[pos:m.start()]
        out.append(_seg(seg))
        tag = m.group(0)
        if m.group(1):           # script / style
            if m.group(1).lower() == "script" and H.search(tag):
                i = tag.index(">") + 1; j = tag.rindex("</")
                tag = tag[:i] + _js(tag[i:j]) + tag[j:]
        elif H.search(tag) and not tag.startswith("<!--"):
            tag = _ATTR.sub(lambda a: f'{a[1]}="{_h.escape(tr(_h.unescape(a[2])))}"', tag)
        out.append(tag); pos = m.end()
    out.append(_seg(text[pos:]))
    return "".join(out)

JSON_KEYS = {"message", "name", "colors", "prev", "label", "title", "fixture_name", "level"}
def json_obj(o):
    if isinstance(o, dict): return {k: (tr(v) if k in JSON_KEYS and isinstance(v, str) else json_obj(v)) for k, v in o.items()}
    if isinstance(o, list): return [json_obj(v) for v in o]
    return o

# 2026.11 직원 피드백: 직원 이름 · 피팅룸 반납 · 동선 토글 · 바쁨 모드(대형) · 옷 삭제
PHRASES.update({
    "김준구": "Kim Jun-gu", "류한솔": "Ryu Han-sol", "이준혁": "Lee Jun-hyeok",
    "이름 고르기": "Pick name", "누가 쓰는 휴대폰인가요?": "Who is using this phone?",
    "신고함에 누가 가는지 · 누가 처리했는지 이름으로 남아요": "The inbox shows who is going and who handled it",
    "로그인 없이 이 휴대폰에만 저장돼요": "Saved on this phone only — no login", "로그인 없이 이 휴대폰에만": "Saved on this phone only — no login",
    "저장돼요": "", "다른 이름 직접 입력": "Type another name", "확인": "OK", "직원 이름": "Staff name", "이 휴대폰": "This phone",
    "아직 안 골랐어요": "Not picked yet", "고르기": "Pick", "바꾸기": "Change", "고르기 목록 (쉼표로 나눠요)": "Name list (comma-separated)",
    "신고함에서 누가 가는지 · 누가 처리했는지 이 이름으로 남아요": "This name shows in the inbox when you go or handle a request",
    "피팅룸 반납": "Fitting room returns", "제자리로 돌려놓을 옷": "Items to put back", "제자리": "Back to",
    "피팅룸에서 반납받은 옷 · 걸면서 아래에서 찍어요": "Returned at the fitting room · scan below as you hang them",
    "위치 없는 옷": "Items without a location", "안내할 위치가 아직 없어요 · 자주 찾는 옷부터": "No location to guide yet · most viewed first",
    "위치 없는 옷이 없어요.": "Every item has a location.", "찍어서 등록": "Scan to register",
    "반납받은 옷 태그를 찍어요": "Scan the tag of returned items",
    "위치는 그대로 두고, 손님 화면에 「피팅룸에 반납된 옷이 있어요」가 떠요. 옷을 제자리에 다시 걸 때": "The location stays the same, and shoppers see 'Some were returned to the fitting room'. When you hang it back, scan the shelf QR → item tag on the",
    "화면에서 선반 QR → 옷 태그를 찍으면 표시가 사라져요.": "screen and the notice disappears.",
    "직접 입력": "Manual entry", "반납": "Return", "스캔 없이 처리": "Done without scan", "방금 반납": "Just returned",
    "제자리에 걸 때": "When hanging it back, scan the shelf QR → item tag on the",
    "화면에서 선반 QR → 옷 태그를 찍으면 목록과 손님 화면 표시가 사라져요": "screen to clear it from this list and the shopper screen",
    "돌려놓을 옷이 없어요.": "Nothing to put back.", "위치 없음 · 등록 화면에서 찍어 주세요": "No location · scan it on the Register screen",
    "손님이 입어 보고 피팅룸에 두고 간 옷 · 위치는 그대로예요": "Tried on and left at the fitting room · location unchanged",
    "고칠 위치": "To fix", "위치만 보기": "Pins only", "동선 보기": "Show route", "한 번에 도는 길": "One-trip route",
    "아직 아무도 안 갔어요": "No one on it yet", "제가 갈게요": "I'll go", "제가 할게요": "I'll take it", "내가 처리 중": "You're on it",
    "처리 중": "on it", "내가": "You:", "손님 화면에도 떠요": "shown on the customer screen", "상품 삭제": "Item deleted", "위치 이동": "Moved",
    "약": "About", "가장 적게 걷는 순서예요 (아래 목록도 이 순서)": "Shortest walking order (the list below follows it)",
    "대형 매장은 바쁨 모드를 쓰지 않아요": "Large stores don't use busy mode",
    "피팅룸에 반납된 옷이 있어요": "Some were returned to the fitting room",
    "행거에 없으면 피팅룸 직원에게 물어보세요": "If it's not on the rack, ask the fitting room staff",
    "지금 손님이 많아 직원이 조금 늦을 수 있어요": "It's busy right now — staff may take a little longer",
    "지금 손님이 많아요": "It's busy right now", "직원이 조금 늦을 수 있어요 · 급하면 계산대에 말씀해 주세요": "Staff may be a little late · ask at the checkout if urgent",
    "삭제한 옷": "Deleted", "삭제한 옷이 없어요": "No deleted items", "되살리기": "Restore", "되돌리기": "Undo", "방금 삭제": "Just deleted",
    "삭제한 옷은 손님 화면 · 검색 · 키오스크에 나오지 않아요 · 되살리면 재고와 위치도 그대로 돌아와요": "Deleted items don't appear on shopper screens, search or the kiosk · restoring brings back stock and location",
    "손님 화면에서 빠져요": "removed from shopper screens", "이 옷 삭제": "Delete this item",
    "더 이상 팔지 않는 옷 · 잘못 등록한 옷 · 되살릴 수 있어요": "No longer sold · registered by mistake · can be restored",
    "이 옷을 삭제할까요? 손님 화면 · 검색 · 키오스크에서 빠져요. 옷 목록 「삭제한 옷」에서 되살릴 수 있어요.": "Delete this item? It will be removed from shopper screens, search and the kiosk. You can restore it from Items → Deleted.",
    "입어 보기만 하고 안 산 옷": "Tried on but not bought", "아직 없어요 · 피팅룸 반납을 찍으면 쌓여요": "None yet · builds up as you scan fitting room returns",
    "두 글자 이상 입력하면 아래에 나와요 · 누르면 바로 반납": "Type 2+ letters to see items · tap to return",
    "사이즈 요청": "Size request", "키오스크 앞": "at the kiosk", "직원이 위치 확인 중이에요": "Staff are checking this location", "보통이에요": "Fair",
})
PATTERNS[:0] = [
    _p(r"제자리로 돌려놓을 옷 (\d+)벌", lambda m, t: f"{m[1]} items to put back"),
    _p(r"손님이 '없어요'한 옷 (\d+)벌은 신고함에서 고쳐요", lambda m, t: f"{m[1]} items shoppers couldn't find are fixed in the inbox"),
    _p(r"(\d+)분 전 반납", lambda m, t: f"Returned {m[1]} min ago"),
    _p(r"고칠 선반 (\d+)곳", lambda m, t: f"{m[1]} shelves to fix"),
    _p(r"피팅룸 반납 (\d+)벌", lambda m, t: f"{m[1]} fitting room returns"),
    _p(r"기다리는 손님 (\d+)명", lambda m, t: f"{m[1]} customers waiting"),
    _p(r"손님 화면에 '직원이 조금 늦을 수 있어요'가 떠요", lambda m, t: "shoppers see 'Staff may take a little longer'"),
    _p(r"늘 바빠서 계산대 안내로 바꾸지 않고, 기다리는 손님이 (\d+)명 이상이면 손님 화면에 '직원이 조금 늦을 수 있어요'를 띄워요\.",
       lambda m, t: f"They're always busy, so instead of sending shoppers to the checkout, shoppers see 'Staff may take a little longer' when {m[1]}+ are waiting."),
    _p(r"(\d+)(분|시간|일) 전 삭제", lambda m, t: f"Deleted {m[1]} {dict(분='min', 시간='h', 일='d')[m[2]]} ago"),
    _p(r"(.+) \((.+)\) 삭제했어요", lambda m, t: f"Deleted {t(m[1])} ({t(m[2])})"),
    _p(r"(\S+) 되살렸어요", lambda m, t: f"Restored {m[1]}"),
    _p(r"(\S+) 가는 중", lambda m, t: f"{t(m[1])} is going"),
    _p(r"(\S+) 처리 중", lambda m, t: f"{t(m[1])} is on it"),
]
JS_SUBS.update({
    "두 글자 이상 입력하면 아래에 나와요 · 누르면 바로 반납": "Type 2+ letters to see items · tap to return", "<span>반납</span>": "<span>Return</span>",
    "찾지 못했어요": "Not found", "✓ 반납 받았어요": "✓ Return recorded", "방금 반납": "Just returned", "제자리 <em></em>": "Back to <em></em>",
    "<em class=\"no\">위치 없음 · 등록 화면에서 찍어 주세요</em>": "<em class=\"no\">No location · scan it on the Register screen</em>",
    "바코드를 다시 찍거나 아래 \\'직접 입력\\'에서 이름으로 찾아 주세요": "Scan again or search by name in \\'Manual entry\\' below",
    "선반 QR이에요": "That's a shelf QR", "피팅룸 반납은 옷 태그만 찍어요 · 제자리에 걸 때는 등록 화면에서 찍어 주세요": "Scan item tags only here · scan on the Register screen when hanging it back",
    "제자리 → ": "Back to → ", "위치 없음 · 등록 화면에서 찍어 주세요": "No location · scan it on the Register screen",
    "위치는 그대로 · 손님 화면에 피팅룸 반납 표시": "Location unchanged · fitting room notice on shopper screen",
    ").<br>아래 \\'직접 입력\\'을 눌러 주세요.": ").<br>Tap \\'Manual entry\\' below.", "벌": "",
})
JS_RAW.update({"' · 피팅룸 반납 표시 지움'": "' · fitting room notice cleared'", "'벌)'": "')'"})

# 2026.11.09 손님 피드백: 찾았어요 되돌리기 · 처음 화면 · 로그인 · 내 사이즈 · 지도 다운로드
PHRASES.update({
    "‘찾았어요!’를 누르면 정확도가 상승합니다!": "Tap 'Found it!' to improve accuracy!",
    "찾았어요! 위치 정확도에 반영했어요": "Found it! This helps keep locations accurate", "잘못 눌렀어요": "Tapped by mistake",
    "되돌리기": "Undo", "처음 화면으로": "Back to home", "다음부터 ‘찾았어요!’ 누르면 바로 처음 화면으로": "Next time, go straight home after 'Found it!'",
    "↩ 되돌리기": "↩ Undo", "찾았어요!": "Found it!", "되돌렸어요 · 다시 찾으면 눌러 주세요": "Undone · tap again when you find it",
    "되돌릴 수 없어요": "Can't undo", "되돌렸어요": "Undone",
    "로그인": "Log in", "회원가입": "Sign up", "로그아웃": "Log out", "가입하고 로그인": "Sign up & log in",
    "로그인하면 다른 휴대폰 · 다른 매장에서도 내 사이즈를 불러와요": "Log in to use your sizes on any phone, in any store",
    "아이디 하나로 내 사이즈를 저장해 두세요": "Save your sizes with one ID",
    "아이디": "ID", "영어 · 숫자 4~20자": "4–20 letters or numbers", "비밀번호": "Password", "8자 이상": "8+ characters",
    "비밀번호 확인": "Confirm password", "예) hansol01": "e.g. hansol01",
    "이 휴대폰에 적어 둔": "Your", "키 · 몸무게 · 내 사이즈": "height · weight · sizes",
    "가 있으면 그대로 계정에 옮겨져요. 비밀번호는 암호화해서 저장해요.": "saved on this phone move to your account. Passwords are stored encrypted.",
    "처음이세요?": "New here?", "이미 아이디가 있어요": "Already have an ID", "로그인하지 않아도 모든 기능을 쓸 수 있어요": "Every feature works without logging in",
    "아이디 또는 비밀번호가 맞지 않아요": "Wrong ID or password", "여러 번 틀려서 5분 동안 잠겼어요": "Too many tries — locked for 5 minutes",
    "아이디는 영어 · 숫자 · _ 로 4~20자예요": "IDs are 4–20 letters, numbers or _", "비밀번호는 8자 이상으로 해 주세요": "Use 8 or more characters",
    "비밀번호가 서로 달라요": "Passwords don't match", "이미 있는 아이디예요": "That ID is taken",
    "로그인됨 · 어느 휴대폰에서나 같은 정보를 불러와요": "Logged in · same info on any phone",
    "로그인하고 내 사이즈 저장": "Log in to save your sizes", "다른 휴대폰에서도 내 사이즈를 불러와요 · 안 해도 돼요": "Use your sizes on other phones · optional",
    "내 계정": "Your account", "에 저장돼요 · 다른 사람에게 보이지 않아요": "stores this · nobody else can see it",
    "로그인하지 않으면": "Without logging in, it's saved on", "내 사이즈": "My size", "추천 사이즈": "Suggested size",
    "알면 바로 골라 주세요": "pick if you know", "모름": "Not sure", "신발 · 발 사이즈": "Shoes · foot size", "선택": "optional",
    "사이즈를 모르면": "Don't know your size?", "키 · 몸무게로 추천해요": "we'll suggest one from height · weight", "성별 · 나이": "Gender · age",
    "설정": "Settings", "‘찾았어요!’ 누르면 처음 화면으로": "Go home after 'Found it!'",
    "옷을 찾고 나면 바로 첫 화면으로 돌아가요": "Return to the home screen once you find it", "키 · 몸무게를 같이 적어 주세요": "Please enter both height and weight",
    "내 사이즈 등록": "Add my size", "몸무게로 추천해요": "weight → suggested size", "이미 아이디가 있어요 ·": "Already have an ID? ·", "하고 바로 보기": "to see it right here", "지도 다운로드": "Download map",
})
PATTERNS.insert(0, _p(r"([A-Za-z0-9_]{4,20})님", lambda m, t: f"Hi, {m[1]}"))
JS_SUBS.update({"초 뒤 처음 화면으로 가요": " s until home", "\">내 사이즈</a>를 적으면 바로 보여 드려요": "\">Add your size</a> to see it here",
                "\">내 사이즈 등록</a>하고 바로 보기": "\">Add my size</a> to see it right here"})

# 설명으로 찾기 (음성 · 글자)
PHRASES.update({'예) "검정 후드티", "모자 달린 회색 옷"': 'e.g. "black hoodie", "gray top with a hood"',
                '예) "검정 후드티", "허리 고무줄 바지"': 'e.g. "black hoodie", "pants with an elastic waist"',
                "설명을 알아듣고 찾았어요": "Found from your description"})
