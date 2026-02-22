from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from backend.config import get_settings
import base64
import hashlib
import hmac
import json
import time

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        # Derive a key from secret_key if no explicit encryption key
        derived = hashlib.sha256(settings.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(derived).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(value: str) -> str:
    if not value:
        return ""
    f = _get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    if not encrypted:
        return ""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None


def sign_oauth_state(data: dict, ttl_seconds: int = 600) -> str:
    """Create an HMAC-signed, base64-encoded OAuth state token with expiry."""
    data = data.copy()
    data["exp"] = time.time() + ttl_seconds
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    sig = hmac.new(
        settings.secret_key.encode(), payload.encode(), hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode()
    return f"{payload}.{sig_b64}"


def verify_oauth_state(token: str) -> Optional[dict]:
    """Verify an HMAC-signed OAuth state token. Returns payload or None."""
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    payload_b64, sig_b64 = parts
    expected_sig = hmac.new(
        settings.secret_key.encode(), payload_b64.encode(), hashlib.sha256
    ).digest()
    try:
        actual_sig = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    except Exception:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data
