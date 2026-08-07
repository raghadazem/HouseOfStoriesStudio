"""approval record revision ordering

Revision ID: 1017c6c7ae38
Revises: 8ed8cbd56eee
Create Date: 2026-08-07 20:55:03.912240

Adds ``approval_records.revision``: a monotonically increasing integer,
scoped per ``(entity_type, entity_id)``, that is now the authoritative
answer to "which decision on this entity is current" (see
``app/core/services/approval_service.py::get_current_approval_state``).
Previously that question was answered by ``ORDER BY decided_at DESC``
alone, which is not deterministic — two decisions recorded close enough
together can land on the same wall-clock timestamp. See
``docs/engineering/WINDOWS_DEVELOPMENT.md`` for the full writeup.

Three steps, in order, so existing rows never violate the new
constraints partway through:

1. Add ``revision`` as nullable (no data yet).
2. Backfill every existing ``(entity_type, entity_id)`` group in
   ``decided_at`` order (falling back to ``id`` as a stable tiebreaker
   for rows that already share a timestamp — the exact scenario this
   migration exists to stop happening going forward) with 1, 2, 3, ...
3. Make the column NOT NULL and add the uniqueness constraint.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1017c6c7ae38'
down_revision: Union[str, None] = '8ed8cbd56eee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A minimal Core (not ORM) view of the table, deliberately re-declared
# here rather than importing app.core.models.approval.ApprovalRecord —
# a migration must stay valid against the schema as it existed at this
# point in the migration chain, independent of how the model evolves
# afterward.
_approval_records = sa.table(
    "approval_records",
    sa.column("id", sa.Uuid()),
    sa.column("entity_type", sa.String()),
    sa.column("entity_id", sa.Uuid()),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("revision", sa.Integer()),
)


def upgrade() -> None:
    with op.batch_alter_table('approval_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('revision', sa.Integer(), nullable=True))

    _backfill_revisions()

    with op.batch_alter_table('approval_records', schema=None) as batch_op:
        batch_op.alter_column('revision', existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint(
            'uq_approval_records_entity_revision', ['entity_type', 'entity_id', 'revision']
        )


def downgrade() -> None:
    with op.batch_alter_table('approval_records', schema=None) as batch_op:
        batch_op.drop_constraint('uq_approval_records_entity_revision', type_='unique')
        batch_op.drop_column('revision')


def _backfill_revisions() -> None:
    """Assign 1, 2, 3, ... per (entity_type, entity_id), oldest first.

    ``decided_at`` is the best (only) ordering information that exists
    for pre-existing rows — imperfect exactly because it can tie, but
    the ``id`` tiebreaker below still gives every row a distinct,
    reproducible revision even when it does. Going forward, new rows
    never rely on this: ``ApprovalService._record`` assigns a real
    monotonic revision at insert time.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _approval_records.c.id,
            _approval_records.c.entity_type,
            _approval_records.c.entity_id,
        ).order_by(
            _approval_records.c.entity_type,
            _approval_records.c.entity_id,
            _approval_records.c.decided_at,
            _approval_records.c.id,
        )
    ).all()

    next_revision: dict[tuple[str, object], int] = {}
    for row in rows:
        key = (row.entity_type, row.entity_id)
        next_revision[key] = next_revision.get(key, 0) + 1
        bind.execute(
            _approval_records.update()
            .where(_approval_records.c.id == row.id)
            .values(revision=next_revision[key])
        )
