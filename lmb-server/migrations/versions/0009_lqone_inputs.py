"""LQ One: ручной ввод итогового показателя заключения (аудит владельца 12.10.2026)

«Биологический возраст (LQ One)», годы, и «Достоверность измерения (LQ One)», %. Только отображение
в ветке Adaptive: в модель LMB v0.3 не входят (in_model_inputs = false); существующие показатели
не меняются (уточнено только название поля ASM). Модель и версия аппарата, дата измерения — пункты анкеты врача (без изменения схемы).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CODES = ("lqone_bioage_years", "lqone_reliability_pct")


def upgrade():
    from lmb_server.catalog import observation_definitions
    for d in observation_definitions():
        if d["code"] not in CODES:
            continue
        op.get_bind().execute(sa.text(
            "insert into observation_definition (code, name_ru, value_type, unit_canonical, allowed_units, "
            "plausible_min, plausible_max, in_model_inputs, in_checkup) values (:code, :name_ru, :value_type, "
            ":unit_canonical, cast(:allowed_units as jsonb), :plausible_min, :plausible_max, :in_model_inputs, "
            ":in_checkup) on conflict (code) do nothing"), {**d, "allowed_units": json.dumps(d["allowed_units"])})
    # уточнение названия: поле — масса мышц конечностей (ASM), а не SMM и не сумма сегментов
    op.execute("UPDATE observation_definition SET name_ru = 'Масса мышц конечностей (ASM)' WHERE code = 'visbody_asm'")


def downgrade():
    op.execute("UPDATE observation_definition SET name_ru = 'Масса мышц конечностей' WHERE code = 'visbody_asm'")
    op.execute("DELETE FROM observation_definition WHERE code IN ('lqone_bioage_years','lqone_reliability_pct') "
               "AND code NOT IN (SELECT DISTINCT definition_code FROM observation)")
