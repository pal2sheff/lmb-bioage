"""Загрузка и выдача файлов. Файлы хранятся только на диске сервера клиники, в зашифрованном виде."""
from __future__ import annotations

import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import Principal, require
from ..models import Attachment, Encounter
from ..security import decrypt, encrypt
from ..storage import StorageError, get_storage
from .clinical import get_encounter

router = APIRouter(tags=["attachments"])
DOCTOR = require("doctor")


def att_out(a: Attachment) -> dict:
    return {"id": str(a.id), "encounter_id": str(a.encounter_id), "kind": a.kind, "filename": decrypt(a.filename_enc),
            "mime_type": a.mime_type, "size_bytes": a.size_bytes, "sha256": a.sha256,
            "created_at": a.created_at.isoformat() if a.created_at else None}


@router.post("/encounters/{encounter_id}/attachments", status_code=201)
async def upload(encounter_id: uuid.UUID, request: Request,
                 kind: Literal["frax_result", "lab", "visbody", "lqone", "other"] = Form(...),
                 file: UploadFile = File(...), p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    storage = get_storage()
    data = await file.read(storage.max_bytes + 1)
    try:
        stored = storage.put(p.clinic_id, data)
    except StorageError as err:
        raise HTTPException(422, str(err))
    name = (file.filename or "файл")[-200:]
    a = Attachment(clinic_id=p.clinic_id, encounter_id=e.id, kind=kind, filename_enc=encrypt(name),
                   mime_type=stored.mime_type, size_bytes=stored.size_bytes, sha256=stored.sha256,
                   storage_key=stored.storage_key, uploaded_by=p.id)
    try:
        db.add(a)
        db.flush()
        audit.log(db, request, p.id, p.clinic_id, "attachment_uploaded", "attachment", a.id, e.patient_id,
                  details={"kind": kind, "mime": stored.mime_type, "size": stored.size_bytes})
        db.commit()
    except Exception:
        storage.discard(stored.storage_key)   # не оставлять на диске файл без записи в базе
        raise
    return att_out(a)


@router.get("/encounters/{encounter_id}/attachments")
def list_attachments(encounter_id: uuid.UUID, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    e = get_encounter(db, p, encounter_id)
    rows = db.scalars(select(Attachment).where(Attachment.encounter_id == e.id).order_by(Attachment.created_at))
    return [att_out(a) for a in rows]


def get_attachment(db: Session, p: Principal, attachment_id: uuid.UUID) -> Attachment:
    a = db.get(Attachment, attachment_id)
    if a is None or a.clinic_id != p.clinic_id:
        raise HTTPException(404, "Файл не найден")
    return a


@router.get("/attachments/{attachment_id}")
def download(attachment_id: uuid.UUID, request: Request, p: Principal = Depends(DOCTOR), db: Session = Depends(get_db)):
    a = get_attachment(db, p, attachment_id)
    try:
        data = get_storage().get(a.storage_key, a.sha256)
    except StorageError as err:
        raise HTTPException(500, str(err))
    e = db.get(Encounter, a.encounter_id)
    audit.log(db, request, p.id, p.clinic_id, "attachment_downloaded", "attachment", a.id, e.patient_id)
    db.commit()
    name = quote(decrypt(a.filename_enc))
    return Response(data, media_type=a.mime_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{name}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
