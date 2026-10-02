"""내 정보·빌라 합류 (명세 UserMe, ProfileUpdate, POST /buildings/join)."""

import enum

from pydantic import BaseModel, ConfigDict, Field

from app.core.enum_maps import BuildingRole


class OnboardingStep(enum.StrEnum):
    """명세 OnboardingStep. 컬럼 없이 계산한다 (결정 9, app/services/users.onboarding_step)."""

    JOIN_BUILDING = "JOIN_BUILDING"
    REGISTER_VEHICLE = "REGISTER_VEHICLE"
    DONE = "DONE"


class AlleyRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class MyBuilding(BaseModel):
    building_id: int
    name: str
    alley: AlleyRef
    role: BuildingRole
    unit: str | None


class UserMe(BaseModel):
    id: int
    email: str
    nickname: str
    name: str | None
    phone: str | None = Field(description="본인에게도 마스킹 (010-****-5678)")
    temperature: float
    token_balance: int
    onboarding_step: OnboardingStep
    building: MyBuilding | None


class ProfileUpdate(BaseModel):
    """보낸 필드만 바꾼다. null 을 보내면 비운다."""

    name: str | None = Field(default=None, max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)


class JoinBuildingRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=12)


class JoinBuildingResult(BaseModel):
    building_id: int
    name: str
    address: str
    alley: AlleyRef
    role: BuildingRole
    onboarding_step: OnboardingStep
