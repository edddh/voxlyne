# migrations/ — congelata, sostituita da Alembic

Questa cartella contiene i 12 file SQL già applicati al database reale tramite
il runner legacy (`run-migrations.sh`, tabella di tracciamento `_migrations`).
Sono la storia di come lo schema è arrivato allo stato attuale.

**Da qui in avanti non si aggiungono più file qui.** Ogni nuova modifica allo
schema passa da Alembic:

```bash
.venv/bin/alembic revision -m "descrizione della modifica"
# scrivi upgrade()/downgrade() nel file generato in db_migrations/versions/
.venv/bin/alembic upgrade head
```

Perché il cambio: due coppie di file con lo stesso numero (`002_duration_generated_column.sql`/
`002_multi_project.sql`, `006_template_system.sql`/`006_voice_engine.sql`) erano
ordinate solo dall'ordinamento alfabetico del glob shell, non da una sequenza
dichiarata — fragile, e il tipo di bug già ritrovato indipendentemente anche
in altre due codebase durante l'analisi comparativa (vedi `docs/adr/`).

**Non rinumerare o rinominare questi file**: `_migrations` li traccia per nome
esatto, e `run-migrations.sh` li rieseguirebbe se il nome cambiasse. Restano
così, per sempre, come sono stati applicati.

Vedi `db_migrations/versions/f747b97a60bd_*.py` per il punto esatto in cui
Alembic prende il controllo (stamp, non replay).
