"""Временный кластер PostgreSQL для тестов (без Docker).

Ищет бинарные файлы PostgreSQL в системе, создаёт кластер во временном каталоге,
роли lmb_admin (BYPASSRLS, владелец) и lmb_app (без обхода RLS) и базу lmb.
Под root кластер запускается от пользователя postgres.
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tempfile
import time


def _bin(name: str) -> str:
    found = shutil.which(name) or next(iter(sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"), reverse=True)), None)
    if not found:
        raise RuntimeError(f"Не найден {name}: установите PostgreSQL 16")
    return found


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PgCluster:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="lmbpg-", dir="/var/tmp")
        self.port = _free_port()
        self.as_postgres = os.geteuid() == 0
        if self.as_postgres:
            shutil.chown(self.dir, "postgres")

    def _run(self, *args):
        cmd = list(args)
        if self.as_postgres:
            cmd = ["runuser", "-u", "postgres", "--"] + cmd
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self) -> "PgCluster":
        data = os.path.join(self.dir, "data")
        self._run(_bin("initdb"), "-D", data, "-A", "trust", "-U", "postgres", "--locale=C.UTF-8", "-E", "UTF8")
        self._run(_bin("pg_ctl"), "-D", data, "-o", f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1",
                  "-l", os.path.join(self.dir, "log"), "-w", "start")
        import psycopg
        with psycopg.connect(self.url("postgres", "postgres"), autocommit=True) as c:
            c.execute("CREATE ROLE lmb_admin LOGIN BYPASSRLS")
            c.execute("CREATE ROLE lmb_app LOGIN NOBYPASSRLS")
            c.execute("CREATE DATABASE lmb OWNER lmb_admin")
        return self

    def url(self, user: str, db: str = "lmb", driver: str = "postgresql") -> str:
        return f"{driver}://{user}@127.0.0.1:{self.port}/{db}"

    def stop(self) -> None:
        try:
            self._run(_bin("pg_ctl"), "-D", os.path.join(self.dir, "data"), "-m", "fast", "-w", "stop")
        finally:
            time.sleep(0.2)
            shutil.rmtree(self.dir, ignore_errors=True)
