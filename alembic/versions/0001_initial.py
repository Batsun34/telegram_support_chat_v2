"""persistent support chat schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_user_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_support_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("telegram_id"),
    )
    op.create_index("ix_users_last_user_message", "users", ["last_user_message_at"], unique=False)
    op.create_index(
        "ix_users_last_support_message", "users", ["last_support_message_at"], unique=False
    )

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("sender_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_alias", sa.String(length=80), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("photo_file_id", sa.String(length=512), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("notification_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_messages_user_created",
        "support_messages",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_support_messages_pending_notify",
        "support_messages",
        ["sender_type", "notification_dispatched_at", "user_id"],
        unique=False,
    )

    op.create_table(
        "moderator_participants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("moderator_id", sa.BigInteger(), nullable=False),
        sa.Column("first_replied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_replied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "moderator_id", name="uq_participant_user_mod"),
    )
    op.create_index(
        "ix_participant_mod_last",
        "moderator_participants",
        ["moderator_id", "last_replied_at"],
        unique=False,
    )

    op.create_table(
        "moderator_sessions",
        sa.Column("moderator_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("active_user_id", sa.BigInteger(), nullable=True),
        sa.Column("active_page", sa.Integer(), nullable=False),
        sa.Column("last_rendered_message_id", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["active_user_id"], ["users.telegram_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("moderator_id"),
    )

    op.create_table(
        "moderator_view_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("moderator_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "moderator_id", "telegram_message_id", name="uq_view_mod_message"
        ),
    )
    op.create_index(
        "ix_view_mod_created",
        "moderator_view_messages",
        ["moderator_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_actor_created", "audit_logs", ["actor_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_actor_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_view_mod_created", table_name="moderator_view_messages")
    op.drop_table("moderator_view_messages")
    op.drop_table("moderator_sessions")
    op.drop_index("ix_participant_mod_last", table_name="moderator_participants")
    op.drop_table("moderator_participants")
    op.drop_index("ix_support_messages_pending_notify", table_name="support_messages")
    op.drop_index("ix_support_messages_user_created", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_users_last_support_message", table_name="users")
    op.drop_index("ix_users_last_user_message", table_name="users")
    op.drop_table("users")
