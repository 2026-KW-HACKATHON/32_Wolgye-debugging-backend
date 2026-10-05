from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

# FE 개발 서버(localhost:5173)는 출처가 달라 CORS 허용이 필요하다 (#36). 인증은 Bearer 헤더라 쿠키는 쓰지 않는다
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# 에러 응답 형식 {"error": {"code", "message", "detail"}} → app/api/errors.py
register_exception_handlers(app)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
