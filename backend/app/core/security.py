import re

from cryptography.fernet import Fernet

from .config import get_settings

_sensitive = re.compile(r"(?i)(api[_-]?key|authorization|password|token)\s*[:=]\s*[^\s,]+")


def redact(value: str) -> str: return _sensitive.sub(r"\1=[REDACTED]", value)
def encrypt(value: str) -> str: return Fernet(get_settings().encryption_key.encode()).encrypt(redact(value).encode()).decode()
def decrypt(value: str) -> str: return Fernet(get_settings().encryption_key.encode()).decrypt(value.encode()).decode()
