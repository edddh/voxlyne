"""calls: track billable audio seconds and cost

Revision ID: 524f1b231172
Revises: a3905808ab22
Create Date: 2026-08-19 11:10:48.939540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '524f1b231172'
down_revision: Union[str, Sequence[str], None] = 'a3905808ab22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer, 20/08 (dopo la revisione della demo con collaborator): "next step" -
costi per chiamata nel dettaglio, poi aggregati in dashboard, per capire
quanto costano davvero le chiamate di prova sul Comune di Exampleville.

Nessuna piattaforma esponeva questo dato prima - verificato in un test
live diretto contro l'API realtime di xAI (non supposto): ogni evento
response.done porta un oggetto usage.billable_audio_seconds (i secondi
di audio effettivamente fatturati per quella risposta, un numero intero
gia' arrotondato da xAI per il billing - non output_audio_seconds, che
e' il valore float non arrotondato). Sommando questo campo su tutte le
risposte di una chiamata e moltiplicando per la tariffa pubblica
confermata (docs.x.ai/docs/models: grok-voice-think-fast-2.0 = l'alias
"grok-voice-latest" da 5/8/2026, $0.08/min audio; + $0.01/min se il
numero e' provisionato tramite xAI, fonte: aipricing.guru/xai-pricing)
si ottiene un costo reale, non una stima a spanne.

billable_audio_seconds: accumulato lato server (realtime_service.py::
run_call, un incremento per ogni response.done) - il dato grezzo da cui
si puo' sempre ricalcolare il costo se la tariffa cambia.
cost_usd: il costo calcolato al momento della finalizzazione della
chiamata con la tariffa corrente (app/services/pricing.py) - congelato
li' cosi' una chiamata vecchia non cambia prezzo retroattivamente se la
tariffa viene aggiornata in futuro.
"""


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN billable_audio_seconds INTEGER")
    op.execute("ALTER TABLE calls ADD COLUMN cost_usd NUMERIC(10, 4)")


def downgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS cost_usd")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS billable_audio_seconds")
