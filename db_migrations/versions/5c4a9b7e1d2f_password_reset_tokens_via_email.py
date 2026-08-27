"""password reset tokens via email

Revision ID: 5c4a9b7e1d2f
Revises: e5e14da0c6e3
Create Date: 2026-08-25 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5c4a9b7e1d2f"
down_revision: Union[str, Sequence[str], None] = "e5e14da0c6e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
        ON password_reset_tokens(user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires
        ON password_reset_tokens(expires_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
