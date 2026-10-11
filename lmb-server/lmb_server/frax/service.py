"""Задачи FRAX: создание, обработка, ручной ввод, выбор действующего результата.

Результат привязан к хешу FRAXRequest на момент запроса. Если врач изменил данные,
поздний ответ сохраняется для прежних входов и в новый расчёт не попадает.
Ручной результат не заменяется автоматическим незаметно: при двух результатах
для одних входов врач выбирает действующий.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Callable, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..engine_bridge import build_payload
from ..models import Encounter, ExternalRequest, Patient
from ..settings import get_settings
from .providers import MAPPINGS, FraxPlusHttpProvider, FRAXResult, NotConfiguredProvider
from .request import BuildResult, FRAXRequest, build_request

AUTO_PROVIDERS = ("fraxplus_cloud", "fraxplus_local", "fake_test")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def default_provider():
    st = get_settings()
    if st.frax_provider in ("fraxplus_cloud", "fraxplus_local") and st.frax_base_url and st.frax_api_key:
        return FraxPlusHttpProvider(st.frax_provider, st.frax_base_url, st.frax_api_key,
                                    MAPPINGS[st.frax_mapping](), api_key_header=st.frax_api_key_header)
    return NotConfiguredProvider()


# переопределяется в тестах
provider_factory: Callable[[], object] = default_provider


def current_inputs(db: Session, enc: Encounter, patient: Patient) -> BuildResult:
    return build_request(build_payload(db, enc, patient), get_settings().frax_allow_assumed_no)


def usage_this_year(db: Session) -> int:
    start = dt.datetime(_now().year, 1, 1, tzinfo=dt.timezone.utc)
    return db.scalar(select(func.count()).select_from(ExternalRequest).where(
        ExternalRequest.provider.in_(("fraxplus_cloud", "fraxplus_local")),
        ExternalRequest.attempts > 0, ExternalRequest.created_at >= start)) or 0


def create_job(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, enc: Encounter, req: FRAXRequest,
               idempotency_key: Optional[str]) -> tuple[ExternalRequest, bool]:
    """Вернуть (задача, создана_ли). Повтор с теми же входами не расходует лимит."""
    if idempotency_key:
        prev = db.scalar(select(ExternalRequest).where(ExternalRequest.clinic_id == clinic_id,
                                                       ExternalRequest.idempotency_key == idempotency_key))
        if prev:
            return prev, False
    h = req.input_hash()
    prov = provider_factory()
    reuse = db.scalar(select(ExternalRequest).where(
        ExternalRequest.encounter_id == enc.id, ExternalRequest.frax_input_hash == h,
        ExternalRequest.provider == prov.name,
        ExternalRequest.status.in_(("queued", "running", "calculated")))
        .order_by(ExternalRequest.created_at.desc()))
    if reuse:
        return reuse, False
    is_test = prov.name == "fake_test"
    if is_test and get_settings().environment != "test":
        raise RuntimeError("Тестовый провайдер FRAX запрещён вне тестовой среды")
    if prov.name == "not_configured":
        job = ExternalRequest(clinic_id=clinic_id, encounter_id=enc.id, provider="not_configured",
                              frax_input_hash=h, request_payload=req.to_dict(), status="integration_not_configured",
                              error_detail="Доступ к FRAX API не настроен", idempotency_key=idempotency_key,
                              created_by=user_id)
    else:
        job = ExternalRequest(clinic_id=clinic_id, encounter_id=enc.id, provider=prov.name, frax_input_hash=h,
                              request_payload=req.to_dict(), status="queued", is_test=is_test,
                              idempotency_key=idempotency_key, created_by=user_id)
    db.add(job)
    db.flush()
    return job, True


def _request_from_payload(d: dict) -> FRAXRequest:
    from .request import FemoralNeckBMD
    bmd = FemoralNeckBMD(**d["fn_bmd"]) if d.get("fn_bmd") else None
    return FRAXRequest(d["age_years"], d["sex"], d["bmi_kg_m2"], d["risk_factors"],
                       tuple(d.get("assumed_no_fields") or ()), bmd, d.get("model_country", "Kazakhstan"))


def process_pending(admin_db_factory: Callable[[], Session], provider=None, limit: int = 20) -> int:
    """Обработать очередь. Выполняется фоновым процессом с ролью lmb_admin."""
    provider = provider or provider_factory()
    done = 0
    for _ in range(limit):
        with admin_db_factory() as db:
            with db.begin():
                job = db.scalar(select(ExternalRequest).where(ExternalRequest.status == "queued")
                                .order_by(ExternalRequest.created_at).limit(1).with_for_update(skip_locked=True))
                if job is None:
                    return done
                job.status, job.started_at = "running", _now()
                job_id, payload = job.id, job.request_payload
            # внешний вызов — вне транзакции
            res: FRAXResult = provider.calculate(_request_from_payload(payload))
            with db.begin():
                job = db.get(ExternalRequest, job_id)
                _store_result(db, job, res)
        done += 1
    return done


def _store_result(db: Session, job: ExternalRequest, res: FRAXResult) -> None:
    job.status = res.status if res.status in ("calculated", "external_error", "integration_not_configured") \
        else "external_error"
    job.attempts = res.attempts
    job.error_code, job.error_detail = res.error_code, res.error_detail
    job.responded_at = res.responded_at or _now()
    if res.status == "calculated":
        job.major_10y_pct, job.hip_10y_pct = res.frax_major_10y_pct, res.frax_hip_10y_pct
        job.with_bmd, job.national_model, job.provider_version = res.with_bmd, res.national_model, res.provider_version
        if get_settings().frax_store_raw:
            job.response_payload = res.raw_response
        _maybe_activate(db, job)


def _maybe_activate(db: Session, job: ExternalRequest) -> None:
    """Правила выбора действующего результата.

    Автоматический результат никогда не заменяет действующий ручной: врач выбирает сам.
    Ручной ввод — явное действие врача: он становится действующим, если для тех же входов
    нет другого действующего результата.
    """
    active = db.scalar(select(ExternalRequest).where(ExternalRequest.encounter_id == job.encounter_id,
                                                     ExternalRequest.is_active_choice.is_(True)))
    if active is None:
        job.is_active_choice = True
        return
    if active.id == job.id:
        return
    same_inputs = active.inputs_bound and job.inputs_bound and active.frax_input_hash == job.frax_input_hash
    if job.provider != "manual" and active.provider == "manual":
        job.conflict_note = "Действует ручной результат; автоматический не заменяет его без решения врача"
    elif same_inputs:
        job.conflict_note = "Для тех же входов уже есть действующий результат; выбор за врачом"
    else:
        db.execute(update(ExternalRequest).where(ExternalRequest.id == active.id).values(is_active_choice=False))
        db.flush()
        job.is_active_choice = True


def add_manual(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, enc: Encounter, request_payload: dict,
               input_hash: str, inputs_bound: bool, major: float, hip: float, with_bmd: bool,
               calculated_on: dt.date, note: str, attachment_id: Optional[uuid.UUID],
               idempotency_key: Optional[str]) -> ExternalRequest:
    """Ручной ввод официального результата. Работает и без полной анкеты в системе
    (inputs_bound=False): врач подтверждает, что перенёс результат официального расчёта."""
    if idempotency_key:
        prev = db.scalar(select(ExternalRequest).where(ExternalRequest.clinic_id == clinic_id,
                                                       ExternalRequest.idempotency_key == idempotency_key))
        if prev:
            return prev
    job = ExternalRequest(clinic_id=clinic_id, encounter_id=enc.id, provider="manual",
                          frax_input_hash=input_hash, request_payload=request_payload, inputs_bound=inputs_bound,
                          status="calculated", major_10y_pct=major, hip_10y_pct=hip, with_bmd=with_bmd,
                          national_model="Kazakhstan", manual_calculated_on=calculated_on, manual_source_note=note,
                          attachment_id=attachment_id, confirmed_by=user_id, confirmed_at=_now(), attempts=0,
                          responded_at=_now(), idempotency_key=idempotency_key, created_by=user_id)
    db.add(job)
    db.flush()
    _maybe_activate(db, job)
    return job


def activate(db: Session, job: ExternalRequest) -> None:
    db.execute(update(ExternalRequest).where(ExternalRequest.encounter_id == job.encounter_id,
                                             ExternalRequest.is_active_choice.is_(True))
               .values(is_active_choice=False))
    db.flush()
    job.is_active_choice = True
    job.conflict_note = None


def augment_payload(db: Session, enc: Encounter, payload: dict) -> dict:
    """Добавить в снимок действующий результат FRAX, если он относится к текущим входам."""
    built = build_request(payload, get_settings().frax_allow_assumed_no)
    active = db.scalar(select(ExternalRequest).where(ExternalRequest.encounter_id == enc.id,
                                                     ExternalRequest.is_active_choice.is_(True)))
    flags = payload["flags"]
    applies = active is not None and (
        (active.provider == "manual" and not active.inputs_bound)
        or (built.request is not None and active.frax_input_hash == built.request.input_hash()))
    if applies:
        for code, v in (("frax_major_10y_pct", active.major_10y_pct), ("frax_hip_10y_pct", active.hip_10y_pct)):
            payload["measurements"][code] = {"observation_id": str(active.id), "revision": 1, "value": v,
                                             "unit": "%", "qualifier": "eq", "sample_date": None,
                                             "sample_id": f"frax:{active.id}", "review": "confirmed"}
        flags["frax_with_bmd"] = active.with_bmd
        flags["frax_source"] = "manual" if active.provider == "manual" else "automatic"
        flags["frax_provider"] = active.provider
        flags["frax_inputs_bound"] = active.inputs_bound
        return payload
    if built.status == "ready":
        last = db.scalar(select(ExternalRequest).where(ExternalRequest.encounter_id == enc.id,
                                                       ExternalRequest.frax_input_hash == built.request.input_hash())
                         .order_by(ExternalRequest.created_at.desc()))
        if last is not None and last.status in ("external_error", "integration_not_configured"):
            flags["frax_status"] = last.status
        elif last is None and provider_factory().name == "not_configured":
            flags["frax_status"] = "integration_not_configured"
    return payload
