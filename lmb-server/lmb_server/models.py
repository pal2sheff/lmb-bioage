"""Модели базы данных (ТЗ, раздел 4 и приложение А) — очередь 0 и 1.1."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

ROLES = ("doctor", "clinic_admin", "researcher", "patient")


def _uuid():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Clinic(Base):
    __tablename__ = "clinic"
    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Asia/Almaty")
    created_at: Mapped[dt.datetime] = _now()


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret_enc: Mapped[Optional[str]] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_model_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), unique=True)
    created_at: Mapped[dt.datetime] = _now()


class UserRole(Base):
    __tablename__ = "user_role"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("app_user.id"))
    granted_at: Mapped[dt.datetime] = _now()
    __table_args__ = (CheckConstraint(f"role in {ROLES}", name="ck_user_role_role"),)


class AuthSession(Base):
    __tablename__ = "auth_session"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))


class Patient(Base):
    __tablename__ = "patient"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    # ФИО хранится зашифрованным (решение владельца 11.10.2026); поиск — по слепому индексу фамилии
    last_name_enc: Mapped[str] = mapped_column(Text, nullable=False)
    first_name_enc: Mapped[str] = mapped_column(Text, nullable=False)
    middle_name_enc: Mapped[Optional[str]] = mapped_column(Text)
    last_name_index: Mapped[str] = mapped_column(Text, nullable=False)
    iin_enc: Mapped[Optional[str]] = mapped_column(Text)
    iin_index: Mapped[Optional[str]] = mapped_column(Text)
    birth_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    sex_at_birth: Mapped[str] = mapped_column(String(6), nullable=False)
    phone_enc: Mapped[Optional[str]] = mapped_column(Text)
    email_enc: Mapped[Optional[str]] = mapped_column(Text)
    pseudonym_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("sex_at_birth in ('female','male')", name="ck_patient_sex"),
        UniqueConstraint("clinic_id", "iin_index", name="uq_patient_iin"),
        Index("ix_patient_last_name_index", "clinic_id", "last_name_index"),
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_patient_idem"),
    )


class Encounter(Base):
    __tablename__ = "encounter"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    encounter_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint("status in ('open','closed')", name="ck_encounter_status"),
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_encounter_idem"),
    )


class ObservationDefinition(Base):
    __tablename__ = "observation_definition"
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ru: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_canonical: Mapped[Optional[str]] = mapped_column(Text)
    allowed_units: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    plausible_min: Mapped[Optional[float]] = mapped_column(Float)
    plausible_max: Mapped[Optional[float]] = mapped_column(Float)
    in_model_inputs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    in_checkup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Observation(Base):
    """Одна запись — одна редакция. Редакции одного показателя объединены chain_id."""
    __tablename__ = "observation"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False, index=True)
    definition_code: Mapped[str] = mapped_column(ForeignKey("observation_definition.code"), nullable=False)
    chain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("observation.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    value_num: Mapped[Optional[float]] = mapped_column(Float)
    qualifier: Mapped[str] = mapped_column(String(2), nullable=False, default="eq")
    unit_original: Mapped[Optional[str]] = mapped_column(Text)
    sample_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    sample_id: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[Optional[str]] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(10), nullable=False)
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("app_user.id"))
    confirmed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    change_reason: Mapped[Optional[str]] = mapped_column(Text)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        UniqueConstraint("chain_id", "revision", name="uq_observation_chain_revision"),
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_observation_idem"),
        CheckConstraint("qualifier in ('eq','lt','gt')", name="ck_observation_qualifier"),
        CheckConstraint("source in ('manual','import','device','questionnaire','carry_over')",
                        name="ck_observation_source"),
        CheckConstraint("review_status in ('pending','confirmed','rejected')", name="ck_observation_review"),
        CheckConstraint("revision = 1 or change_reason is not null", name="ck_observation_reason"),
        Index("uq_observation_current", "chain_id", unique=True, postgresql_where=text("is_current")),
    )


class QuestionnaireAnswer(Base):
    """Ответы анкеты и клинические отметки; новые ответы не перезаписывают старые."""
    __tablename__ = "questionnaire_answer"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False, index=True)
    item_code: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    answered_by_role: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        UniqueConstraint("encounter_id", "item_code", "revision", name="uq_answer_revision"),
        Index("uq_answer_current", "encounter_id", "item_code", unique=True, postgresql_where=text("is_current")),
    )


class ModelVersion(Base):
    __tablename__ = "model_version"
    id: Mapped[uuid.UUID] = _uuid()
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # редакция конфигурации внутри версии модели: строка неизменяема, изменение = новая редакция
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    source_note: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    completeness: Mapped[str] = mapped_column(String(12), nullable=False)
    usage_permission: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_validated")
    synthetic_parameters: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint("state in ('draft','technically_verified','approved','archived')", name="ck_mv_state"),
        CheckConstraint("usage_permission in ('none','research_only','patient_report_allowed')", name="ck_mv_perm"),
        CheckConstraint("not (synthetic_parameters and usage_permission = 'patient_report_allowed')",
                        name="ck_mv_synthetic_not_for_patients"),
        UniqueConstraint("label", "revision", name="uq_model_version_label_revision"),
    )


class InputSnapshot(Base):
    __tablename__ = "input_snapshot"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (UniqueConstraint("encounter_id", "sha256", name="uq_snapshot"),)


class CalculationRun(Base):
    __tablename__ = "calculation_run"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False, index=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("input_snapshot.id"), nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_version.id"), nullable=False)
    model_config_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    app_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bioage_years: Mapped[Optional[float]] = mapped_column(Float)
    delta_years: Mapped[Optional[float]] = mapped_column(Float)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text)
    started_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (UniqueConstraint("clinic_id", "idempotency_key", name="uq_run_idem"),)


class Attachment(Base):
    """Файл, сохранённый на диске сервера клиники в зашифрованном виде."""
    __tablename__ = "attachment"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    filename_enc: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint("kind in ('frax_result','lab','visbody','lqone','other')", name="ck_attachment_kind"),
        CheckConstraint("mime_type in ('application/pdf','image/png','image/jpeg')", name="ck_attachment_mime"),
    )


class ExternalRequest(Base):
    """Запросы и результаты FRAX: автоматические (облачный или локальный сервис) и ручной ввод врача."""
    __tablename__ = "external_request"
    id: Mapped[uuid.UUID] = _uuid()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinic.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="frax")
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    frax_input_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(28), nullable=False)
    major_10y_pct: Mapped[Optional[float]] = mapped_column(Float)
    hip_10y_pct: Mapped[Optional[float]] = mapped_column(Float)
    with_bmd: Mapped[Optional[bool]] = mapped_column(Boolean)
    national_model: Mapped[Optional[str]] = mapped_column(Text)
    provider_version: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(Text)
    error_detail: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    manual_calculated_on: Mapped[Optional[dt.date]] = mapped_column(Date)
    manual_source_note: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("app_user.id"))
    confirmed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    attachment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("attachment.id"))
    inputs_bound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                              server_default=text("true"))
    is_active_choice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_note: Mapped[Optional[str]] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("provider in ('fraxplus_cloud','fraxplus_local','manual','not_configured','fake_test')",
                        name="ck_ext_provider"),
        CheckConstraint("status in ('queued','running','calculated','external_error','integration_not_configured')",
                        name="ck_ext_status"),
        CheckConstraint("major_10y_pct is null or (major_10y_pct >= 0 and major_10y_pct <= 100)", name="ck_ext_major"),
        CheckConstraint("hip_10y_pct is null or (hip_10y_pct >= 0 and hip_10y_pct <= 100)", name="ck_ext_hip"),
        CheckConstraint("status <> 'calculated' or (major_10y_pct is not null and hip_10y_pct is not null)",
                        name="ck_ext_both_risks"),
        CheckConstraint("provider <> 'manual' or (confirmed_by is not null and manual_calculated_on is not null)",
                        name="ck_ext_manual_confirmed"),
        CheckConstraint("not is_active_choice or status = 'calculated'", name="ck_ext_active_calculated"),
        CheckConstraint("(provider = 'fake_test') = is_test", name="ck_ext_test_flag"),
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_ext_idem"),
        Index("uq_ext_active", "encounter_id", unique=True, postgresql_where=text("is_active_choice")),
    )


class AuditEvent(Base):
    """Журнал только на добавление: роли приложения выдано лишь право INSERT."""
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[dt.datetime] = _now()
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    clinic_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(Text)
    entity_id: Mapped[Optional[str]] = mapped_column(Text)
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip: Mapped[Optional[str]] = mapped_column(INET)


RLS_TABLES = ("patient", "encounter", "observation", "questionnaire_answer", "input_snapshot", "calculation_run",
              "external_request", "attachment")
