"""Редакция 3 модели v0.3: исследовательский режим (решение владельца 11.10.2026)

Коэффициенты, веса и правила доменов не меняются. Добавлены поля reference_sample = null,
research_mode = local_synthetic, research_population (синтетические профили 40–64 лет, Казахстан)
и research_limitations. target_population остаётся null: клинический итог по-прежнему
заблокирован, исследовательский расчёт выполняется отдельно. Редакция 2 → archived.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""
from pathlib import Path
import uuid

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SNAPSHOT = Path(__file__).resolve().parents[1] / "snapshots" / "model_v0.3_rev3.json"


def upgrade():
    from lmb_engine.model import check_config, config_sha256, load_config
    cfg = load_config(str(SNAPSHOT))
    chk = check_config(cfg)
    assert chk.valid, chk.errors
    assert chk.gaps == ["target_population"], chk.gaps
    op.execute("UPDATE model_version SET state = 'archived' WHERE label = 'v0.3' AND revision = 2")
    mv = sa.table("model_version", sa.column("id", sa.Uuid), sa.column("label"), sa.column("revision"),
                  sa.column("source_note"), sa.column("state"), sa.column("config", sa.JSON),
                  sa.column("config_sha256"), sa.column("completeness"), sa.column("usage_permission"),
                  sa.column("validation_status"), sa.column("synthetic_parameters"))
    op.bulk_insert(mv, [dict(id=uuid.uuid4(), label="v0.3", revision=3,
                             source_note="Исследовательский режим local_synthetic: LMB_Claude_Decisions от "
                                         "11.10.2026 (техническая область 40–64 лет, Казахстан; клиническая "
                                         "популяция и референтная выборка не заданы)",
                             state="draft", config=cfg, config_sha256=config_sha256(cfg),
                             completeness="incomplete", usage_permission="research_only",
                             validation_status="not_validated", synthetic_parameters=False)])


def downgrade():
    op.execute("DELETE FROM model_version WHERE label = 'v0.3' AND revision = 3")
    op.execute("UPDATE model_version SET state = 'draft' WHERE label = 'v0.3' AND revision = 2")
