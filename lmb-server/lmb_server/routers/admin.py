"""Версии модели (просмотр) и журнал аудита."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from lmb_engine.model import check_config

from ..db import get_db
from ..deps import Principal, require
from ..models import AuditEvent, ModelVersion

router = APIRouter(tags=["admin"])


@router.get("/model-versions")
def model_versions(p: Principal = Depends(require("doctor", model_owner=True)), db: Session = Depends(get_db)):
    out = []
    for mv in db.scalars(select(ModelVersion).order_by(ModelVersion.label, ModelVersion.revision)):
        chk = check_config(mv.config)
        out.append({"label": mv.label, "revision": mv.revision, "source_note": mv.source_note,
                    "state": mv.state, "completeness": mv.completeness,
                    "usage_permission": mv.usage_permission, "validation_status": mv.validation_status,
                    "synthetic_parameters": mv.synthetic_parameters, "config_sha256": mv.config_sha256,
                    "config_errors": chk.errors, "config_gaps": chk.gaps})
    return out


@router.get("/audit-events")
def audit_events(limit: int = 200, p: Principal = Depends(require("clinic_admin", model_owner=True)),
                 db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.clinic_id == p.clinic_id)
                      .order_by(AuditEvent.id.desc()).limit(min(limit, 1000))).all()
    return [{"id": a.id, "occurred_at": a.occurred_at.isoformat(), "actor_id": str(a.actor_id) if a.actor_id else None,
             "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
             "patient_id": str(a.patient_id) if a.patient_id else None, "details": a.details} for a in rows]
