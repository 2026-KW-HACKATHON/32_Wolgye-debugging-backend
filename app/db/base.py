"""Alembic autogenerate 용: Base 와 전체 모델을 함께 노출한다."""
import app.models  # noqa: F401  (모든 모델을 Base.metadata 에 등록)
from app.db.base_class import Base

__all__ = ["Base"]
