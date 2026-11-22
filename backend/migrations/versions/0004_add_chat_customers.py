"""Persist shopping chat customers and their message usage."""

import sqlalchemy as sa
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("messages_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
        sa.CheckConstraint("messages_used >= 0", name="ck_chat_customer_messages_used"),
    )


def downgrade() -> None:
    op.drop_table("chat_customers")
