"""Фоновый обработчик очереди FRAX.

Запуск: python3 -m lmb_server.frax.worker [--once]
Работает с ролью lmb_admin, потому что обрабатывает задачи всех клиник.
"""
from __future__ import annotations

import argparse
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..settings import get_settings
from .service import process_pending


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()
    eng = create_engine(get_settings().admin_database_url, pool_pre_ping=True)
    while True:
        n = process_pending(lambda: Session(eng))
        if a.once:
            print(f"Обработано задач: {n}")
            return
        if n == 0:
            time.sleep(a.interval)


if __name__ == "__main__":
    main()
