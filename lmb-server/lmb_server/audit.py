"""Журнал аудита. В details не записываются медицинские значения и персональные данные."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditEvent


def log(db: Session, request: Optional[Request], actor_id: Optional[uuid.UUID], clinic_id: Optional[uuid.UUID],
        action: str, entity_type: str | None = None, entity_id: object = None,
        patient_id: Optional[uuid.UUID] = None, details: dict | None = None) -> None:
    ip = request.client.host if request is not None and request.client else None
    if ip == "testclient":
        ip = None
    db.add(AuditEvent(actor_id=actor_id, clinic_id=clinic_id, action=action, entity_type=entity_type,
                      entity_id=str(entity_id) if entity_id is not None else None, patient_id=patient_id,
                      details=details, ip=ip))
