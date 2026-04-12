from pathlib import Path
from typing import Optional

from app.env import settings

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def resolve_db_path(db_path: Optional[str] = None) -> Path:
    target = Path(db_path or settings.db_path)
    if not target.is_absolute():
        target = Path(__file__).resolve().parents[2] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
