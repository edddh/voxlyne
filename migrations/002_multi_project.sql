-- Ascolta - Multi-Project Foundation
-- Milestone 2.1: Add multi-use-case support
--
-- This migration adds:
-- - projects: Different use cases (recruiting, lead gen, support, survey)
-- - settings: Global configuration key-value store
-- - records: Structured output (JSON + PDF) for each completed call
-- - metrics: Anonymous GDPR-compliant usage statistics
-- - project_id to calls: Link calls to projects

-- ===========================================
-- Projects Table
-- ===========================================
-- Supports multiple use cases with isolated configurations

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Project identity
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,  -- URL-friendly identifier (e.g., "candidate-screening-demo")
    type VARCHAR(50) NOT NULL CHECK (type IN ('recruiting', 'lead_gen', 'support', 'survey', 'other')),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,

    -- AI Configuration
    prompt_a TEXT NOT NULL,             -- Conversation prompt (interview questions)
    prompt_b TEXT NOT NULL,             -- Data extraction prompt (JSON schema)
    consent_message TEXT,               -- Custom GDPR consent message (NULL = use default)

    -- Voice settings
    voice_name VARCHAR(50) DEFAULT 'alloy',  -- OpenAI voice (alloy, echo, fable, onyx, nova, shimmer)
    language VARCHAR(10) DEFAULT 'it',       -- ISO 639-1 code (it, en, es, fr, de)

    -- Output configuration (JSONB for flexibility)
    output_config JSONB NOT NULL DEFAULT '{
        "pdf": {"enabled": true, "template": "default"},
        "email": {"enabled": false, "to": []},
        "webhook": {"enabled": false, "url": null}
    }',

    -- SIP routing (for multi-number setups)
    sip_number VARCHAR(50),             -- Zadarma number assigned to this project
    openai_project_id VARCHAR(100),     -- OpenAI project ID for SIP routing

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_projects_slug ON projects(slug);
CREATE INDEX idx_projects_type ON projects(type);
CREATE INDEX idx_projects_is_active ON projects(is_active);

-- Auto-update trigger for projects
CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Settings Table (Global Configuration)
-- ===========================================
-- Key-value store for system-wide settings

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Trigger for settings
CREATE OR REPLACE FUNCTION update_settings_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_settings_timestamp();

-- ===========================================
-- Records Table (Structured Output)
-- ===========================================
-- Stores JSON extraction and PDF reference for completed calls

CREATE TABLE IF NOT EXISTS records (
    id SERIAL PRIMARY KEY,
    call_id UUID NOT NULL UNIQUE REFERENCES calls(id) ON DELETE CASCADE,

    -- Structured data extracted via Prompt B
    json_data JSONB NOT NULL,           -- Flexible JSONB for any use case schema

    -- PDF storage
    pdf_key VARCHAR(255),               -- S3/MinIO object key (e.g., "pdfs/candidate-screening-demo/uuid.pdf")
    pdf_generated_at TIMESTAMP WITH TIME ZONE,

    -- Email tracking
    email_sent BOOLEAN DEFAULT FALSE,
    email_sent_at TIMESTAMP WITH TIME ZONE,
    email_to VARCHAR(255),

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_records_call_id ON records(call_id);
CREATE INDEX idx_records_email_sent ON records(email_sent);
CREATE INDEX idx_records_created_at ON records(created_at DESC);

-- Trigger for records
CREATE TRIGGER update_records_updated_at
    BEFORE UPDATE ON records
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Metrics Table (Anonymous GDPR Stats)
-- ===========================================
-- Aggregate metrics that survive hard deletes

CREATE TABLE IF NOT EXISTS _gdpr_metrics (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- Call statistics
    total_calls INTEGER DEFAULT 0,
    consented_calls INTEGER DEFAULT 0,
    declined_calls INTEGER DEFAULT 0,
    cancelled_calls INTEGER DEFAULT 0,      -- User pressed DTMF "9"
    completed_calls INTEGER DEFAULT 0,

    -- Performance metrics
    avg_duration_seconds NUMERIC(10,2),
    avg_consent_time_seconds NUMERIC(10,2),

    -- Updated timestamp
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(date)
);

CREATE INDEX idx_metrics_date ON _gdpr_metrics(date DESC);

-- ===========================================
-- Alter Calls Table: Add project_id
-- ===========================================
-- Link calls to projects (NULL = default project)

ALTER TABLE calls
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_calls_project_id ON calls(project_id);

-- ===========================================
-- Seed Default Project: Candidate Screening Demo
-- ===========================================

-- Insert default project
INSERT INTO projects (
    name,
    slug,
    type,
    description,
    prompt_a,
    prompt_b,
    consent_message,
    voice_name,
    language,
    output_config,
    is_active
) VALUES (
    'Candidate Screening Demo',
    'candidate-screening-demo',
    'recruiting',
    'Synthetic phone screening example for fictional job candidates',

    -- PROMPT A: Conversation (from original implementation)
    'Sei un recruiter AI professionale che conduce colloqui telefonici in italiano per un''organizzazione fittizia.

FASE 1: CONSENSO GDPR
All''inizio della chiamata, chiedi SEMPRE il consenso:
"Buongiorno! Sono l''assistente AI della demo. Prima di procedere con il colloquio, ho bisogno del suo consenso per registrare e trattare i dati forniti nella simulazione. Acconsente a procedere con questa intervista? Può rispondere semplicemente ''sì'' o ''no''."

Se l''utente dice "sì" o equivalente → procedi con FASE 2
Se l''utente dice "no" o equivalente → rispondi "Capisco, grazie per il suo tempo. Buona giornata!" e termina

DIRITTO DI CANCELLAZIONE:
Se durante la conversazione l''utente dice frasi come "cancella i miei dati", "elimina tutto", "voglio cancellare" o preme il tasto 9 sul telefono:
- Conferma immediatamente: "Certamente, cancellerò tutti i suoi dati immediatamente."
- Termina la chiamata (il sistema si occuperà della cancellazione automatica)

FASE 2: COLLOQUIO
Dopo aver ottenuto il consenso, conduci un colloquio professionale ma cordiale.

Domande da porre (adatta il flusso in base alle risposte):
1. "Può dirmi il suo nome completo?"
2. "Quali sono le sue esperienze lavorative più rilevanti nel settore delle costruzioni o dell''ingegneria?"
3. "Ha mai lavorato su grandi progetti infrastrutturali? Se sì, quali?"
4. "Quali competenze tecniche potrebbero essere utili per questo ruolo?"
5. "Perché è interessato a questa opportunità?"
6. "Ha disponibilità per trasferte nazionali o internazionali?"
7. "Qual è la sua disponibilità di inizio lavoro?"

STILE:
- Professionale ma empatico
- Ascolta attivamente, fai domande di approfondimento
- Non interrompere il candidato
- Concludi con: "Grazie per il suo tempo! Riceverà un riscontro entro 5 giorni lavorativi. Buona giornata!"

NOTE TECNICHE:
- Parla in modo naturale, come un vero recruiter
- Gestisci interruzioni e richieste di chiarimento
- Se il candidato va fuori tema, riporta gentilmente la conversazione sul tracciato
- Non chiedere informazioni sensibili (etnia, religione, orientamento sessuale, dati sensibili)
- Durata target: 5-8 minuti',

    -- PROMPT B: Data Extraction
    'Analizza la trascrizione del colloquio telefonico e genera un JSON strutturato con le informazioni del candidato.

IMPORTANTE: Rispondi SOLO con JSON valido, senza testo aggiuntivo.

Schema JSON richiesto:
{
  "candidate_name": "Nome completo del candidato (string, required)",
  "phone_number": "Numero di telefono (string, from metadata)",
  "email": "Email se menzionata (string, nullable)",

  "role_targets": ["Lista di ruoli/posizioni di interesse (array of strings)"],
  "seniority_estimate": "junior|mid|senior|expert (basato su esperienza descritta)",

  "experience_summary": "Sintesi dell''esperienza lavorativa in 2-3 frasi (string, max 500 chars)",

  "relevant_projects": [
    {
      "project_name": "Nome progetto/azienda",
      "role": "Ruolo ricoperto",
      "duration_estimate": "Stima durata (es: 2 anni, 6 mesi)",
      "key_activities": "Attività principali svolte"
    }
  ],

  "hard_skills": ["Lista di competenze tecniche concrete (array of strings)"],
  "soft_skills": ["Competenze trasversali emerse (array of strings)"],

  "availability": {
    "willing_to_relocate": true/false,
    "willing_to_travel": true/false,
    "start_date_estimate": "Disponibilità inizio (string, nullable)"
  },

  "motivations": "Motivazioni per candidarsi (string, max 300 chars)",

  "red_flags": ["Eventuali criticità emerse (array of strings, può essere vuoto)"],

  "overall_fit_score": 1-10 (intero, valutazione complessiva idoneità),
  "recruiter_notes": "Note libere del sistema AI per il recruiter umano (string, max 500 chars)"
}

REGOLE DI ESTRAZIONE:
1. Usa SOLO informazioni presenti nella trascrizione
2. Se un campo non ha informazioni, usa null (per stringhe/oggetti) o [] (per array)
3. Non inventare dati
4. Sii conservativo nelle valutazioni (overall_fit_score)
5. Per red_flags, segnala solo evidenze concrete (es: "Non disponibile a trasferte ma ruolo richiede mobilità")
6. Le date/durate sono stime basate su quanto detto dal candidato
7. Rispondi SOLO con il JSON, nessun testo prima o dopo

Esempio di output:
{
  "candidate_name": "Andrea Rinaldi",
  "phone_number": "+39 000 000 0000",
  "email": null,
  "role_targets": ["Site Manager", "Project Engineer"],
  "seniority_estimate": "senior",
  "experience_summary": "Esperienza in progetti tecnici complessi, con responsabilita di coordinamento e gestione fornitori.",
  "relevant_projects": [
    {
      "project_name": "Progetto dimostrativo Alpha",
      "role": "Coordinatore operativo",
      "duration_estimate": "2 anni",
      "key_activities": "Coordinamento attivita, fornitori e avanzamento lavori"
    }
  ],
  "hard_skills": ["Project Management", "Pianificazione", "Coordinamento fornitori"],
  "soft_skills": ["Leadership", "Problem solving", "Gestione team"],
  "availability": {
    "willing_to_relocate": true,
    "willing_to_travel": true,
    "start_date_estimate": "2 mesi preavviso"
  },
  "motivations": "Interessato a un ruolo con responsabilita operative e opportunita di crescita",
  "red_flags": [],
  "overall_fit_score": 8,
  "recruiter_notes": "Profilo coerente con un colloquio tecnico di approfondimento."
}',

    -- Consent message (NULL = use default from code)
    NULL,

    -- Voice and language
    'alloy',
    'it',

    -- Output config
    '{
        "pdf": {
            "enabled": true,
            "template": "candidate"
        },
        "email": {
            "enabled": false,
            "to": ["recruiting@example.test"]
        },
        "webhook": {
            "enabled": false,
            "url": null
        }
    }'::jsonb,

    TRUE
) ON CONFLICT (slug) DO NOTHING;

-- Seed initial settings
INSERT INTO settings (key, value, description) VALUES
    ('system_name', 'Ascolta', 'Application name'),
    ('default_project_slug', 'candidate-screening-demo', 'Default project for calls without SIP routing'),
    ('max_call_duration_seconds', '900', 'Maximum call duration (15 minutes)'),
    ('silence_timeout_seconds', '5', 'Silence before ending call'),
    ('dtmf_cancel_key', '9', 'DTMF key for immediate cancellation')
ON CONFLICT (key) DO NOTHING;

-- Initialize metrics for today
INSERT INTO _gdpr_metrics (date, total_calls, consented_calls, declined_calls, cancelled_calls, completed_calls)
VALUES (CURRENT_DATE, 0, 0, 0, 0, 0)
ON CONFLICT (date) DO NOTHING;
