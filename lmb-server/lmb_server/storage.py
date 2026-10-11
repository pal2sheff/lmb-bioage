"""Хранение файлов только на диске сервера клиники.

Файлы не передаются в облачные хранилища и сторонние сервисы. Каждый файл
шифруется отдельным ключом хранилища (LMB_FILES_KEY, Fernet: AES-128-CBC + HMAC-SHA256)
и записывается в каталог LMB_FILES_DIR с правами только для владельца процесса.
Тип файла определяется по содержимому, а не по имени или заголовку браузера.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .settings import get_settings

SIGNATURES = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


class StorageError(ValueError):
    pass


@dataclass(frozen=True)
class Stored:
    storage_key: str
    sha256: str
    size_bytes: int
    mime_type: str


def sniff(data: bytes) -> tuple[str, str]:
    for sig, mime, ext in SIGNATURES:
        if data.startswith(sig):
            return mime, ext
    raise StorageError("Допустимы только PDF, PNG и JPEG")


class LocalEncryptedStorage:
    def __init__(self, root: str, key: bytes, max_bytes: int):
        self.root = Path(root).resolve()
        self.fernet = Fernet(key)
        self.max_bytes = max_bytes

    def _path(self, storage_key: str) -> Path:
        p = (self.root / storage_key).resolve()
        if self.root not in p.parents:
            raise StorageError("Недопустимый путь хранения")
        return p

    def put(self, clinic_id: uuid.UUID, data: bytes) -> Stored:
        if not data:
            raise StorageError("Пустой файл")
        if len(data) > self.max_bytes:
            raise StorageError(f"Файл больше {self.max_bytes // (1024 * 1024)} МБ")
        mime, _ = sniff(data)
        key = f"{clinic_id}/{uuid.uuid4().hex}.lmbenc"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(".tmp")
        # O_BINARY — только Windows: без него файл открывается в текстовом режиме
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.fernet.encrypt(data))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return Stored(key, hashlib.sha256(data).hexdigest(), len(data), mime)

    def discard(self, storage_key: str) -> None:
        """Удалить файл, если запись о нём не попала в базу (откат загрузки)."""
        try:
            self._path(storage_key).unlink()
        except FileNotFoundError:
            pass

    def get(self, storage_key: str, expected_sha256: str) -> bytes:
        try:
            data = self.fernet.decrypt(self._path(storage_key).read_bytes())
        except (FileNotFoundError, InvalidToken) as e:
            raise StorageError("Файл недоступен или повреждён") from e
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise StorageError("Контрольная сумма файла не совпадает")
        return data


def get_storage() -> LocalEncryptedStorage:
    st = get_settings()
    return LocalEncryptedStorage(st.files_dir, st.files_key, st.max_upload_mb * 1024 * 1024)
