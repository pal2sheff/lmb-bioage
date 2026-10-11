"""FRAXProvider: внутренний устойчивый контракт и реализации (ТЗ 10.1.3).

Схема запроса и ответа облачного FRAXplus API на 10.10.2026 не получена (страница
спецификации формируется скриптом). Поэтому сопоставление полей вынесено в объект
mapping; рабочего сопоставления пока нет, и HTTP-провайдер возвращает
integration_not_configured, а не отправляет запрос с выдуманными полями.
Подтверждено документацией: локальный Docker-образ принимает ключ в заголовке x-api-key;
в CSV-спецификации FRAXplus пол кодируется 0 — мужчины, 1 — женщины.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from .request import FRAXRequest

ERROR_CODES = ("auth_failed", "quota_exhausted", "rate_limited", "timeout", "network_error", "bad_request",
               "unsupported_country_model", "unit_mismatch", "response_schema_invalid", "provider_unavailable",
               "mapping_not_verified")

# CSV-спецификация FRAXplus (fraxplus.org/documentation/csv/FRAX): 0 — мужчины, 1 — женщины.
# В LMB-нормализации наоборот: женщина = 0, мужчина = 1. Перепутать нельзя — есть тест.
FRAXPLUS_SEX_CODE = {"male": 0, "female": 1}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class FRAXResult:
    status: str                         # calculated | integration_not_configured | external_error
    provider: str
    frax_major_10y_pct: Optional[float] = None
    frax_hip_10y_pct: Optional[float] = None
    with_bmd: Optional[bool] = None
    national_model: Optional[str] = None
    provider_version: Optional[str] = None
    requested_at: dt.datetime = field(default_factory=_now)
    responded_at: Optional[dt.datetime] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    attempts: int = 0
    raw_response: Optional[dict] = None


class ProviderError(Exception):
    def __init__(self, code: str, detail: str = "", retryable: bool = False, retry_after: Optional[float] = None):
        assert code in ERROR_CODES
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.retryable, self.retry_after = code, detail, retryable, retry_after


class NotConfiguredProvider:
    name = "not_configured"

    def calculate(self, req: FRAXRequest) -> FRAXResult:
        return FRAXResult("integration_not_configured", self.name, error_detail="Доступ к FRAX API не настроен")


class Mapping:
    """Сопоставление внутреннего запроса с внешним API. Заполняется после чтения спецификации."""
    name = "abstract"
    verified = False

    def build(self, req: FRAXRequest) -> tuple[str, str, dict]:
        raise ProviderError("mapping_not_verified", "Сопоставление полей FRAXplus API не задано")

    def parse(self, body: dict) -> dict:
        """Вернуть dict: major, hip, horizon_years, country, with_bmd, version."""
        raise ProviderError("mapping_not_verified", "Сопоставление полей FRAXplus API не задано")

    def classify(self, status: int, body: Optional[dict]) -> Optional[ProviderError]:
        """Специфичные коды провайдера (например, исчерпание лимита). None — общая обработка."""
        return None


class UnverifiedMapping(Mapping):
    name = "unverified"


def validate_response(req: FRAXRequest, parsed: dict) -> tuple[float, float]:
    """HTTP 200 ещё не означает корректный медицинский ответ."""
    major, hip = parsed.get("major"), parsed.get("hip")
    for label, v in (("major", major), ("hip", hip)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not 0 <= v <= 100:
            raise ProviderError("response_schema_invalid", f"{label}: {v!r} не число 0–100")
    if parsed.get("horizon_years") != 10:
        raise ProviderError("response_schema_invalid", "горизонт не 10 лет")
    if parsed.get("country") != req.model_country:
        raise ProviderError("unsupported_country_model", f"модель {parsed.get('country')!r} вместо Kazakhstan")
    if parsed.get("with_bmd") != (req.fn_bmd is not None):
        raise ProviderError("response_schema_invalid", "признак МПК в ответе не совпадает с запросом")
    return float(major), float(hip)


class FraxPlusHttpProvider:
    """Облачный FRAXplus API или локальный Docker-экземпляр; отличаются адресом и ключом."""

    def __init__(self, kind: str, base_url: str, api_key: str, mapping: Mapping, api_key_header: str = "x-api-key",
                 timeout_s: float = 15.0, max_attempts: int = 3, backoff_s: tuple = (2.0, 8.0, 30.0),
                 transport: Optional[httpx.BaseTransport] = None, sleep: Callable[[float], None] = time.sleep):
        assert kind in ("fraxplus_cloud", "fraxplus_local")
        self.name = kind
        self.base_url, self.api_key, self.mapping = base_url.rstrip("/"), api_key, mapping
        self.header, self.timeout, self.max_attempts, self.backoff = api_key_header, timeout_s, max_attempts, backoff_s
        self.transport, self.sleep = transport, sleep

    def calculate(self, req: FRAXRequest) -> FRAXResult:
        res = FRAXResult("external_error", self.name)
        if not self.mapping.verified:
            res.status, res.error_code = "integration_not_configured", "mapping_not_verified"
            res.error_detail = "Сопоставление полей FRAXplus API не подтверждено спецификацией"
            return res
        method, path, body = self.mapping.build(req)
        with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
            for attempt in range(1, self.max_attempts + 1):
                res.attempts = attempt
                try:
                    return self._once(client, method, path, body, req, res)
                except ProviderError as e:
                    res.error_code, res.error_detail = e.code, e.detail
                    if not e.retryable or attempt == self.max_attempts:
                        res.status = "external_error"
                        res.responded_at = _now()
                        return res
                    wait = e.retry_after if e.retry_after is not None else self.backoff[min(attempt - 1, len(self.backoff) - 1)]
                    self.sleep(min(wait, 60.0))
        return res  # pragma: no cover

    def _once(self, client, method, path, body, req, res) -> FRAXResult:
        try:
            r = client.request(method, path, json=body, headers={self.header: self.api_key,
                                                                 "accept": "application/json"})
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", type(e).__name__, retryable=True)
        except httpx.TransportError as e:
            raise ProviderError("network_error", type(e).__name__, retryable=True)
        try:
            data = r.json()
        except ValueError:
            data = None
        special = self.mapping.classify(r.status_code, data)
        if special:
            raise special
        if r.status_code in (401, 403):
            raise ProviderError("auth_failed", f"HTTP {r.status_code}")
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            raise ProviderError("rate_limited", "HTTP 429", retryable=True,
                                retry_after=float(ra) if ra and ra.isdigit() else None)
        if r.status_code >= 500:
            raise ProviderError("provider_unavailable", f"HTTP {r.status_code}", retryable=True)
        if r.status_code != 200:
            raise ProviderError("bad_request", f"HTTP {r.status_code}")
        if not isinstance(data, dict):
            raise ProviderError("response_schema_invalid", "ответ не JSON-объект")
        parsed = self.mapping.parse(data)
        major, hip = validate_response(req, parsed)
        res.status, res.frax_major_10y_pct, res.frax_hip_10y_pct = "calculated", major, hip
        res.with_bmd, res.national_model = req.fn_bmd is not None, req.model_country
        res.provider_version, res.responded_at, res.error_code, res.error_detail = parsed.get("version"), _now(), None, None
        res.raw_response = data
        return res


MAPPINGS = {"unverified": UnverifiedMapping}
