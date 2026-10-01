import subprocess
import sys

from sqlalchemy.orm import configure_mappers

from app.db.base import Base


def test_mappers_configure():
    """모든 모델의 relationship/타입 표기가 해석되는지 (DB 없이) 확인."""
    configure_mappers()
    assert {
        "alleys",
        "buildings",
        "garages",
        "parking_slots",
        "residents",
        "vehicles",
        "parking_assignments",
        "departure_schedules",
        "share_offers",
        "share_requests",
        "token_transfers",
        "move_requests",
        "notifications",
    } <= set(Base.metadata.tables)


def test_app_import_registers_all_models():
    """앱만 import 해도(alembic 용 app.db.base 없이) 매퍼가 설정돼야 한다. 새 프로세스에서 확인."""
    code = "import app.main; from sqlalchemy.orm import configure_mappers; configure_mappers()"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
