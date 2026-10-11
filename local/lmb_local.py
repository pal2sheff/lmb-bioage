"""Локальный запуск LMB BioAge на одном компьютере (тестовый режим).

Команды:
  setup   — первый запуск: ключи, база PostgreSQL в папке данных, миграции, учётная запись врача
  start   — запустить базу и сайт (http://127.0.0.1:8000) и открыть браузер; Ctrl+C — остановить
  stop    — остановить базу, если она осталась запущенной
  backup  — резервная копия базы и файлов в папку backups
  status  — где лежат данные и запущена ли база

Папка данных: %LOCALAPPDATA%\\LMB-BioAge в Windows, ~/.local/share/lmb-bioage в Linux и macOS
(переопределяется переменной LMB_HOME). Сайт слушает только 127.0.0.1 — с других компьютеров
он недоступен. Второй фактор входа (TOTP) в этом режиме выключен.

Ключи шифрования лежат в secrets.env в папке данных. Без них ФИО, ИИН, контакты и файлы
восстановить нельзя: храните копию отдельно от резервных копий базы.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "lmb-server"
ENGINE = REPO / "lmb-engine"
DIST = REPO / "lmb-web" / "dist"
IS_WIN = os.name == "nt"
APP_HOST = "127.0.0.1"


# ---------------------------------------------------------------- пути и настройки
def home() -> Path:
    if os.environ.get("LMB_HOME"):
        return Path(os.environ["LMB_HOME"])
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LMB-BioAge"
    return Path.home() / ".local" / "share" / "lmb-bioage"


H = home()
PGDATA = H / "pgdata"
CONFIG = H / "config.json"
SECRETS = H / "secrets.env"


def say(msg: str) -> None:
    print(f"[LMB] {msg}", flush=True)


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("Не найден свободный порт")


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def read_secrets() -> dict:
    out = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def make_secrets() -> None:
    if SECRETS.exists():
        return
    from cryptography.fernet import Fernet
    SECRETS.write_text(
        "# Ключи LMB BioAge. Храните копию отдельно от базы: без них зашифрованные данные не восстановить.\n"
        f"LMB_FIELD_KEY={Fernet.generate_key().decode()}\n"
        f"LMB_INDEX_KEY={base64.urlsafe_b64encode(os.urandom(32)).decode()}\n"
        f"LMB_FILES_KEY={Fernet.generate_key().decode()}\n", encoding="utf-8")
    if not IS_WIN:
        os.chmod(SECRETS, 0o600)
    say(f"Созданы ключи шифрования: {SECRETS}")


# ---------------------------------------------------------------- PostgreSQL
def pg_bin(name: str) -> str:
    exe = name + (".exe" if IS_WIN else "")
    found = shutil.which(exe)
    if found:
        return found
    patterns = [r"C:\Program Files\PostgreSQL\*\bin", r"C:\Program Files (x86)\PostgreSQL\*\bin"] if IS_WIN \
        else ["/usr/lib/postgresql/*/bin", "/opt/homebrew/opt/postgresql@*/bin", "/usr/local/opt/postgresql@*/bin"]
    for pat in patterns:
        for d in sorted(glob.glob(pat), reverse=True):
            p = Path(d) / exe
            if p.exists():
                return str(p)
    raise SystemExit(f"Не найден {exe}. Установите PostgreSQL 16 (см. local/README.md).")


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def pg_running() -> bool:
    if not PGDATA.exists():
        return False
    r = subprocess.run([pg_bin("pg_ctl"), "-D", str(PGDATA), "status"], capture_output=True, text=True)
    return r.returncode == 0


def pg_start(cfg: dict) -> None:
    if pg_running():
        return
    opts = f"-p {cfg['pg_port']} -c listen_addresses=127.0.0.1"
    if not IS_WIN:
        opts += f" -k {PGDATA}"
    run([pg_bin("pg_ctl"), "-D", str(PGDATA), "-o", opts, "-l", str(H / "postgres.log"), "-w", "start"],
        stdout=subprocess.DEVNULL)
    say(f"База данных запущена (порт {cfg['pg_port']})")


def pg_stop() -> None:
    if pg_running():
        run([pg_bin("pg_ctl"), "-D", str(PGDATA), "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL)
        say("База данных остановлена")


def db_url(cfg: dict, user: str, db: str = "lmb", driver: str = "postgresql+psycopg") -> str:
    return f"{driver}://{user}@127.0.0.1:{cfg['pg_port']}/{db}"


def server_env(cfg: dict) -> dict:
    env = dict(os.environ)
    env.update(read_secrets())
    env.update({
        "LMB_DATABASE_URL": db_url(cfg, "lmb_app"),
        "LMB_ADMIN_DATABASE_URL": db_url(cfg, "lmb_admin"),
        "LMB_FILES_DIR": str(H / "files"),
        "LMB_COOKIE_SECURE": "false",           # только http://127.0.0.1
        "LMB_REQUIRE_STAFF_TOTP": "false",      # тестовый режим на одном компьютере
        "LMB_ENVIRONMENT": "local",
        "LMB_STATIC_DIR": str(DIST),
        "PYTHONPATH": os.pathsep.join([str(SERVER), str(ENGINE), env.get("PYTHONPATH", "")]),
    })
    return env


def migrate(cfg: dict) -> None:
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=SERVER, env=server_env(cfg),
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-3000:])
        raise SystemExit("Ошибка обновления базы (миграции)")
    say("Структура базы актуальна")


# ---------------------------------------------------------------- команды
def cmd_setup(a) -> None:
    H.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.setdefault("pg_port", free_port(54329))
    cfg.setdefault("app_port", 8000)
    save_config(cfg)
    make_secrets()
    if not PGDATA.exists():
        say("Создаю базу данных в папке данных…")
        run([pg_bin("initdb"), "-D", str(PGDATA), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
            stdout=subprocess.DEVNULL)
    pg_start(cfg)
    try:
        import psycopg
        with psycopg.connect(db_url(cfg, "postgres", "postgres", "postgresql"), autocommit=True) as c:
            roles = {r[0] for r in c.execute("select rolname from pg_roles")}
            if "lmb_admin" not in roles:
                c.execute("CREATE ROLE lmb_admin LOGIN BYPASSRLS")
            if "lmb_app" not in roles:
                c.execute("CREATE ROLE lmb_app LOGIN NOBYPASSRLS")
            if not c.execute("select 1 from pg_database where datname = 'lmb'").fetchone():
                c.execute("CREATE DATABASE lmb OWNER lmb_admin")
        migrate(cfg)
        create_first_user(cfg, a)
    finally:
        pg_stop()
    say("Готово. Запуск: start.bat (или python local/lmb_local.py start)")
    say(f"ВАЖНО: сохраните копию файла ключей в надёжном месте: {SECRETS}")


def create_first_user(cfg: dict, a) -> None:
    os.environ.update(server_env(cfg))
    sys.path[:0] = [str(SERVER), str(ENGINE)]
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from lmb_server.bootstrap import create_clinic, create_user
    from lmb_server.models import User
    eng = create_engine(os.environ["LMB_ADMIN_DATABASE_URL"])
    with Session(eng) as s, s.begin():
        if s.scalar(select(func.count()).select_from(User)):
            say("Учётная запись уже есть — пропускаю")
            return
        email = a.email or input("Электронная почта врача для входа: ").strip()
        name = a.name or input("Имя врача (как показывать в системе): ").strip() or "Врач"
        pw = os.environ.get("LMB_BOOTSTRAP_PASSWORD")
        while not pw:
            p1 = getpass.getpass("Пароль (не короче 12 символов): ")
            if len(p1) < 12:
                print("Слишком короткий пароль")
                continue
            if getpass.getpass("Повторите пароль: ") != p1:
                print("Пароли не совпадают")
                continue
            pw = p1
        c = create_clinic(s, a.clinic)
        # один пользователь в тестовом режиме: врач, администратор клиники и ответственный за модель
        create_user(s, c.id, email, name, pw, ["doctor", "clinic_admin"], model_owner=True)
    say(f"Создана учётная запись {email}")


def cmd_start(a) -> None:
    cfg = load_config()
    if not cfg or not PGDATA.exists():
        raise SystemExit("Сначала выполните установку: install.bat (или python local/lmb_local.py setup)")
    if not (DIST / "index.html").exists():
        raise SystemExit("Интерфейс не собран: выполните install.bat ещё раз")
    pg_start(cfg)
    try:
        migrate(cfg)
        env = server_env(cfg)
        os.environ.update(env)
        sys.path[:0] = [str(SERVER), str(ENGINE)]
        port = free_port(cfg["app_port"])
        url = f"http://{APP_HOST}:{port}/"
        if not a.no_browser:
            threading.Timer(2.0, lambda: webbrowser.open(url)).start()
        say(f"Сайт: {url}  (остановить — Ctrl+C или закрыть это окно)")
        import uvicorn
        uvicorn.run("lmb_server.main:app", host=APP_HOST, port=port, log_level="warning")
    finally:
        pg_stop()


def cmd_stop(a) -> None:
    pg_stop()


def cmd_backup(a) -> None:
    cfg = load_config()
    was_running = pg_running()
    pg_start(cfg)
    try:
        out = H / "backups"
        out.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dump = out / f"lmb-{stamp}.dump"
        run([pg_bin("pg_dump"), "-h", "127.0.0.1", "-p", str(cfg["pg_port"]), "-U", "lmb_admin", "-Fc",
             "-f", str(dump), "lmb"])
        files = H / "files"
        arch = out / f"files-{stamp}.zip"
        with zipfile.ZipFile(arch, "w", zipfile.ZIP_STORED) as z:
            if files.exists():
                for p in files.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(files))
        say(f"Резервная копия: {dump.name} и {arch.name} в {out}")
        say("Ключи (secrets.env) в копию не входят — храните их копию отдельно")
    finally:
        if not was_running:
            pg_stop()


def cmd_status(a) -> None:
    say(f"Папка данных: {H}")
    say(f"Ключи: {SECRETS} ({'есть' if SECRETS.exists() else 'нет'})")
    say(f"База: {'запущена' if pg_running() else 'остановлена'}; настройки: {load_config()}")
    say(f"Интерфейс собран: {'да' if (DIST / 'index.html').exists() else 'нет'}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Локальный запуск LMB BioAge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--email")
    s.add_argument("--name")
    s.add_argument("--clinic", default="Love my body (тестовый режим)")
    st = sub.add_parser("start")
    st.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("backup")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    {"setup": cmd_setup, "start": cmd_start, "stop": cmd_stop, "backup": cmd_backup, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
