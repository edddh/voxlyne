"""projects: custom variable schema and values

Revision ID: e5e14da0c6e3
Revises: 524f1b231172
Create Date: 2026-08-19 12:08:46.731654

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5e14da0c6e3'
down_revision: Union[str, Sequence[str], None] = '524f1b231172'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer, 20/08: "ora nei prompt Appointment Demo, comune di exampleville e
voxlyne ci sono dei tag che andrebbero collegati a dei campi o
attivi (come data e ora) oppure custom. inoltre il template dovrebbe
avere dei campi custom che chiede di riempire quando si effettua
l'importazione e che possono poi essere modificati successivamente."

Two kinds of {{tag}} in a prompt, now distinguished by naming
convention rather than storage:
- {{system__xxx}} (e.g. {{system__caller_id}}, already used and
  working - see runtime_workers/provision_elevenlabs.py) - resolved by
  the voice PROVIDER itself at call time (ElevenLabs' and xAI's
  realtime APIs both understand this convention natively). Voxlyne never
  touches these - confirmed by grepping the whole codebase for any
  substitution logic before this, there is none.
- {{anything_else}} (e.g. {{comune}}, {{nome_contatto}}) - a per-project
  CUSTOM variable Voxlyne itself substitutes, using these two new
  columns.

custom_variables_schema: what fields exist (on a template: what a new
project cloned from it should ask for; copied as-is into every project
created from that template - same set of fields, just a different
value per project). A JSON array of {key, label, description, default}.
custom_variables: the actual values for THIS project (or the
template's own example/default values, on a template row). A flat
{key: value} object.

Substitution happens once, at publish_version() time (app/services/
agent_versions.py) - the published agent_versions snapshot gets the
literal substituted text, prompt_a/prompt_b/consent_message on the
`projects` row keep the {{key}} markers forever so a custom_variables
value can be edited later (Projects tab UI) without touching the
prompt text, and republishing (not resaving the draft) is what applies
a changed value to real calls - same draft/publish mental model already
used for prompt edits.
"""


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN custom_variables_schema JSONB NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE projects ADD COLUMN custom_variables JSONB NOT NULL DEFAULT '{}'")
    # agent_versions snapshots need the same value-holding column too -
    # not the schema (a published version is a frozen point in time, it
    # doesn't need to know what fields COULD be edited, only what the
    # substitution used) - kept here for audit/debugging (what values
    # produced this exact published prompt).
    op.execute("ALTER TABLE agent_versions ADD COLUMN custom_variables JSONB NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_versions DROP COLUMN IF EXISTS custom_variables")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS custom_variables")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS custom_variables_schema")
