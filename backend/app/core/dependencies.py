from collections.abc import Callable

import jwt
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.database import User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> User:
    if credentials is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    settings = get_settings()
    if settings.supabase_url and settings.supabase_publishable_key:
        async with httpx.AsyncClient(base_url=settings.supabase_url, timeout=10) as client:
            response = await client.get(
                "/auth/v1/user",
                headers={"Authorization": f"Bearer {credentials.credentials}", "apikey": settings.supabase_publishable_key},
            )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Supabase access token")
        identity = response.json()
        user_id, email = identity.get("id"), identity.get("email")
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Supabase user is missing an email address")
        user = await db.scalar(select(User).where(User.id == user_id))
        if user is None:
            user = User(id=user_id, email=email.lower(), password_hash="supabase-managed", role="admin" if email.lower() == settings.admin_email.lower() else "learner")
            db.add(user); await db.commit(); await db.refresh(user)
        return user
    try: payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as error: raise HTTPException(status_code=401, detail="Invalid access token") from error
    user = await db.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None: raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def get_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Admin access required")
    return user
