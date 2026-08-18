"""calls: colonna xai_call_id per il worker xAI SIP diretto

Revision ID: ab11d01c42f3
Revises: ff22cc041e56
Create Date: 2026-08-18 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab11d01c42f3'
down_revision: Union[str, Sequence[str], None] = 'ff22cc041e56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer (18/08): "ma la trascrizione delle telefonate e gli analytics
sono a posto?" - la risposta era no, per il percorso xAI diretto
(l'unico verificato localmente finora): runtime_workers/realtime_service.py
non scriveva mai una riga in `calls`, mai una trascrizione, mai
agganciava il post-processing - solo la sessione audio dal vivo, nessuna
integrazione con lo strato dati di Ascolta. La simulazione di test di stasera
su Exampleville non ha lasciato traccia nel DB.

Stesso pattern di vapi_call_id/twilio_call_sid/elevenlabs_conversation_id
gia' presenti sulla stessa tabella - un id esterno per provider, non un
campo generico riusato con un nome fuorviante.
"""


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN xai_call_id VARCHAR(255)")
    op.execute("CREATE INDEX idx_calls_xai_call_id ON calls (xai_call_id) WHERE xai_call_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calls_xai_call_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS xai_call_id")
