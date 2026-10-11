"""Пароли (Argon2id), сеансы, TOTP, шифрование полей и слепой индекс."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

import os

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet

from .settings import get_settings

# Argon2id с параметрами библиотеки по умолчанию. Облегчённый профиль — только для тестов.
_ph = (PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
       if os.environ.get("LMB_ARGON2_PROFILE") == "test" else PasswordHasher())


def hash_password(pw: str) -> str:
    if len(pw) < 12:
        raise ValueError("Пароль должен быть не короче 12 символов")
    return _ph.hash(pw)


def verify_password(pw_hash: str, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


# Хеш-заглушка, чтобы время проверки не выдавало существование учётной записи
DUMMY_HASH = _ph.hash("timing-equalizer-not-a-password")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expiry() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=get_settings().session_hours)


def _fernet() -> Fernet:
    return Fernet(get_settings().field_key)


def encrypt(value: str | None) -> str | None:
    return None if value is None else _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    return None if value is None else _fernet().decrypt(value.encode()).decode()


def blind_index(value: str | None) -> str | None:
    """Детерминированный HMAC для точного поиска по зашифрованному полю (ИИН)."""
    if value is None:
        return None
    norm = "".join(ch for ch in value if ch.isdigit())
    return hmac.new(get_settings().index_key, norm.encode(), hashlib.sha256).hexdigest()


def normalize_name(value: str) -> str:
    """Нормализация ФИО для точного поиска: регистр, ё→е, пробелы и дефисы."""
    v = value.strip().casefold().replace("ё", "е")
    v = "-".join(part.strip() for part in v.split("-"))
    return " ".join(v.split())


def name_index(value: str | None) -> str | None:
    """Слепой индекс фамилии: HMAC с отдельной меткой, чтобы не совпадать с индексом ИИН.

    Позволяет найти пациента по точной фамилии, не храня её открыто. Поиск по началу
    фамилии и сортировка по алфавиту в базе при этом невозможны.
    """
    if value is None:
        return None
    msg = b"last_name\x00" + normalize_name(value).encode()
    return hmac.new(get_settings().index_key, msg, hashlib.sha256).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
