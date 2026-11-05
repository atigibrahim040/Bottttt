import base64, os
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

def get_password():
    p = os.getenv("SESSION_PASSWORD", "").strip()
    if not p: raise RuntimeError("SESSION_PASSWORD required")
    return p

def encrypt(plaintext, password):
    salt = get_random_bytes(16)
    key = PBKDF2(password, salt, dkLen=32, count=390000, hmac_hash_module=SHA256)
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
    return base64.b64encode(salt + nonce + tag + ct).decode('ascii')

def decrypt(enc_b64, password):
    raw = base64.b64decode(enc_b64)
    salt, nonce, tag, ct = raw[:16], raw[16:28], raw[28:44], raw[44:]
    key = PBKDF2(password, salt, dkLen=32, count=390000, hmac_hash_module=SHA256)
    return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode('utf-8')
