"""Шифрование ФИО пациента (решение владельца 11.10.2026)

ФИО переносится в зашифрованные поля (ключ LMB_FIELD_KEY), для поиска по точной фамилии
добавляется слепой индекс (ключ LMB_INDEX_KEY). Открытые столбцы удаляются. Для переноса
существующих карточек миграции нужны те же ключи, что и серверу.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11 08:46:33.844196
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('patient', sa.Column('last_name_enc', sa.Text(), nullable=True))
    op.add_column('patient', sa.Column('first_name_enc', sa.Text(), nullable=True))
    op.add_column('patient', sa.Column('middle_name_enc', sa.Text(), nullable=True))
    op.add_column('patient', sa.Column('last_name_index', sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("select id, last_name, first_name, middle_name from patient")).all()
    if rows:
        from lmb_server.security import encrypt, name_index
        for r in rows:
            middle = r.middle_name.strip() if r.middle_name and r.middle_name.strip() else None
            bind.execute(sa.text("update patient set last_name_enc = :l, first_name_enc = :f, middle_name_enc = :m, "
                                 "last_name_index = :i where id = :id"),
                         {"l": encrypt(r.last_name.strip()), "f": encrypt(r.first_name.strip()),
                          "m": encrypt(middle), "i": name_index(r.last_name), "id": r.id})

    op.alter_column('patient', 'last_name_enc', nullable=False)
    op.alter_column('patient', 'first_name_enc', nullable=False)
    op.alter_column('patient', 'last_name_index', nullable=False)
    op.create_index('ix_patient_last_name_index', 'patient', ['clinic_id', 'last_name_index'], unique=False)
    op.drop_column('patient', 'first_name')
    op.drop_column('patient', 'middle_name')
    op.drop_column('patient', 'last_name')


def downgrade():
    op.add_column('patient', sa.Column('last_name', sa.TEXT(), nullable=True))
    op.add_column('patient', sa.Column('middle_name', sa.TEXT(), nullable=True))
    op.add_column('patient', sa.Column('first_name', sa.TEXT(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text("select id, last_name_enc, first_name_enc, middle_name_enc from patient")).all()
    if rows:
        from lmb_server.security import decrypt
        for r in rows:
            bind.execute(sa.text("update patient set last_name = :l, first_name = :f, middle_name = :m where id = :id"),
                         {"l": decrypt(r.last_name_enc), "f": decrypt(r.first_name_enc),
                          "m": decrypt(r.middle_name_enc), "id": r.id})
    op.alter_column('patient', 'last_name', nullable=False)
    op.alter_column('patient', 'first_name', nullable=False)
    op.drop_index('ix_patient_last_name_index', table_name='patient')
    op.drop_column('patient', 'last_name_index')
    op.drop_column('patient', 'middle_name_enc')
    op.drop_column('patient', 'first_name_enc')
    op.drop_column('patient', 'last_name_enc')
