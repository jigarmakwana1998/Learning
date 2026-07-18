import os
import tempfile
from pathlib import Path

test_database = Path(tempfile.gettempdir()) / "learning_coach_test.db"

# Always isolate tests from a developer's configured PostgreSQL database.  Building
# this URL from the platform temp directory keeps the suite portable to Windows.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_database.as_posix()}"
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-32-characters")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPass123!")
