"""Миграции выполняются ролью lmb_admin (LMB_ADMIN_DATABASE_URL)."""
import os
import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[2] / "lmb-engine"
if _ENGINE.exists():
    sys.path.insert(0, str(_ENGINE))

from alembic import context
from sqlalchemy import create_engine

from lmb_server.db import Base
from lmb_server import models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online():
    engine = create_engine(os.environ["LMB_ADMIN_DATABASE_URL"])
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
