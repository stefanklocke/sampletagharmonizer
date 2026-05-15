from __future__ import annotations

from pathlib import Path

from sampletagharmonizer.db.models import Base
from sampletagharmonizer.db.session import make_engine


def create_schema(database_url: str | None = None, env_path: Path = Path(".env")) -> None:
    engine = make_engine(database_url, env_path)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
