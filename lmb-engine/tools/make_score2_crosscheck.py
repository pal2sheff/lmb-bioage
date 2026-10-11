"""Формирует синтетические случаи SCORE2/SCORE2-OP и эталон независимой реализации.

Эталон: пакет cvd-risk 0.1.48 (PyPI, PyCVDRisk), регион high; возраст — целые годы.
Сверка с официальным HeartScore ведётся отдельно: tests/fixtures/heartscore_check.csv.
Пациенты выдуманы.
Запуск: pip install cvd-risk==0.1.48 && python3 tools/make_score2_crosscheck.py
"""
import csv
import random

from cvd_risk.core.validation import PatientData
from cvd_risk.models.score2.score2 import SCORE2
from cvd_risk.models.score2op.score2op import SCORE2OP

rnd = random.Random(20261010)
rows = []
specs = [(40, 69, 20, "score2"), (70, 89, 10, "score2_op")]
n = 0
for lo, hi, count, code in specs:
    ages = [lo, hi] + [rnd.randint(lo, hi) for _ in range(count - 2)]
    for i, age in enumerate(ages):
        n += 1
        sex = "male" if i % 2 == 0 else "female"
        smoker = rnd.random() < 0.4
        sbp = rnd.choice(range(100, 181, 5))
        tc = round(rnd.uniform(3.5, 8.0), 1)
        hdl = round(rnd.uniform(0.8, 2.2), 1)
        p = PatientData(age=age, sex=sex, systolic_bp=sbp, total_cholesterol=tc, hdl_cholesterol=hdl,
                        smoking=smoker, region="high", diabetes=False)
        model = SCORE2() if code == "score2" else SCORE2OP()
        ref = model.calculate(p).risk_score
        rows.append({"case": f"C{n:02d}", "model": code, "age": age, "sex": sex, "smoker": int(smoker),
                     "sbp_mmhg": sbp, "tc_mmol_l": tc, "hdl_mmol_l": hdl,
                     "cvd_risk_0_1_48_pct": f"{ref:.6f}"})

with open("tests/fixtures/score2_crosscheck.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), "cases")
