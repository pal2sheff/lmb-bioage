"""Подключение к PostgreSQL и изоляция клиник.

Приложение работает под ролью lmb_app без права обхода политик строк (RLS).
В начале каждой транзакции устанавливается lmb.clinic_id текущего пользователя;
политики RLS пропускают только строки этой клиники. Это вторая линия защиты
после фильтров в коде.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def new_session() -> Session:
    engine()
    return _SessionLocal()


@event.listens_for(Session, "after_begin")
def _set_clinic(session: Session, transaction, connection) -> None:
    cid = session.info.get("clinic_id")
    connection.execute(text("select set_config('lmb.clinic_id', :c, true)"), {"c": str(cid) if cid else ""})


def get_db() -> Iterator[Session]:
    s = new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset_engine() -> None:
    """Для тестов: сбросить пул после смены настроек."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
