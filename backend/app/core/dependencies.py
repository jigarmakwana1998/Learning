from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import supabase
from app.core.config import get_settings
from app.core.database import get_db
from app.models.database import User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> User:
    if credentials is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    response = await supabase.request("GET", "/auth/v1/user", access_token=credentials.credentials)
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Supabase access token")
    identity = response.json()
    subject, email = identity.get("id"), identity.get("email")
    if not subject or not email:
        raise HTTPException(status_code=401, detail="Supabase user is missing an email address")
    email = email.lower()
    role = "admin" if identity.get("app_metadata", {}).get("role") == "admin" else "learner"
    settings = get_settings()
    if role != "admin" and email == settings.admin_email and settings.supabase_secret_key:
        await supabase.grant_admin(subject)
        role = "admin"
    user = await db.scalar(select(User).where(or_(User.auth_subject == subject, User.email == email)))
    if user is None:
        user = User(auth_subject=subject, email=email, role=role)
        db.add(user)
    elif user.auth_subject != subject or user.email != email or user.role != role:
        user.auth_subject, user.email, user.role = subject, email, role
    await db.commit()
    await db.refresh(user)
    return user


async def get_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Admin access required")
    return user
