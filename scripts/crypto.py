"""AES-GCM + PBKDF2 encryption. Password comes from SESSION_PASSWORD env var."""
import base64
import os
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

PBKDF2_ITER = 390_000


def get_password() -> str:
    pwd = os.getenv("SESSION_PASSWORD", "").strip()
    if not pwd:
        raise RuntimeError("SESSION_PASSWORD env var required")
    return pwd


def encrypt(plaintext: str, password: str) -> str:
    salt = get_random_bytes(16)
    key = PBKDF2(password, salt, dkLen=32, count=PBKDF2_ITER, hmac_hash_module=SHA256)
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    return base64.b64encode(salt + nonce + tag + ct).decode("ascii")


def decrypt(enc_b64: str, password: str) -> str:
    raw = base64.b64decode(enc_b64)
    salt, nonce, tag, ct = raw[:16], raw[16:28], raw[28:44], raw[44:]
    key = PBKDF2(password, salt, dkLen=32, count=PBKDF2_ITER, hmac_hash_module=SHA256)
    pt = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag)
    return pt.decode("utf-8")
