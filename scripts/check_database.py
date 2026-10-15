from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import Settings
from app.db.session import build_engine
from sqlalchemy import text

try:
    engine = build_engine(Settings())
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    engine.dispose()
except Exception:
    sys.exit(1)
