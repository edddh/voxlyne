"""calls session_model for configurable voice pricing

Revision ID: 9d2c4f6a1b7e
Revises: 7b8f3c1d9e2a
Create Date: 2026-08-25 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "9d2c4f6a1b7e"
down_revision: Union[str, Sequence[str], None] = "7b8f3c1d9e2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE calls
        ADD COLUMN IF NOT EXISTS session_model VARCHAR(100)
        """
    )
    op.execute(
        """
        UPDATE calls
        SET session_model = 'grok-voice-latest'
        WHERE voice_engine = 'xai_sip_direct'
          AND session_model IS NULL
        """
    )
    op.execute(
        """
        UPDATE calls
        SET cost_usd = ROUND((billable_audio_seconds::numeric / 60.0) * 0.08, 4),
            cost_source = 'estimated'
        WHERE voice_engine = 'xai_sip_direct'
          AND billable_audio_seconds IS NOT NULL
          AND cost_in_usd_ticks IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE calls
        DROP COLUMN IF EXISTS session_model
        """
    )
