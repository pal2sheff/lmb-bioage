"""FRAXRequest и HTTP-провайдер без базы данных.

MockMapping — тестовое сопоставление с вымышленными полями. Оно не описывает реальный
FRAXplus API и существует только для проверки повторов, ошибок и проверки ответа.
"""
import json

import httpx
import pytest

from lmb_server.frax.providers import (FRAXPLUS_SEX_CODE, FraxPlusHttpProvider, Mapping, NotConfiguredProvider,
                                       ProviderError, UnverifiedMapping)
from lmb_server.frax.request import RISK_FACTORS, build_request

ALL_NO = {f: "no" for f in RISK_FACTORS}


def payload(age=66, flags=None, ms=None, sex="female"):
    birth = f"{2026 - age}-01-01"
    m = {"height_cm": dict(value=160, unit="cm", qualifier="eq", review="confirmed"),
         "weight_kg": dict(value=60, unit="kg", qualifier="eq", review="confirmed")}
    m.update(ms or {})
    return {"encounter_date": "2026-10-10", "birth_date": birth, "sex": sex, "measurements": m,
            "flags": {**ALL_NO, **(flags or {})}}


# ---------------------------------------------------------------- сбор запроса
def test_ready_request_has_no_identifiers():
    b = build_request(payload())
    assert b.status == "ready"
    d = b.request.to_dict()
    assert set(d) == {"age_years", "sex", "bmi_kg_m2", "risk_factors", "assumed_no_fields", "fn_bmd", "model_country"}
    assert d["age_years"] == 66 and d["bmi_kg_m2"] == pytest.approx(60 / 1.6 ** 2)


@pytest.mark.parametrize("age", [35, 39, 91])
def test_b01_age_out_of_range_not_substituted(age):
    b = build_request(payload(age=age))
    assert b.status == "not_applicable" and b.request is None


def test_b02_unknown_is_not_no():
    b = build_request(payload(flags={"parent_hip_fracture": "unknown"}))
    assert b.status == "missing_data" and "parent_hip_fracture" in b.problems


def test_assumed_no_requires_setting():
    p = payload(flags={"parent_hip_fracture": "unknown", "frax_assumed_no": "parent_hip_fracture"})
    assert build_request(p).status == "invalid_input"
    b = build_request(p, allow_assumed_no=True)
    assert b.status == "ready" and b.request.risk_factors["parent_hip_fracture"] == "no"
    assert b.request.assumed_no_fields == ("parent_hip_fracture",)


def test_bmd_variants():
    t = dict(value=-2.6, unit="SD", qualifier="eq", review="confirmed")
    g = dict(value=0.71, unit="g/cm2", qualifier="eq", review="confirmed")
    b = build_request(payload(ms={"fn_tscore": t}))
    assert b.request.fn_bmd.kind == "t_score" and b.request.fn_bmd.site == "femoral_neck"
    assert build_request(payload(ms={"fn_bmd": g})).status == "missing_data"          # нет производителя
    b = build_request(payload(ms={"fn_bmd": g}, flags={"fn_bmd_device_make": "Hologic"}))
    assert b.request.fn_bmd.kind == "g_cm2" and b.request.fn_bmd.device_make == "Hologic"
    assert build_request(payload(ms={"fn_tscore": t, "fn_bmd": g})).status == "awaiting_review"


def test_bmi_range_and_pending():
    b = build_request(payload(ms={"weight_kg": dict(value=300, unit="kg", qualifier="eq", review="confirmed"),
                                  "height_cm": dict(value=100, unit="cm", qualifier="eq", review="confirmed")}))
    assert b.status == "invalid_input"
    b = build_request(payload(ms={"weight_kg": dict(value=60, unit="kg", qualifier="eq", review="pending")}))
    assert b.status == "awaiting_review"
    b = build_request(payload(ms={"weight_kg": dict(value=60, unit="kg", qualifier="lt", review="confirmed")}))
    assert b.status == "invalid_input"


def test_input_hash_changes_with_inputs():
    a = build_request(payload()).request.input_hash()
    assert a == build_request(payload()).request.input_hash()
    assert a != build_request(payload(flags={"smoking_current": "yes"})).request.input_hash()


def test_b03_sex_coding_differs_from_lmb():
    """LMB: женщина = 0. FRAXplus CSV: женщины = 1."""
    from lmb_engine.model import LMB_SEX_CODE
    from lmb_engine.core import Sex
    assert LMB_SEX_CODE[Sex.FEMALE] == 0 and FRAXPLUS_SEX_CODE["female"] == 1
    assert LMB_SEX_CODE[Sex.MALE] == 1 and FRAXPLUS_SEX_CODE["male"] == 0


# ---------------------------------------------------------------- провайдер
class MockMapping(Mapping):
    """Только для тестов: вымышленный формат, не реальный FRAXplus API."""
    name, verified = "test", True

    def build(self, req):
        d = req.to_dict()
        d["sex_code"] = FRAXPLUS_SEX_CODE[req.sex]
        return "POST", "/test-calc", d

    def parse(self, body):
        return {"major": body.get("major"), "hip": body.get("hip"), "horizon_years": body.get("years"),
                "country": body.get("country"), "with_bmd": body.get("with_bmd"), "version": body.get("v")}

    def classify(self, status, body):
        if status == 403 and isinstance(body, dict) and body.get("error") == "quota":
            return ProviderError("quota_exhausted", "лимит")
        return None


GOOD = {"major": 12.3, "hip": 2.4, "years": 10, "country": "Kazakhstan", "with_bmd": False, "v": "4.4"}


def provider(handler, **kw):
    sleeps = []
    p = FraxPlusHttpProvider("fraxplus_local", "http://frax.local", "secret-key", MockMapping(),
                             transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return p, sleeps


REQ = build_request(payload()).request


def test_not_configured():
    assert NotConfiguredProvider().calculate(REQ).status == "integration_not_configured"


def test_unverified_mapping_sends_nothing():
    calls = []
    p = FraxPlusHttpProvider("fraxplus_cloud", "https://x", "k", UnverifiedMapping(),
                             transport=httpx.MockTransport(lambda r: calls.append(r)))
    r = p.calculate(REQ)
    assert r.status == "integration_not_configured" and r.error_code == "mapping_not_verified" and calls == []
    with pytest.raises(ProviderError):
        UnverifiedMapping().build(REQ)
    with pytest.raises(ProviderError):
        UnverifiedMapping().parse({})


def test_success_and_headers():
    seen = {}

    def h(req):
        seen["key"] = req.headers.get("x-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=GOOD)
    p, _ = provider(h)
    r = p.calculate(REQ)
    assert r.status == "calculated" and r.frax_major_10y_pct == 12.3 and r.frax_hip_10y_pct == 2.4
    assert r.provider_version == "4.4" and r.national_model == "Kazakhstan" and r.with_bmd is False
    assert seen["key"] == "secret-key" and seen["body"]["sex_code"] == 1
    assert "birth_date" not in seen["body"] and "name" not in json.dumps(seen["body"])


def test_auth_failed_not_retried():
    p, sleeps = provider(lambda r: httpx.Response(401, json={}))
    r = p.calculate(REQ)
    assert r.error_code == "auth_failed" and r.attempts == 1 and sleeps == []


def test_quota_classified():
    p, _ = provider(lambda r: httpx.Response(403, json={"error": "quota"}))
    assert p.calculate(REQ).error_code == "quota_exhausted"


def test_rate_limit_respects_retry_after():
    state = {"n": 0}

    def h(req):
        state["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "3"}) if state["n"] == 1 else httpx.Response(200, json=GOOD)
    p, sleeps = provider(h)
    r = p.calculate(REQ)
    assert r.status == "calculated" and r.attempts == 2 and sleeps == [3.0]


def test_server_errors_exhaust_retries():
    p, sleeps = provider(lambda r: httpx.Response(503, text="down"))
    r = p.calculate(REQ)
    assert r.status == "external_error" and r.error_code == "provider_unavailable" and r.attempts == 3
    assert sleeps == [2.0, 8.0]


def test_timeout_and_network():
    def t(req):
        raise httpx.ReadTimeout("slow")
    p, _ = provider(t)
    assert p.calculate(REQ).error_code == "timeout"

    def n(req):
        raise httpx.ConnectError("refused")
    p, _ = provider(n)
    assert p.calculate(REQ).error_code == "network_error"


@pytest.mark.parametrize("body,code", [
    ({**GOOD, "major": 140}, "response_schema_invalid"),          # B-20: HTTP 200 с риском 140 %
    ({**GOOD, "hip": None}, "response_schema_invalid"),
    ({**GOOD, "hip": True}, "response_schema_invalid"),
    ({**GOOD, "years": 5}, "response_schema_invalid"),
    ({**GOOD, "country": "UK"}, "unsupported_country_model"),
    ({**GOOD, "with_bmd": True}, "response_schema_invalid"),
])
def test_http_200_is_not_automatically_success(body, code):
    p, _ = provider(lambda r: httpx.Response(200, json=body))
    r = p.calculate(REQ)
    assert r.status == "external_error" and r.error_code == code and r.frax_major_10y_pct is None


def test_non_json_and_other_4xx():
    p, _ = provider(lambda r: httpx.Response(200, text="<html>"))
    assert p.calculate(REQ).error_code == "response_schema_invalid"
    p, _ = provider(lambda r: httpx.Response(422, json={}))
    assert p.calculate(REQ).error_code == "bad_request"
