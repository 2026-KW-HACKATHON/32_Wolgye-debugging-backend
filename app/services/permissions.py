"""빌라 권한 확인. 경로에 building_id 가 없는 리소스(칸·공유 요청 등)는 서비스가 대상의 빌라를 찾은 뒤 이 함수를 부른다.
경로에 building_id 가 있으면 app/api/deps.py 의 BuildingMember / BuildingAdmin 의존성을 쓴다."""

from app.core.error_codes import ErrorCode
from app.models.resident import Resident, ResidentRole
from app.services.exceptions import ForbiddenError

NOT_MEMBER_MESSAGE = "이 빌라의 입주민만 이용할 수 있습니다."
NOT_ADMIN_MESSAGE = "이 빌라의 관리인만 이용할 수 있습니다."


def ensure_building_member(resident: Resident, building_id: int) -> None:
    """resident 가 building_id 빌라 소속(입주민·관리인 모두)이 아니면 403 NOT_BUILDING_MEMBER."""
    if resident.building_id is None or resident.building_id != building_id:
        raise ForbiddenError(NOT_MEMBER_MESSAGE, code=ErrorCode.NOT_BUILDING_MEMBER)


def ensure_building_admin(resident: Resident, building_id: int) -> None:
    """resident 가 building_id 빌라의 관리인(role = MANAGER)이 아니면 403 NOT_BUILDING_ADMIN."""
    if resident.role != ResidentRole.MANAGER or resident.building_id != building_id:
        raise ForbiddenError(NOT_ADMIN_MESSAGE, code=ErrorCode.NOT_BUILDING_ADMIN)
