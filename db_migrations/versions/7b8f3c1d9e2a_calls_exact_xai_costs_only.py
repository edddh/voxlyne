"""calls: exact xai costs only, remove ambiguous historical estimates

Revision ID: 7b8f3c1d9e2a
Revises: 5c4a9b7e1d2f
Create Date: 2026-08-25 11:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7b8f3c1d9e2a"
down_revision: Union[str, Sequence[str], None] = "5c4a9b7e1d2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE calls
        ADD COLUMN IF NOT EXISTS cost_in_usd_ticks BIGINT
        """
    )
    op.execute(
        """
        ALTER TABLE calls
        ADD COLUMN IF NOT EXISTS cost_source VARCHAR(16)
        """
    )
    op.execute(
        """
        UPDATE calls
        SET cost_usd = NULL,
            cost_source = NULL
        WHERE voice_engine = 'xai_sip_direct'
          AND cost_in_usd_ticks IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE calls
        DROP COLUMN IF EXISTS cost_source
        """
    )
    op.execute(
        """
        ALTER TABLE calls
        DROP COLUMN IF EXISTS cost_in_usd_ticks
        """
    )
