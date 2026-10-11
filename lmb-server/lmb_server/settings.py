"""Настройки из переменных окружения. Секреты в код и журналы не попадают."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache


def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return v


@dataclass(frozen=True)
class Settings:
    database_url: str          # роль приложения lmb_app (без обхода RLS)
    admin_database_url: str    # роль lmb_admin (миграции, начальная настройка)
    field_key: bytes           # ключ шифрования полей (Fernet, base64 32 байта)
    index_key: bytes           # ключ слепого индекса (HMAC)
    cookie_secure: bool
    session_hours: int
    require_staff_totp: bool
    timezone: str
    environment: str           # production | test; тестовые результаты FRAX в рабочую базу не пишутся
    frax_provider: str         # none | fraxplus_cloud | fraxplus_local
    frax_base_url: str
    frax_api_key: str
    frax_api_key_header: str
    frax_mapping: str
    frax_annual_limit: int
    frax_allow_assumed_no: bool
    frax_store_raw: bool
    files_dir: str             # каталог файлов на диске сервера клиники
    files_key: bytes           # отдельный ключ шифрования файлов (Fernet)
    max_upload_mb: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=_req("LMB_DATABASE_URL"),
        admin_database_url=_req("LMB_ADMIN_DATABASE_URL"),
        field_key=_req("LMB_FIELD_KEY").encode(),
        index_key=base64.urlsafe_b64decode(_req("LMB_INDEX_KEY")),
        cookie_secure=os.environ.get("LMB_COOKIE_SECURE", "true") == "true",
        session_hours=int(os.environ.get("LMB_SESSION_HOURS", "12")),
        require_staff_totp=os.environ.get("LMB_REQUIRE_STAFF_TOTP", "true") == "true",
        timezone=os.environ.get("LMB_TIMEZONE", "Asia/Almaty"),
        environment=os.environ.get("LMB_ENVIRONMENT", "production"),
        frax_provider=os.environ.get("LMB_FRAX_PROVIDER", "none"),
        frax_base_url=os.environ.get("LMB_FRAX_BASE_URL", ""),
        frax_api_key=os.environ.get("LMB_FRAX_API_KEY", ""),
        frax_api_key_header=os.environ.get("LMB_FRAX_API_KEY_HEADER", "x-api-key"),
        frax_mapping=os.environ.get("LMB_FRAX_MAPPING", "unverified"),
        frax_annual_limit=int(os.environ.get("LMB_FRAX_ANNUAL_LIMIT", "5000")),
        # решение владельца по п. 7 раздела 21 ТЗ; до решения выключено
        frax_allow_assumed_no=os.environ.get("LMB_FRAX_ALLOW_ASSUMED_NO", "false") == "true",
        frax_store_raw=os.environ.get("LMB_FRAX_STORE_RAW", "false") == "true",
        files_dir=_req("LMB_FILES_DIR"),
        files_key=_req("LMB_FILES_KEY").encode(),
        max_upload_mb=int(os.environ.get("LMB_MAX_UPLOAD_MB", "20")),
    )
