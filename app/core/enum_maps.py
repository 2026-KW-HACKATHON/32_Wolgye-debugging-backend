"""명세 enum ↔ DB enum 변환 (명세 열린 질문 16, CLAUDE.md "주의할 점").

DB enum 의 값은 소문자("pending"), 이름은 대문자("PENDING")이고 명세는 대문자를 쓴다.
- 이름이 같은 것 (MoveRequestStatus, NotificationType, GarageType ↔ ZoneType): api_name / from_api_name
- 이름이 다른 것: 아래 전용 enum 과 함수
    역할       명세 ADMIN    ↔ DB ResidentRole.MANAGER   (RESIDENT ↔ RESIDENT)
    공유 요청  명세 APPROVED ↔ DB ShareRequestStatus.ACCEPTED (PENDING, REJECTED 는 같음)
- 필드 이름만 다른 것(is_default ↔ is_primary, alias ↔ nickname)은 각 스키마에서 Field(validation_alias=...) 등으로 바꾼다.
"""

import enum

from app.models.resident import ResidentRole
from app.models.share_request import ShareRequestStatus


def api_name(member: enum.Enum) -> str:
    """DB enum 멤버 → 명세 문자열 (이름이 같은 enum 용). MoveRequestStatus.MOVED → "MOVED"."""
    return member.name


def from_api_name[E: enum.Enum](enum_cls: type[E], name: str) -> E:
    """명세 문자열 → DB enum 멤버 (이름이 같은 enum 용). 없는 이름이면 ValueError."""
    try:
        return enum_cls[name]
    except KeyError:
        raise ValueError(f"{name!r} is not a valid {enum_cls.__name__}") from None


# ── 역할 ──
class BuildingRole(enum.StrEnum):
    """명세 BuildingRole."""

    RESIDENT = "RESIDENT"
    ADMIN = "ADMIN"


_ROLE_TO_API = {ResidentRole.RESIDENT: BuildingRole.RESIDENT, ResidentRole.MANAGER: BuildingRole.ADMIN}
_ROLE_FROM_API = {v: k for k, v in _ROLE_TO_API.items()}


def role_to_api(role: ResidentRole) -> BuildingRole:
    return _ROLE_TO_API[role]


def role_from_api(role: BuildingRole | str) -> ResidentRole:
    return _ROLE_FROM_API[BuildingRole(role)]


# ── 공유 요청 상태 ──
class ApiShareRequestStatus(enum.StrEnum):
    """명세 ShareRequestStatus."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


_SHARE_TO_API = {
    ShareRequestStatus.PENDING: ApiShareRequestStatus.PENDING,
    ShareRequestStatus.ACCEPTED: ApiShareRequestStatus.APPROVED,
    ShareRequestStatus.REJECTED: ApiShareRequestStatus.REJECTED,
}
_SHARE_FROM_API = {v: k for k, v in _SHARE_TO_API.items()}


def share_status_to_api(status: ShareRequestStatus) -> ApiShareRequestStatus:
    return _SHARE_TO_API[status]


def share_status_from_api(status: ApiShareRequestStatus | str) -> ShareRequestStatus:
    return _SHARE_FROM_API[ApiShareRequestStatus(status)]
