from collections.abc import Callable

import jwt
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
    try: payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as error: raise HTTPException(status_code=401, detail="Invalid access token") from error
    user = await db.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None: raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def get_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Admin access required")
    return user
