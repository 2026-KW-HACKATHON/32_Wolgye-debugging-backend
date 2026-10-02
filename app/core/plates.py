"""번호판 정규화 (명세 공통 규칙: 응답은 `12가 3456`, 요청은 공백 유무 모두 허용).

DB(vehicles.plate_no)에는 공백을 모두 뺀 값을 저장한다 → 같은 번호판이 띄어쓰기만 달라 중복 등록되지 않는다.
"""

import re

# 공백을 뺀 번호판 형식 (#7): 숫자 2~3자리 + 한글 1자 + 숫자 4자리 ("12가3456", "123가4567")
PLATE_PATTERN = re.compile(r"^(\d{2,3}[가-힣])(\d{4})$")


def normalize_plate(plate: str) -> str:
    """저장·검색용. 모든 공백을 지운다. "12가 3456" → "12가3456"."""
    return "".join(plate.split())


def format_plate(plate: str) -> str:
    """응답용. 마지막 숫자 4자리 앞에 공백 하나. "12가3456" → "12가 3456". 형식이 다르면 공백만 지워서 돌려준다."""
    normalized = normalize_plate(plate)
    match = PLATE_PATTERN.match(normalized)
    return f"{match.group(1)} {match.group(2)}" if match else normalized


def is_valid_plate(plate: str) -> bool:
    """공백을 뺀 값이 PLATE_PATTERN 에 맞는지."""
    return PLATE_PATTERN.match(normalize_plate(plate)) is not None
