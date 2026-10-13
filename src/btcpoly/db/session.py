from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from btcpoly.config import REPO_ROOT, Settings
from btcpoly.db.models import Base, RawPostRow
from btcpoly.ingestion.schema import RawPost

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def _sqlite_path_from_url(url: str) -> Path | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix) :]
    if rest in {":memory:", ""}:
        return None
    path = Path(rest)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def make_engine(settings: Settings, *, url: str | None = None) -> Engine:
    db_url = url or settings.database.url
    sqlite_path = _sqlite_path_from_url(db_url)
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{sqlite_path.as_posix()}"
    connect_args = {}
    engine_kwargs: dict = {"echo": settings.database.echo, "future": True}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 5
        if db_url.endswith(":memory:") or db_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(
        db_url,
        connect_args=connect_args,
        **engine_kwargs,
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_wal(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def init_db(settings: Settings, *, url: str | None = None, engine: Engine | None = None) -> Engine:
    global _ENGINE, _SESSION_FACTORY
    resolved = engine or make_engine(settings, url=url)
    Base.metadata.create_all(resolved)
    _ENGINE = resolved
    _SESSION_FACTORY = sessionmaker(bind=resolved, expire_on_commit=False, future=True)
    return resolved


def reset_engine() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def get_engine() -> Engine:
    if _ENGINE is None:
        raise RuntimeError("database not initialized; call init_db() first")
    return _ENGINE


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SESSION_FACTORY is None:
        raise RuntimeError("database not initialized; call init_db() first")
    session = _SESSION_FACTORY()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def table_names(engine: Engine | None = None) -> list[str]:
    target = engine or get_engine()
    return sorted(inspect(target).get_table_names())


def insert_raw_post(session: Session, post: RawPost) -> RawPostRow:
    row = RawPostRow(
        platform=post.platform,
        post_id=post.post_id,
        author=post.author,
        event_ts=post.event_ts,
        ingested_at=post.ingested_at,
        text=post.text,
        views=post.views,
        likes=post.likes,
        replies=post.replies,
        reposts=post.reposts,
        engagement=post.engagement,
        author_followers=post.author_followers,
        url=post.url,
        raw_json=post.raw_json,
    )
    session.add(row)
    session.flush()
    return row


def insert_raw_post_or_skip(session: Session, post: RawPost) -> bool:
    """Insert a post. Return True if inserted, False if duplicate (platform, post_id)."""
    try:
        with session.begin_nested():
            insert_raw_post(session, post)
        return True
    except IntegrityError:
        return False


def count_rows(model: type, engine: Engine | None = None) -> int:
    from sqlalchemy.orm import Session as SASession

    target = engine or get_engine()
    with SASession(target) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)
