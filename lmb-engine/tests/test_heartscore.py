"""Сверка SCORE2/SCORE2-OP с официальным калькулятором HeartScore ESC (Europe high risk).

Набор: tests/fixtures/heartscore_check.csv — 30 синтетических случаев HS01–HS30 владельца
(20 SCORE2, 10 SCORE2-OP; LMB_Claude_Decisions, 11.10.2026). Прежние строки C с другими входами
вынесены в score2_extra_inputs.csv без статуса официально сверенных. Строка с пустым hs_result
пропускается; значения за HeartScore не придумываются.

HeartScore принимает месяц и год рождения и считает непрерывный возраст на дату проверки.
День рождения ему неизвестен, поэтому случай считается совпавшим, если при каком-либо дне
рождения в указанном месяце наш риск даёт то же значение с той точностью, с какой его
показал HeartScore («1 %» — целые, «8,8 %» — десятые; «<1 %» — верхняя граница).
"""
import calendar
import csv
import datetime as dt
import re
from pathlib import Path

import pytest

from lmb_engine import cardio
from lmb_engine.core import Sex, age_exact_years

ROWS = list(csv.DictReader(open(Path(__file__).parent / "fixtures" / "heartscore_check.csv", encoding="utf-8")))
REQUIRED = 30


def parse_result(raw: str) -> dict:
    """«1%» → =1 (целые); «8,8%» → =8.8 (десятые); «<1%» → <1. Пусто → None."""
    raw = raw.strip()
    if not raw:
        return None
    m = re.fullmatch(r"(<|>)?\s*(\d+(?:[.,]\d+)?)\s*%", raw)
    if not m:
        raise ValueError(f"нераспознанный результат HeartScore «{raw}»")
    num = m.group(2).replace(",", ".")
    decimals = len(num.split(".")[1]) if "." in num else 0
    cmp = m.group(1) or "="
    return {"comparator": cmp, "risk_percent": float(num) if cmp == "=" else None,
            "bound_percent": float(num) if cmp != "=" else None, "decimals": decimals}


def our_risk_range(row) -> tuple:
    """Минимум и максимум нашего риска (%) по всем дням рождения в месяце, указанном в HeartScore."""
    mm, yyyy = (int(x) for x in row["hs_birth_month"].split("/"))
    check = dt.date.fromisoformat(row["hs_check_date"])
    p = cardio.load_params(row["model"])
    risks = []
    for day in range(1, calendar.monthrange(yyyy, mm)[1] + 1):
        age = age_exact_years(dt.date(yyyy, mm, day), check)
        risks.append(cardio.compute(p, age, Sex(row["sex"]), row["smoker"] == "1", float(row["sbp_mmhg"]),
                                    float(row["tc_mmol_l"]), float(row["hdl_mmol_l"]))["risk"] * 100)
    return min(risks), max(risks)


def test_parse_result_formats():
    assert parse_result("1%") == {"comparator": "=", "risk_percent": 1.0, "bound_percent": None, "decimals": 0}
    assert parse_result("8,8%")["risk_percent"] == 8.8 and parse_result("8,8%")["decimals"] == 1
    hs02 = parse_result("<1%")
    assert hs02["comparator"] == "<" and hs02["risk_percent"] is None and hs02["bound_percent"] == 1.0
    assert parse_result("") is None
    with pytest.raises(ValueError):
        parse_result("около 5")


@pytest.mark.parametrize("row", ROWS, ids=[r["case"] for r in ROWS])
def test_matches_heartscore(row):
    res = parse_result(row["hs_result"])
    if res is None:
        pytest.skip("результат HeartScore ещё не внесён")
    lo, hi = our_risk_range(row)
    if res["comparator"] == "<":
        assert lo < res["bound_percent"], (lo, hi)
    elif res["comparator"] == ">":
        assert hi > res["bound_percent"], (lo, hi)
    else:
        half = 0.5 * 10 ** -res["decimals"]
        v = res["risk_percent"]
        assert lo < v + half and hi >= v - half, f"наш риск {lo:.3f}–{hi:.3f} %, HeartScore {row['hs_result']}"


def test_hs04_requires_continuous_age():
    """С возрастом в целых годах (40) HS04 даёт 8,52 % вместо 8,8 % — поэтому SCORE2 считает
    непрерывный возраст, как HeartScore."""
    r = cardio.compute(cardio.load_params("score2"), 40, Sex.FEMALE, True, 160, 6.5, 1.0)["risk"] * 100
    assert round(r, 1) != 8.8


def _matches(row) -> bool:
    res = parse_result(row["hs_result"])
    if res is None:
        return False
    lo, hi = our_risk_range(row)
    if res["comparator"] == "<":
        return lo < res["bound_percent"]
    if res["comparator"] == ">":
        return hi > res["bound_percent"]
    half = 0.5 * 10 ** -res["decimals"]
    return lo < res["risk_percent"] + half and hi >= res["risk_percent"] - half


def test_checklist_status_and_activation_rule():
    """Каждый алгоритм активируется только после совпадения всех своих эталонов (20 и 10)."""
    assert len(ROWS) == REQUIRED
    assert [r["case"] for r in ROWS] == [f"HS{i:02d}" for i in range(1, 31)]
    need = {"score2": 20, "score2_op": 10}
    for code, n in need.items():
        rows = [r for r in ROWS if r["model"] == code]
        assert len(rows) == n
        if cardio.load_params(code)["verification"]["heartscore_verified"]:
            assert all(_matches(r) for r in rows), f"{code}: активирован без полной сверки"


def test_hs02_kept_as_bound():
    """HS02 «<1%» хранится как верхняя граница, точное число ему не присваивается."""
    hs02 = next(r for r in ROWS if r["case"] == "HS02")
    assert parse_result(hs02["hs_result"])["risk_percent"] is None
