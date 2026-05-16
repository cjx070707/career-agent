from datetime import datetime, timedelta, timezone
from typing import Optional

import hashlib
import hmac
import os

from jose import JWTError, jwt

from app.db.session import get_connection

SECRET_KEY = "careerhub-demo-secret-2026"
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"{salt}${h.hex()}"


def _verify_password(plain: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        expected = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 260000)
        return hmac.compare_digest(expected.hex(), h)
    except Exception:
        return False


def _create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    """Return username if token is valid, else None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


class AuthService:
    def register(self, username: str, password: str) -> str:
        """Create user and return JWT. Raises ValueError if username taken."""
        username = username.strip()
        if not username or not password:
            raise ValueError("用户名和密码不能为空")
        if len(username) < 2:
            raise ValueError("用户名至少 2 个字符")

        password_hash = _hash_password(password)
        now = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                raise ValueError("用户名已被使用，请换一个")
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, now),
            )
        return _create_token(username)

    def login(self, username: str, password: str) -> str:
        """Verify credentials and return JWT. Raises ValueError on failure."""
        username = username.strip()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise ValueError("用户名或密码错误")
        return _create_token(username)
