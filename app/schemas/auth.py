"""인증 (명세 SignupRequest, LoginRequest, AuthTokens, /auth/refresh, /auth/password-reset)."""

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import OnboardingStep


class SignupRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=1)
    nickname: str = Field(min_length=1, max_length=50)
    agree_terms: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class AuthUser(BaseModel):
    id: int
    nickname: str
    onboarding_step: OnboardingStep


class TokenPair(BaseModel):
    """/auth/refresh 응답."""

    access_token: str
    refresh_token: str


class AuthTokens(TokenPair):
    """signup·login 응답."""

    user: AuthUser
