"""Aggiunge service_type 'llm' per credenziali embedding RAG

Revision ID: e1cc4132c384
Revises: acfbe417a42a
Create Date: 2026-08-18 19:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1cc4132c384'
down_revision: Union[str, Sequence[str], None] = 'acfbe417a42a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
app/services/rag/embeddings.py resolve_embedding_api_key() vuole
service_type='llm', provider='openai' - service_credentials aveva un
CHECK che ammetteva solo ('crm','voice','telephony','tts','calendar');
la RAG e' un tipo di credenziale nuovo, non uno dei precedenti riusato a
forza (un embedding non e' una voce, ne' un CRM).
"""


def upgrade() -> None:
    op.execute("ALTER TABLE service_credentials DROP CONSTRAINT service_credentials_service_type_check")
    op.execute(
        """
        ALTER TABLE service_credentials ADD CONSTRAINT service_credentials_service_type_check
        CHECK (service_type IN ('crm', 'voice', 'telephony', 'tts', 'calendar', 'llm'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE service_credentials DROP CONSTRAINT service_credentials_service_type_check")
    op.execute(
        """
        ALTER TABLE service_credentials ADD CONSTRAINT service_credentials_service_type_check
        CHECK (service_type IN ('crm', 'voice', 'telephony', 'tts', 'calendar'))
        """
    )
