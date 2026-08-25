"""xai historical estimates use visible call duration

Revision ID: b1a6d3e4f902
Revises: 9d2c4f6a1b7e
Create Date: 2026-08-25 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b1a6d3e4f902"
down_revision: Union[str, Sequence[str], None] = "9d2c4f6a1b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE calls
        SET cost_usd = ROUND((duration_seconds::numeric / 60.0) * 0.08, 4),
            cost_source = 'est_duration'
        WHERE voice_engine = 'xai_sip_direct'
          AND duration_seconds IS NOT NULL
          AND cost_in_usd_ticks IS NULL
          AND cost_source IN ('estimated', 'est_duration')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE calls
        SET cost_usd = ROUND((billable_audio_seconds::numeric / 60.0) * 0.08, 4),
            cost_source = 'estimated'
        WHERE voice_engine = 'xai_sip_direct'
          AND billable_audio_seconds IS NOT NULL
          AND cost_in_usd_ticks IS NULL
          AND cost_source = 'est_duration'
        """
    )
