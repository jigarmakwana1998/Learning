import re
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash

from .config import get_settings

password_hash = PasswordHash.recommended()
_sensitive = re.compile(r"(?i)(api[_-]?key|authorization|password|token)\s*[:=]\s*[^\s,]+")


def hash_password(value: str) -> str: return password_hash.hash(value)
def verify_password(value: str, digest: str) -> bool: return password_hash.verify(value, digest)
def redact(value: str) -> str: return _sensitive.sub(r"\1=[REDACTED]", value)
def encrypt(value: str) -> str: return Fernet(get_settings().encryption_key.encode()).encrypt(redact(value).encode()).decode()
def decrypt(value: str) -> str: return Fernet(get_settings().encryption_key.encode()).decrypt(value.encode()).decode()


def create_access_token(user_id: str, role: str) -> str:
    payload = {"sub": user_id, "role": role, "exp": datetime.now(timezone.utc) + timedelta(hours=8)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
