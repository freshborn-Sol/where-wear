# -*- coding: utf-8 -*-
"""직원 휴대폰 잠금화면 알림 (Web Push) — 외부 서비스 가입 없이 표준 방식으로 보낸다.

- 알림 보내는 열쇠(VAPID)는 처음 실행할 때 vapid.json 으로 자동으로 만들어진다 (깃허브에 올리지 않음)
- 휴대폰은 https 주소(공유링크켜기.command 의 trycloudflare 주소)로 접속해야 알림을 켤 수 있다
  · 안드로이드 크롬: 바로 가능
  · 아이폰: 사파리에서 '홈 화면에 추가' 후 그 아이콘으로 열어야 가능 (iOS 16.4+)
- 표준: RFC 8291 (aes128gcm 암호화) · RFC 8292 (VAPID)
필요한 패키지: cryptography
"""
import base64, json, os, struct, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEYFILE = Path(__file__).parent / "vapid.json"
CONTACT = "mailto:wherewear@example.com"

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64d(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def _raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

_KEY = None
def vapid():
    """(개인키, 공개키 base64url). 없으면 만들어 vapid.json 에 저장"""
    global _KEY
    if _KEY: return _KEY
    if KEYFILE.exists():
        d = json.loads(KEYFILE.read_text())
        priv = serialization.load_pem_private_key(d["private_pem"].encode(), None)
    else:
        priv = ec.generate_private_key(ec.SECP256R1())
        pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        KEYFILE.write_text(json.dumps({"private_pem": pem, "public": b64u(_raw_pub(priv))}))
    _KEY = (priv, b64u(_raw_pub(priv)))
    return _KEY

def _hmac(key, data):
    h = hmac.HMAC(key, hashes.SHA256()); h.update(data); return h.finalize()

def encrypt(payload: bytes, p256dh: str, auth: str, salt=None, as_priv=None):
    """RFC 8291: 받는 기기의 공개키(p256dh)·auth 로 aes128gcm 본문을 만든다"""
    ua_pub = b64d(p256dh); auth_b = b64d(auth)
    as_priv = as_priv or ec.generate_private_key(ec.SECP256R1())
    as_pub = _raw_pub(as_priv)
    shared = as_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    prk_key = _hmac(auth_b, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")[:32]
    salt = salt or os.urandom(16)
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub)) + as_pub + body

def _jwt(aud):
    priv, pub = vapid()
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": CONTACT}).encode())
    r, s = decode_dss_signature(priv.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}", pub

def send(sub: dict, data: dict, ttl=300):
    """구독 1건에 알림 보내기. 돌려주는 값: 상태코드 (201 성공, 404/410 은 더 이상 없는 구독)"""
    u = urlparse(sub["endpoint"])
    token, pub = _jwt(f"{u.scheme}://{u.netloc}")
    body = encrypt(json.dumps(data, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Authorization": f"vapid t={token}, k={pub}", "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream", "TTL": str(ttl), "Urgency": "high"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0
