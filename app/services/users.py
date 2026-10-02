"""내 정보·빌라 합류 (#6). onboarding_step 계산(결정 9)과 phone 마스킹도 여기에 둔다."""

import re

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enum_maps import role_to_api
from app.core.error_codes import ErrorCode
from app.models.alley import Alley
from app.models.building import Building
from app.models.resident import Resident
from app.models.vehicle import Vehicle
from app.schemas.user import (
    AlleyRef,
    JoinBuildingResult,
    MyBuilding,
    OnboardingStep,
    ProfileUpdate,
    UserMe,
)
from app.services.exceptions import ConflictError, NotFoundError

# ProfileUpdate 필드 → residents 컬럼
_PROFILE_COLUMNS = {"name": "name", "unit": "unit_no", "phone": "phone"}


async def onboarding_step(db: AsyncSession, resident: Resident) -> OnboardingStep:
    """빌라 없음 → JOIN_BUILDING, 내 차량 없음 → REGISTER_VEHICLE, 둘 다 있음 → DONE (결정 9)."""
    if resident.building_id is None:
        return OnboardingStep.JOIN_BUILDING
    has_vehicle = await db.scalar(select(exists().where(Vehicle.owner_id == resident.id)))
    return OnboardingStep.DONE if has_vehicle else OnboardingStep.REGISTER_VEHICLE


def mask_phone(phone: str | None) -> str | None:
    """숫자만 뽑아 `앞3-****-뒤4` (예: 010-****-5678). 8자리 미만이면 전부 `*`."""
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 8:
        return "*" * len(digits)
    return f"{digits[:3]}-****-{digits[-4:]}"


async def _building_with_alley(db: AsyncSession, building_id: int) -> tuple[Building, Alley]:
    row = (
        await db.execute(
            select(Building, Alley).join(Alley, Building.alley_id == Alley.id).where(Building.id == building_id)
        )
    ).one()
    return row[0], row[1]


async def get_me(db: AsyncSession, user: Resident) -> UserMe:
    building = None
    if user.building_id is not None:
        b, alley = await _building_with_alley(db, user.building_id)
        building = MyBuilding(
            building_id=b.id,
            name=b.name,
            alley=AlleyRef.model_validate(alley),
            role=role_to_api(user.role),
            unit=user.unit_no,
        )
    return UserMe(
        id=user.id,
        email=user.email,
        nickname=user.nickname,
        name=user.name,
        phone=mask_phone(user.phone),
        temperature=user.manner_temperature,
        token_balance=user.token_balance,
        onboarding_step=await onboarding_step(db, user),
        building=building,
    )


async def update_me(db: AsyncSession, user: Resident, payload: ProfileUpdate) -> UserMe:
    """보낸 필드만 바꾼다 (unit → residents.unit_no)."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, _PROFILE_COLUMNS[field], value)
    await db.commit()
    await db.refresh(user)
    return await get_me(db, user)


async def join_building(db: AsyncSession, user: Resident, invite_code: str) -> JoinBuildingResult:
    """초대코드(대소문자 무시)로 빌라에 합류. 이미 소속이면(같은 빌라 포함) 409 ALREADY_IN_BUILDING, 코드가 없으면 404 INVALID_INVITE_CODE."""
    if user.building_id is not None:
        raise ConflictError(
            "이미 빌라에 소속되어 있습니다.",
            code=ErrorCode.ALREADY_IN_BUILDING,
            detail={"building_id": user.building_id},
        )
    # 초대코드는 앞뒤 공백을 지우고 대소문자 구분 없이 비교한다 (대문자로 정규화)
    code = invite_code.strip().upper()
    building = await db.scalar(select(Building).where(func.upper(Building.invite_code) == code))
    if building is None:
        raise NotFoundError("초대코드가 올바르지 않습니다.", code=ErrorCode.INVALID_INVITE_CODE)

    user.building_id = building.id
    await db.commit()
    await db.refresh(user)

    _, alley = await _building_with_alley(db, building.id)
    return JoinBuildingResult(
        building_id=building.id,
        name=building.name,
        address=building.address,
        alley=AlleyRef.model_validate(alley),
        role=role_to_api(user.role),
        onboarding_step=await onboarding_step(db, user),
    )
