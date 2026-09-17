"""Track browser voice simulations separately from production calls."""

from typing import Sequence, Union

from alembic import op


revision: str = "2f8a1c7d4e90"
down_revision: Union[str, Sequence[str], None] = "9d2c4f6a1b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS origin VARCHAR(32) NOT NULL DEFAULT 'production'")
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS channel VARCHAR(32)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_calls_origin ON calls(origin)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calls_origin")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS channel")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS origin")
