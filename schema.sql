CREATE TABLE fixtures (          -- 집기(선반). QR이 붙는 고정 지점
  id TEXT PRIMARY KEY, zone TEXT, name TEXT, kind TEXT,
  x INT, y INT, w INT, h INT);
CREATE TABLE zones (id TEXT PRIMARY KEY, name TEXT, x INT, y INT, w INT, h INT, color TEXT, lx INT, ly INT);  -- 매장 구역 (도면 바탕)
CREATE TABLE nodes  (id TEXT PRIMARY KEY, x INT, y INT);   -- 길찾기용 점
CREATE TABLE edges  (a TEXT, b TEXT);                      -- 점과 점 사이 길
CREATE TABLE items  (                                      -- 상품 카탈로그(SKU)
  sku TEXT PRIMARY KEY, name TEXT, category TEXT, subcat TEXT,
  color TEXT, hex TEXT, fit TEXT, price INT, image TEXT);
CREATE TABLE stock  (sku TEXT, size TEXT, qty INT, wh INT DEFAULT 0);   -- qty=매장 진열, wh=창고
CREATE TABLE placements (                                  -- 위치 기록(계속 바뀜)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT, fixture_id TEXT, level TEXT,
  updated_at TEXT, updated_by TEXT, active INT DEFAULT 1,
  confirmed_at TEXT);                                      -- 손님이 '찾았어요' 누른 시각
CREATE TABLE reports (                       -- none=위치에 없음 / size=사이즈 요청 / call=직원 호출
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT, fixture_id TEXT, kind TEXT, created_at TEXT, done INT DEFAULT 0,
  detail TEXT, size TEXT, device TEXT,
  wait_state TEXT DEFAULT '', wait_at TEXT, served_at TEXT,   -- 손님 대기: waiting/going/served/nostock/expired
  resolution TEXT, resolved_at TEXT);                         -- 위치 신고 처리 결과

CREATE TABLE barcodes (code TEXT PRIMARY KEY, sku TEXT, season TEXT);  -- 시즌마다 다른 바코드 → 같은 상품
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);             -- 매장 유형·직원 수·키오스크·바쁨 모드·진열 점검일
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, sku TEXT, src TEXT, ts TEXT);  -- 사용률 지표
