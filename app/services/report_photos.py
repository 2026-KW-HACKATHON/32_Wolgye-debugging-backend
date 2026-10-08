"""미등록 차량 제보 사진 (#52): 검사 → EXIF 제거·축소 → 파일 저장.

- JPEG·PNG 만 받는다 (확장자·Content-Type 이 아니라 실제 내용으로 판단). HEIC 는 FE 가 JPEG 로 바꿔 보낸다
- 회전(EXIF Orientation)만 픽셀에 반영하고 EXIF(위치정보 등)는 모두 버린다. 긴 변 1600px 이하 JPEG 로 다시 저장
- 파일 이름은 UUID. 저장 위치는 설정 REPORT_PHOTO_DIR (운영은 docker 볼륨). DB 에는 파일 이름(photo_key)만 둔다
"""

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.services.exceptions import InvalidInputError

MAX_SIDE = 1600
JPEG_QUALITY = 85
ACCEPTED_FORMATS = {"JPEG", "PNG"}
MEDIA_TYPE = "image/jpeg"


def _invalid(reason: str) -> InvalidInputError:
    return InvalidInputError("사진을 다시 찍어 주세요.", detail={"field": "photo", "reason": reason})


def process(data: bytes) -> bytes:
    """올린 사진 → 저장할 JPEG. 이미지가 아니거나 너무 크면 400 INVALID_INPUT. CPU 작업이라 스레드에서 부른다."""
    max_bytes = get_settings().report_photo_max_bytes
    if not data:
        raise _invalid("사진 파일이 비어 있습니다.")
    if len(data) > max_bytes:
        raise _invalid(f"사진은 {max_bytes // (1024 * 1024)}MB 이하여야 합니다.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ACCEPTED_FORMATS:
                raise _invalid("JPEG 또는 PNG 사진만 올릴 수 있습니다.")
            image.load()
            upright = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError) as exc:
        raise _invalid("이미지 파일이 아닙니다.") from exc
    upright.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    upright.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)  # exif 를 넘기지 않으므로 메타데이터 없음
    return out.getvalue()


def _dir() -> Path:
    return Path(get_settings().report_photo_dir)


def path_of(key: str) -> Path:
    """photo_key → 파일 경로. key 는 서버가 만든 UUID 이름이라 경로 조작 걱정은 없지만 이름만 쓴다."""
    return _dir() / Path(key).name


def save(jpeg: bytes) -> str:
    """파일로 저장하고 photo_key 를 돌려준다."""
    directory = _dir()
    directory.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}.jpg"
    (directory / key).write_bytes(jpeg)
    return key


def delete(key: str) -> None:
    """저장한 사진을 지운다 (DB 저장 실패 시 정리). 없으면 무시."""
    path_of(key).unlink(missing_ok=True)
