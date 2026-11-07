"""grounding note on a generation request

Why retrieval grounded a batch of drafts, or why it could not, in one
sentence, so Draft Studio can explain an ungrounded draft instead of only
badging it.

Revision ID: c4b1f07a9d2e
Revises: 1148ac12ba14
Create Date: 2026-11-07 14:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4b1f07a9d2e'
down_revision: str | Sequence[str] | None = '1148ac12ba14'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('generation_request', sa.Column('grounding_note', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('generation_request', 'grounding_note')
