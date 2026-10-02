from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# 에러 응답 형식 {"error": {"code", "message", "detail"}} → app/api/errors.py
register_exception_handlers(app)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
