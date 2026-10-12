"""«Возраст по LQ1» — одно поле (решение владельца 12.10.2026, 22:05)

Меняется только название показателя в справочнике; прежние записи (в том числе достоверность LQ One)
сохраняются без изменений, в интерфейсе не показываются.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-12
"""
from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE observation_definition SET name_ru = 'Возраст по LQ1' WHERE code = 'lqone_bioage_years'")


def downgrade():
    op.execute("UPDATE observation_definition SET name_ru = 'Возраст по LQ1 (из отчёта)' WHERE code = 'lqone_bioage_years'")
