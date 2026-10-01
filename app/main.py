from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db_errors import integrity_error_message
from app.services.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# 도메인 예외 → HTTP 상태 코드. 응답 본문은 HTTPException 과 같은 {"detail": ...} 형태.
DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ForbiddenError: 403,
    ConflictError: 409,
}


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = next((code for cls, code in DOMAIN_ERROR_STATUS.items() if isinstance(exc, cls)), 400)
    return JSONResponse(status_code=status_code, content={"detail": exc.detail})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """DB 제약 위반이 500 으로 나가지 않도록 409 로 변환 (docs/db-design-issues.md 1장)."""
    return JSONResponse(status_code=409, content={"detail": integrity_error_message(exc)})


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
