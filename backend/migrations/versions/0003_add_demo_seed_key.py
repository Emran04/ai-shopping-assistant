"""Track seeded demo products by their stable fixture keys."""

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("demo_seed_key", sa.String(length=120), nullable=True))
    op.create_unique_constraint("uq_products_demo_seed_key", "products", ["demo_seed_key"])


def downgrade() -> None:
    op.drop_constraint("uq_products_demo_seed_key", "products", type_="unique")
    op.drop_column("products", "demo_seed_key")
