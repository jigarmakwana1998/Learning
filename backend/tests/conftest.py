import os
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

test_database = Path(tempfile.gettempdir()) / "learning_coach_test.db"
test_database.unlink(missing_ok=True)  # create_all never migrates a stale schema

# Captured before the fake values below replace them; the live contract tests
# in test_supabase_live.py run against this real project.
_dotenv = dotenv_values(Path(__file__).parents[1] / ".env")
LIVE_SUPABASE = {
    key: (os.getenv(key) or _dotenv.get(key) or "").strip().strip('"') or None
    for key in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")
}

# Always isolate tests from a developer's configured PostgreSQL database.  Building
# this URL from the platform temp directory keeps the suite portable to Windows.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_database.as_posix()}"
os.environ["SUPABASE_URL"] = "https://supabase.test"
os.environ["SUPABASE_PUBLISHABLE_KEY"] = "sb_publishable_test"
os.environ["SUPABASE_SECRET_KEY"] = "sb_secret_test"
os.environ["ADMIN_EMAIL"] = "owner@example.com"
os.environ.setdefault("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["AGENT_CHECKPOINT_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


class FakeSupabaseAuth:
    def __init__(self):
        self.require_email_confirmation = False
        self.users = {
            "admin@example.com": {
                "id": "00000000-0000-0000-0000-000000000001",
                "email": "admin@example.com",
                "password": "AdminPass123!",
                "app_metadata": {"role": "admin"},
            }
        }
        self.tokens: dict[str, dict] = {}

    def response(self, method: str, path: str, status_code: int, body: dict) -> httpx.Response:
        return httpx.Response(
            status_code,
            json=body,
            request=httpx.Request(method, f"https://supabase.test{path}"),
        )

    def session(self, user: dict) -> dict:
        token = f"test-token-{user['id']}"
        self.tokens[token] = user
        return {"access_token": token, "user": self.public_user(user)}

    @staticmethod
    def public_user(user: dict) -> dict:
        return {key: user[key] for key in ("id", "email", "app_metadata")}

    async def request(
        self,
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        api_key: str | None = None,
        json: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        payload = json or {}
        email = str(payload.get("email", "")).lower()
        if method == "POST" and path == "/auth/v1/signup":
            if email in self.users:
                return self.response(method, path, 400, {"msg": "User already registered"})
            user = {
                "id": str(uuid4()),
                "email": email,
                "password": payload.get("password"),
                "app_metadata": {},
            }
            self.users[email] = user
            body = {"access_token": None, "user": self.public_user(user)} if self.require_email_confirmation else self.session(user)
            return self.response(method, path, 200, body)
        if method == "POST" and path == "/auth/v1/token" and params == {"grant_type": "password"}:
            user = self.users.get(email)
            if user is None or user["password"] != payload.get("password"):
                return self.response(method, path, 400, {"msg": "Invalid login credentials"})
            return self.response(method, path, 200, self.session(user))
        if method == "PUT" and path.startswith("/auth/v1/admin/users/"):
            user = next(u for u in self.users.values() if u["id"] == path.rsplit("/", 1)[1])
            user["app_metadata"] = payload["app_metadata"]
            return self.response(method, path, 200, self.public_user(user))
        if method == "GET" and path == "/auth/v1/user":
            user = self.tokens.get(access_token or "")
            return self.response(method, path, 200, self.public_user(user)) if user else self.response(method, path, 401, {"msg": "Invalid token"})
        raise AssertionError(f"Unexpected Supabase request: {method} {path}")


@pytest.fixture
def live_supabase_credentials() -> dict[str, str | None]:
    # A fixture, not an import: re-importing conftest would capture the fake values.
    return LIVE_SUPABASE


@pytest.fixture(autouse=True)
def fake_supabase(monkeypatch):
    from app.core import supabase

    service = FakeSupabaseAuth()
    monkeypatch.setattr(supabase, "request", service.request)
    return service
