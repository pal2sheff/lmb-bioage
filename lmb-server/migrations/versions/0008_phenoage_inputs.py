"""Показатели контрольного PhenoAge в справочнике (решение владельца 11.10.2026)

Лейкоциты, MCV, RDW-CV, альбумин сыворотки, вч-СРБ, щелочная фосфатаза. В модель LMB v0.3
не входят (in_model_inputs = false); существующие показатели не меняются.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CODES = ("wbc", "mcv", "rdw", "albumin_serum", "crp", "alp")


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


def downgrade():
    # наблюдения с этими кодами (если есть) сохраняются; удаляется только неиспользованный справочник
    op.execute("DELETE FROM observation_definition WHERE code IN ('wbc','mcv','rdw','albumin_serum','crp','alp') "
               "AND code NOT IN (SELECT DISTINCT definition_code FROM observation)")
