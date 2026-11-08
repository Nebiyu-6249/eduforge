"""background work a teacher can leave, and quizzes that exist while they are written

A job now carries what the activity panel shows: a title in the teacher's own
words, the course it belongs to, the page to open when it finishes, how long is
left, and how big it is (so past jobs of the same size can estimate a new one).

An assessment form gains the `writing` status, the job writing it, and a plain
reason when it could not be finished.

Revision ID: e7c3a91b2d58
Revises: d5e2c81a7f44
Create Date: 2026-11-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e7c3a91b2d58'
down_revision: str | Sequence[str] | None = 'd5e2c81a7f44'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('job', schema=None) as b:
        b.add_column(sa.Column('title', sa.String(length=200), nullable=True))
        b.add_column(sa.Column('course_version_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('link', sa.String(length=300), nullable=True))
        b.add_column(sa.Column('eta_seconds', sa.Integer(), nullable=True))
        b.add_column(sa.Column('size', sa.Integer(), nullable=True))
        b.create_index('ix_job_course_version_id', ['course_version_id'])
        b.create_foreign_key('fk_job_course_version', 'course_version', ['course_version_id'], ['id'])

    with op.batch_alter_table('assessment_form', schema=None) as b:
        b.add_column(sa.Column('job_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('error', sa.Text(), nullable=True))
        b.create_foreign_key('fk_assessment_form_job', 'job', ['job_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('assessment_form', schema=None) as b:
        b.drop_constraint('fk_assessment_form_job', type_='foreignkey')
        b.drop_column('error')
        b.drop_column('job_id')

    with op.batch_alter_table('job', schema=None) as b:
        b.drop_constraint('fk_job_course_version', type_='foreignkey')
        b.drop_index('ix_job_course_version_id')
        b.drop_column('size')
        b.drop_column('eta_seconds')
        b.drop_column('link')
        b.drop_column('course_version_id')
        b.drop_column('title')
