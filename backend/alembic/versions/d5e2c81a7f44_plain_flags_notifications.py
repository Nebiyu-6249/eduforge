"""plain flag messages and read notifications

`validation_flag.plain_message` holds the problem written for a teacher, so the
UI never has to show a rule id or a JSON Pointer. `notification_read` records
which dashboard notifications a teacher has already seen.

Revision ID: d5e2c81a7f44
Revises: c4b1f07a9d2e
Create Date: 2026-11-07 16:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5e2c81a7f44'
down_revision: str | Sequence[str] | None = 'c4b1f07a9d2e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('validation_flag', sa.Column('plain_message', sa.Text(), nullable=True))
    op.create_table(
        'notification_read',
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('faculty_id', 'key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('notification_read')
    op.drop_column('validation_flag', 'plain_message')
