"""wildchat corpus (pgvector)

Revision ID: a1b2c3d4e5f6
Revises: 253ee575f924
Create Date: 2026-06-12 10:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "253ee575f924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # HNSW + trigram indexes are built by PgCorpusStore after the lazy bulk-ingest, not here.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "wildchat_corpus",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("length_mode", sa.String(length=32), nullable=True),
        sa.Column("domain", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wildchat_corpus_lang", "wildchat_corpus", ["lang"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_wildchat_corpus_lang", table_name="wildchat_corpus")
    op.drop_table("wildchat_corpus")
