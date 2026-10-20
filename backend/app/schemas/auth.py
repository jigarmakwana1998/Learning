from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(RegisterRequest):
    pass


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    role: str
    message: str | None = None


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    model_config = {"from_attributes": True}
