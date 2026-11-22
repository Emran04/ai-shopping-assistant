"""Add the clothing catalog and preserve existing products as drafts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 13:26:45.312834
"""

import sqlalchemy as sa
from alembic import op


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.CheckConstraint("kind IN ('audience', 'clothing_type')", name='ck_category_kind'),
        sa.CheckConstraint('sort_order >= 0', name='ck_category_order'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'slug', name='uq_category_kind_slug')
    )
    op.create_table('media_storage_locations',
        sa.Column('storage_id', sa.String(length=80), nullable=False),
        sa.Column('provider', sa.String(length=20), server_default='r2', nullable=False),
        sa.Column('bucket_name', sa.String(length=63), nullable=False),
        sa.Column('endpoint_url', sa.String(length=255), nullable=False),
        sa.CheckConstraint("provider = 'r2'", name='ck_media_storage_provider'),
        sa.PrimaryKeyConstraint('storage_id'),
        sa.UniqueConstraint('endpoint_url', 'bucket_name', name='uq_media_storage_bucket')
    )
    op.create_table('product_categories',
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('product_id', 'category_id')
    )
    op.create_index('ix_product_categories_category_product', 'product_categories', ['category_id', 'product_id'], unique=False)
    op.create_table('product_images',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('storage_id', sa.String(length=80), nullable=False),
        sa.Column('original_key', sa.String(length=255), nullable=False),
        sa.Column('thumbnail_key', sa.String(length=255), nullable=False),
        sa.Column('alt_text', sa.String(length=250), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.String(length=12), server_default='pending', nullable=False),
        sa.Column('replaces_image_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'ready', 'deleting', 'deleted')", name='ck_image_state'),
        sa.CheckConstraint('sort_order >= 0', name='ck_image_order'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['storage_id'], ['media_storage_locations.storage_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_product_images_cleanup', 'product_images', ['state', 'updated_at'], unique=False)
    op.create_index('ix_product_images_gallery', 'product_images', ['product_id', 'state', 'sort_order', 'id'], unique=False)
    op.create_table('product_variants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(length=80), nullable=False),
        sa.Column('size', sa.String(length=80), nullable=False),
        sa.Column('color', sa.String(length=80), nullable=False),
        sa.Column('size_key', sa.String(length=160), nullable=False),
        sa.Column('color_key', sa.String(length=160), nullable=False),
        sa.Column('stock_quantity', sa.Integer(), server_default='0', nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.CheckConstraint('stock_quantity >= 0', name='ck_variant_stock'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'size_key', 'color_key', name='uq_variant_size_color'),
        sa.UniqueConstraint('sku')
    )
    op.create_table('media_retirements',
        sa.Column('image_id', sa.Uuid(), nullable=False),
        sa.Column('storage_id', sa.String(length=80), nullable=False),
        sa.Column('delete_after', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['image_id'], ['product_images.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['storage_id'], ['media_storage_locations.storage_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('image_id', 'storage_id')
    )
    op.create_index(op.f('ix_media_retirements_delete_after'), 'media_retirements', ['delete_after'], unique=False)
    op.add_column('products', sa.Column('slug', sa.String(length=120), nullable=True))
    op.execute("UPDATE products SET slug = 'product-' || id")
    op.alter_column('products', 'slug', nullable=False)
    op.add_column('products', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('products', sa.Column('price_minor', sa.BigInteger(), nullable=True))
    op.add_column('products', sa.Column('currency', sa.String(length=3), nullable=True))
    op.add_column('products', sa.Column('status', sa.String(length=12), server_default='draft', nullable=False))
    op.add_column('products', sa.Column('first_published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('products', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('products', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.create_index('ix_products_status_price_id', 'products', ['status', 'price_minor', 'id'], unique=False)
    op.create_unique_constraint('uq_products_slug', 'products', ['slug'])
    op.create_check_constraint('ck_product_status', 'products', "status IN ('draft', 'active', 'archived')")
    op.create_check_constraint(
        'ck_product_price', 'products',
        "(price_minor IS NULL AND currency IS NULL) OR "
        "(price_minor IS NOT NULL AND price_minor BETWEEN 0 AND 999999999999 "
        "AND currency IS NOT NULL AND currency ~ '^[A-Z]{3}$')",
    )
    op.create_check_constraint(
        'ck_product_publish', 'products',
        "status <> 'active' OR (price_minor IS NOT NULL AND first_published_at IS NOT NULL)",
    )

    categories = sa.table(
        'categories', sa.column('kind', sa.String), sa.column('name', sa.String),
        sa.column('slug', sa.String), sa.column('sort_order', sa.Integer),
    )
    op.bulk_insert(categories, [
        {'kind': kind, 'name': name, 'slug': slug, 'sort_order': index}
        for kind, entries in (
            ('audience', [('Men', 'men'), ('Women', 'women'), ('Kids', 'kids')]),
            ('clothing_type', [
                ('T-shirts', 't-shirts'), ('Shirts', 'shirts'), ('Trousers', 'trousers'),
                ('Dresses', 'dresses'), ('Outerwear', 'outerwear'),
            ]),
        )
        for index, (name, slug) in enumerate(entries)
    ])


def downgrade() -> None:
    op.drop_constraint('ck_product_publish', 'products', type_='check')
    op.drop_constraint('ck_product_price', 'products', type_='check')
    op.drop_constraint('ck_product_status', 'products', type_='check')
    op.drop_constraint('uq_products_slug', 'products', type_='unique')
    op.drop_index('ix_products_status_price_id', table_name='products')
    op.drop_column('products', 'updated_at')
    op.drop_column('products', 'created_at')
    op.drop_column('products', 'first_published_at')
    op.drop_column('products', 'status')
    op.drop_column('products', 'currency')
    op.drop_column('products', 'price_minor')
    op.drop_column('products', 'description')
    op.drop_column('products', 'slug')
    op.drop_index(op.f('ix_media_retirements_delete_after'), table_name='media_retirements')
    op.drop_table('media_retirements')
    op.drop_table('product_variants')
    op.drop_index('ix_product_images_gallery', table_name='product_images')
    op.drop_index('ix_product_images_cleanup', table_name='product_images')
    op.drop_table('product_images')
    op.drop_index('ix_product_categories_category_product', table_name='product_categories')
    op.drop_table('product_categories')
    op.drop_table('media_storage_locations')
    op.drop_table('categories')
