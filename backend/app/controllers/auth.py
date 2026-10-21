from typing import NoReturn

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core import supabase
from app.core.dependencies import get_current_user
from learning_db.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest) -> TokenResponse:
    response = await supabase.request("POST", "/auth/v1/signup", json=_credentials(payload))
    if not response.is_success:
        _raise_auth_error(response, 400, "Registration failed")
    return _token_response(response)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    response = await supabase.request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "password"},
        json=_credentials(payload),
    )
    if not response.is_success:
        _raise_auth_error(response, 401, "Invalid email or password")
    return _token_response(response)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


def _credentials(payload: RegisterRequest) -> dict[str, str]:
    return {"email": payload.email.lower(), "password": payload.password}


def _token_response(response: httpx.Response) -> TokenResponse:
    data = response.json()
    user = data.get("user") or {}
    role = "admin" if user.get("app_metadata", {}).get("role") == "admin" else "learner"
    token = data.get("access_token")
    return TokenResponse(
        access_token=token,
        role=role,
        message=None if token else "Check your inbox to confirm your email, then sign in.",
    )


def _raise_auth_error(response: httpx.Response, status_code: int, fallback: str) -> NoReturn:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("msg") or body.get("message") or body.get("error_description") or fallback
    raise HTTPException(status_code=status_code, detail=detail)
