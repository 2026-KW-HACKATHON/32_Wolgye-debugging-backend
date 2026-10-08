from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "chagok-chagok-api"
    env: str = "local"
    api_v1_prefix: str = "/api/v1"

    # CORS (#36): 브라우저에서 API 를 부를 수 있는 FE 출처. .env 에서는 JSON 배열로 준다
    # 예) CORS_ORIGINS=["http://localhost:5173","https://chagok.example.com"]
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = "postgresql+asyncpg://chagok:chagok@localhost:5432/chagok"
    database_url_sync: str = "postgresql+psycopg2://chagok:chagok@localhost:5432/chagok"

    secret_key: str = "change-me-local-dev-only-secret-key-32b"  # JWT HS256 키는 32바이트 이상 (운영은 .env 로 교체)

    # 인증 (#6, 결정 8): JWT HS256. refresh 토큰은 DB 에 저장하지 않는다
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # 가입 시 시스템 지급 토큰 (결정 6)
    signup_token_grant: int = 500_000

    # 미등록 차량 제보 (#52). 사진은 REPORT_PHOTO_DIR 에 저장한다 (운영은 docker 볼륨)
    report_token_reward: int = 500
    report_daily_limit: int = 3  # 1인 하루(KST) 제보 횟수. 넘으면 409 REPORT_LIMIT_EXCEEDED
    report_photo_max_bytes: int = 10 * 1024 * 1024
    report_photo_dir: str = "data/vehicle-reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
