import pytest

from app.core.error_codes import ErrorCode
from app.models.resident import ResidentRole
from app.schemas.user import OnboardingStep, ProfileUpdate
from app.services import users
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import make_building, make_resident, make_vehicle

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("phone", "masked"),
    [
        ("010-1234-5678", "010-****-5678"),
        ("01012345678", "010-****-5678"),
        ("010 123 4567", "010-****-4567"),
        ("1234", "****"),
        (None, None),
    ],
)
def test_mask_phone(phone, masked):
    assert users.mask_phone(phone) == masked


async def test_onboarding_step(db):
    user = await make_resident(db)
    assert await users.onboarding_step(db, user) == OnboardingStep.JOIN_BUILDING

    building = await make_building(db)
    user.building_id = building.id
    await db.commit()
    assert await users.onboarding_step(db, user) == OnboardingStep.REGISTER_VEHICLE

    await make_vehicle(db, owner=user)
    assert await users.onboarding_step(db, user) == OnboardingStep.DONE


async def test_vehicle_without_building_is_still_join_building(db):
    user = await make_resident(db)
    await make_vehicle(db, owner=user)
    assert await users.onboarding_step(db, user) == OnboardingStep.JOIN_BUILDING


async def test_get_me_with_building(db):
    building = await make_building(db)
    user = await make_resident(db, building=building, role=ResidentRole.MANAGER, token_balance=30)
    me = await users.get_me(db, user)
    assert me.building.building_id == building.id
    assert me.building.alley.name == "광운로19가길"
    assert me.building.role == "ADMIN"
    assert me.token_balance == 30
    assert me.temperature == 36.5


async def test_update_me_only_sent_fields(db):
    user = await make_resident(db)
    await users.update_me(db, user, ProfileUpdate(name="김지수", unit="101동 202호", phone="010-1234-5678"))
    me = await users.update_me(db, user, ProfileUpdate(name="지수"))

    assert (user.name, user.unit_no, user.phone) == ("지수", "101동 202호", "010-1234-5678")
    assert me.phone == "010-****-5678"


async def test_join_building(db):
    building = await make_building(db, invite_code="HANBIT01")
    user = await make_resident(db)
    result = await users.join_building(db, user, "HANBIT01")
    assert user.building_id == building.id
    assert result.role == "RESIDENT"
    assert result.onboarding_step == OnboardingStep.REGISTER_VEHICLE


async def test_join_building_invalid_code(db):
    user = await make_resident(db)
    with pytest.raises(NotFoundError) as exc:
        await users.join_building(db, user, "NOPE")
    assert exc.value.code == ErrorCode.INVALID_INVITE_CODE


@pytest.mark.parametrize("same_building", [True, False])
async def test_join_building_already_member(db, same_building):
    mine = await make_building(db, invite_code="MINE01")
    other = mine if same_building else await make_building(db, invite_code="OTHER1", name="다른빌라")
    user = await make_resident(db, building=mine)
    with pytest.raises(ConflictError) as exc:
        await users.join_building(db, user, other.invite_code)
    assert exc.value.code == ErrorCode.ALREADY_IN_BUILDING
    assert exc.value.detail == {"building_id": mine.id}
