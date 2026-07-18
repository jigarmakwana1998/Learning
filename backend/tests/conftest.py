import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/learning_coach_test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-with-at-least-32-characters")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPass123!")
