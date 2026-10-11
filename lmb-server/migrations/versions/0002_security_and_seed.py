"""RLS, права роли приложения, уникальность текущих редакций, справочники и модель v0.3

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RLS_TABLES = ("patient", "encounter", "observation", "questionnaire_answer", "input_snapshot", "calculation_run")
APP_RW = ("clinic", "app_user", "user_role", "auth_session") + RLS_TABLES
APP_RO = ("observation_definition", "model_version")


def upgrade():
    # одна текущая редакция на показатель и на пункт анкеты
    op.create_index("uq_observation_current", "observation", ["chain_id"], unique=True,
                    postgresql_where=sa.text("is_current"))
    op.create_index("uq_answer_current", "questionnaire_answer", ["encounter_id", "item_code"], unique=True,
                    postgresql_where=sa.text("is_current"))

    # изоляция клиник политиками строк
    for t in RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {t}_clinic ON {t} "
            f"USING (clinic_id = nullif(current_setting('lmb.clinic_id', true), '')::uuid) "
            f"WITH CHECK (clinic_id = nullif(current_setting('lmb.clinic_id', true), '')::uuid)")

    # права роли приложения
    op.execute("GRANT USAGE ON SCHEMA public TO lmb_app")
    for t in APP_RW:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO lmb_app")
    for t in APP_RO:
        op.execute(f"GRANT SELECT ON {t} TO lmb_app")
    # журнал аудита — только добавление и чтение; изменение и удаление запрещены
    op.execute("GRANT SELECT, INSERT ON audit_event TO lmb_app")
    op.execute("GRANT USAGE ON SEQUENCE audit_event_id_seq TO lmb_app")
    # физическое удаление медицинских данных ролью приложения невозможно
    op.execute("REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM lmb_app")

    # справочник показателей
    from lmb_server.catalog import observation_definitions
    defs = sa.table("observation_definition", sa.column("code"), sa.column("name_ru"), sa.column("value_type"),
                    sa.column("unit_canonical"), sa.column("allowed_units", sa.JSON), sa.column("plausible_min"),
                    sa.column("plausible_max"), sa.column("in_model_inputs"), sa.column("in_checkup"))
    op.bulk_insert(defs, observation_definitions())

    # модель v0.3 в утверждённом виде: веса заданы, нормализация отсутствует
    from lmb_engine.model import check_config, config_sha256, default_v03_config
    cfg = default_v03_config()
    chk = check_config(cfg)
    mv = sa.table("model_version", sa.column("id", sa.Uuid), sa.column("label"), sa.column("state"),
                  sa.column("config", sa.JSON), sa.column("config_sha256"), sa.column("completeness"),
                  sa.column("usage_permission"), sa.column("validation_status"), sa.column("synthetic_parameters"))
    import uuid
    op.bulk_insert(mv, [dict(id=uuid.uuid4(), label="v0.3", state="draft", config=cfg,
                             config_sha256=config_sha256(cfg),
                             completeness="complete" if chk.complete else "incomplete",
                             usage_permission="none", validation_status="not_validated",
                             synthetic_parameters=False)])


def downgrade():
    op.execute("DELETE FROM model_version WHERE label = 'v0.3'")
    op.execute("DELETE FROM observation_definition")
    for t in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {t}_clinic ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_answer_current", table_name="questionnaire_answer")
    op.drop_index("uq_observation_current", table_name="observation")
