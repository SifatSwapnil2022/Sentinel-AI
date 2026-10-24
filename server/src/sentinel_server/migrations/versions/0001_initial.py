"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    """Create every table."""
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("team", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("label_delay_days", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("active_version_id", sa.BigInteger),
        sa.Column("incident_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("id ~ '^[a-z0-9][a-z0-9-]{0,63}$'", name="models_id_slug"),
        sa.CheckConstraint("label_delay_days >= 0", name="models_label_delay"),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "model_id",
            sa.String(64),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decision_threshold", sa.Double, nullable=False, server_default="0.5"),
        sa.Column("feature_schema", pg.JSONB, nullable=False),
        sa.Column("reference_csv", sa.LargeBinary),
        sa.Column("score_column", sa.Text, nullable=False),
        sa.Column("label_column", sa.Text, nullable=False),
        sa.Column("prediction_column", sa.Text),
        sa.Column("monitors", sa.LargeBinary),
        sa.Column("summary", pg.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("activate", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("fitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("model_id", "version"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name="model_versions_status"
        ),
        sa.CheckConstraint(
            "decision_threshold > 0 AND decision_threshold < 1", name="model_versions_threshold"
        ),
    )
    op.create_index(
        "model_versions_pending",
        "model_versions",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_foreign_key(
        "models_active_version",
        "models",
        "model_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Partitioned by day; partitions are created by the worker (db/partitions.py).
    op.execute(
        """
        CREATE TABLE predictions (
            model_id    varchar(64)      NOT NULL,
            request_id  varchar(128)     NOT NULL,
            ts          timestamptz      NOT NULL,
            version_id  bigint           NOT NULL,
            features    jsonb            NOT NULL,
            score       double precision NOT NULL CHECK (score >= 0 AND score <= 1),
            prediction  smallint         NOT NULL CHECK (prediction IN (0, 1)),
            latency_ms  double precision CHECK (latency_ms >= 0),
            PRIMARY KEY (model_id, request_id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute("CREATE INDEX predictions_request ON predictions (model_id, request_id)")
    op.execute("CREATE INDEX predictions_version_ts ON predictions (version_id, ts)")

    op.create_table(
        "labels",
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("label", sa.SmallInteger, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("label IN (0, 1)", name="labels_binary"),
    )
    op.create_table(
        "dirty_days",
        sa.Column(
            "version_id",
            sa.BigInteger,
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "daily_windows",
        sa.Column(
            "version_id",
            sa.BigInteger,
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("doc", pg.JSONB, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "model_documents",
        sa.Column(
            "model_id",
            sa.String(64),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("summary", pg.JSONB, nullable=False),
        sa.Column("doc", pg.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column(
            "model_id",
            sa.String(64),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.BigInteger,
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_on", sa.Date, nullable=False),
        sa.Column("resolved_on", sa.Date),
        sa.Column("doc", pg.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="incidents_status"),
    )
    op.create_index(
        "incidents_one_open_per_model",
        "incidents",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("incidents_model_opened", "incidents", ["model_id", "opened_on"])


def downgrade() -> None:
    """Drop every table, partitions included."""
    for table in (
        "incidents",
        "model_documents",
        "daily_windows",
        "dirty_days",
        "labels",
    ):
        op.drop_table(table)
    op.execute("DROP TABLE predictions CASCADE")  # takes its partitions with it
    op.drop_constraint("models_active_version", "models", type_="foreignkey")
    op.drop_table("model_versions")
    op.drop_table("models")
    op.drop_table("api_keys")
