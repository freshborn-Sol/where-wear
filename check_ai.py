# -*- coding: utf-8 -*-
"""AI(Gemini) 연결 점검.  실행: python check_ai.py
키 내용은 화면에 앞 4글자만 보여준다."""
import json, os, urllib.error, urllib.request
import vision as V

k = V.api_key()
src = "gemini_key.txt" if (V.BASE / "gemini_key.txt").exists() and V._ok_key((V.BASE / "gemini_key.txt").read_text(encoding="utf-8").strip()) else "환경변수 GEMINI_API_KEY"
print(f"1) 키: {'없음' if not k else k[:4] + '…(' + str(len(k)) + '자)'}  ← {src}")
print(f"2) 모델: {V.MODEL}")
if not k:
    raise SystemExit("→ 키가 없어요. gemini_key.txt 를 확인하세요.")

body = {"contents": [{"parts": [{"text": "OK 라고만 답해"}]}]}
req = urllib.request.Request(V.ENDPOINT.format(m=V.MODEL), data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json", "x-goog-api-key": k})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    print("3) 성공! AI 답:", d["candidates"][0]["content"]["parts"][0].get("text", "").strip())
except urllib.error.HTTPError as e:
    msg = e.read().decode(errors="ignore").replace(k, "***")
    try:
        msg = json.loads(msg)["error"]["message"]
    except Exception:
        pass
    print(f"3) 실패: HTTP {e.code}\n   구글 메시지: {msg[:400]}")
except Exception as e:
    print("3) 연결 실패:", type(e).__name__, str(e)[:200])
