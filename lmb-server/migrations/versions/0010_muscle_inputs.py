"""Мышечная ветка: сегменты Visbody, сила хвата, пять вставаний; название «Возраст по LQ1» (задание 12.10.2026)

Показатели только отображаются и используются для мышечного возраста (модель 0.1-synthetic);
в модель LMB v0.3 не входят (in_model_inputs = false). Существующие показатели не меняются.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

CODES = ("visbody_seg_arm_left_kg", "visbody_seg_arm_right_kg", "visbody_seg_leg_left_kg", "visbody_seg_leg_right_kg",
         "grip_right_kg", "grip_left_kg", "chair_stand_5x_s")


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
    op.execute("UPDATE observation_definition SET name_ru = 'Возраст по LQ1 (из отчёта)' WHERE code = 'lqone_bioage_years'")


def downgrade():
    op.execute("UPDATE observation_definition SET name_ru = 'Биологический возраст (LQ One)' WHERE code = 'lqone_bioage_years'")
    codes = ",".join(f"'{c}'" for c in CODES)
    op.execute(f"DELETE FROM observation_definition WHERE code IN ({codes}) "
               "AND code NOT IN (SELECT DISTINCT definition_code FROM observation)")
