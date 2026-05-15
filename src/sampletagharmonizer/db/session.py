from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sampletagharmonizer.config import database_url_from_env


def make_engine(database_url: str | None = None, env_path: Path = Path(".env")) -> Engine:
    url = database_url or database_url_from_env(env_path)
    return create_engine(url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(database_url: str | None = None, env_path: Path = Path(".env")) -> Iterator[Session]:
    engine = make_engine(database_url, env_path)
    factory = make_session_factory(engine)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            engine.dispose()


def healthcheck(database_url: str | None = None) -> None:
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    finally:
        engine.dispose()
