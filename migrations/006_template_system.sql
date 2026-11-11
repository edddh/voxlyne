-- Ascolta - Template System + Project-Level Configuration
-- Milestone M4+: Template System, Project Config, Prompt Composer
--
-- This migration adds:
-- - Template system (global templates assigned to tenants)
-- - Prompt composer blocks (reusable prompt building blocks)
-- - Project-level SIP configuration
-- - Project-level CRM configuration (moving from global)
-- - Project-level Calendar configuration (moving from global)
-- - Prompt placeholders (configurable phrases instead of hardcoded)

-- ============================================
-- TEMPLATE SYSTEM
-- ============================================

-- Distingue template da progetti live
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_template BOOLEAN DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS from_template_id UUID REFERENCES projects(id);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS template_category VARCHAR(50); -- recruiting, sales, support, survey

COMMENT ON COLUMN projects.is_template IS 'TRUE if this is a global template (super_admin only), FALSE if live project';
COMMENT ON COLUMN projects.from_template_id IS 'Reference to template used to create this project (NULL if created from scratch)';
COMMENT ON COLUMN projects.template_category IS 'Category for templates: recruiting, sales, support, survey, other';

-- Template assignments (super_admin → tenant)
CREATE TABLE IF NOT EXISTS template_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE,
    assigned_by UUID REFERENCES users(id),
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(template_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_template_assignments_template ON template_assignments(template_id);
CREATE INDEX IF NOT EXISTS idx_template_assignments_tenant ON template_assignments(tenant_id);

COMMENT ON TABLE template_assignments IS 'Tracks which templates are assigned to which tenants (super_admin only)';
COMMENT ON COLUMN template_assignments.is_active IS 'If FALSE, tenant can no longer see/use this template';

-- ============================================
-- PROMPT COMPOSER BLOCKS
-- ============================================

-- Building blocks for the prompt composer (from the frontend starter)
CREATE TABLE IF NOT EXISTS prompt_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL = global (super_admin)
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('personality', 'rules', 'domain', 'custom')),
    content TEXT NOT NULL,
    is_public BOOLEAN DEFAULT FALSE, -- Se true, visibile a tutti i tenant
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_blocks_tenant ON prompt_blocks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_prompt_blocks_category ON prompt_blocks(category);
CREATE INDEX IF NOT EXISTS idx_prompt_blocks_public ON prompt_blocks(is_public) WHERE is_public = TRUE;

COMMENT ON TABLE prompt_blocks IS 'Reusable building blocks for prompt composer (personality, rules, domain knowledge)';
COMMENT ON COLUMN prompt_blocks.tenant_id IS 'NULL = global block (super_admin), UUID = tenant-specific block';
COMMENT ON COLUMN prompt_blocks.is_public IS 'If TRUE, this block is visible to all tenants (super_admin only)';
COMMENT ON COLUMN prompt_blocks.category IS 'personality (coach/mentor), rules (socratic/feedback), domain (sales/negotiation), custom';

-- ============================================
-- PROJECT-LEVEL CONFIGURATION
-- ============================================

-- SIP configuration per progetto
ALTER TABLE projects ADD COLUMN IF NOT EXISTS sip_address VARCHAR(255); -- e.g. sip:demo@sip.example.test
ALTER TABLE projects ADD COLUMN IF NOT EXISTS sip_username VARCHAR(100);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS sip_password_encrypted TEXT;

COMMENT ON COLUMN projects.sip_address IS 'SIP address for incoming calls (e.g., sip:demo@sip.example.test)';
COMMENT ON COLUMN projects.sip_username IS 'SIP authentication username';
COMMENT ON COLUMN projects.sip_password_encrypted IS 'Encrypted SIP password (Fernet encryption)';

-- Sposta CRM config da globale a per-progetto
CREATE TABLE IF NOT EXISTS project_crm_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE UNIQUE,
    enabled BOOLEAN DEFAULT FALSE,
    provider VARCHAR(50) NOT NULL CHECK (provider IN ('hubspot', 'salesforce', 'webhook')),

    -- HubSpot
    hubspot_api_key_encrypted TEXT,
    hubspot_portal_id VARCHAR(50),

    -- Generic webhook
    webhook_url TEXT,
    webhook_secret_encrypted TEXT,

    -- Config
    config JSONB DEFAULT '{}', -- pipeline, stage, field mapping
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_crm_config_project ON project_crm_config(project_id);

COMMENT ON TABLE project_crm_config IS 'Project-level CRM configuration (replaces global config from settings)';
COMMENT ON COLUMN project_crm_config.enabled IS 'If FALSE, no CRM sync for this project';
COMMENT ON COLUMN project_crm_config.hubspot_api_key_encrypted IS 'Encrypted HubSpot private app API key';
COMMENT ON COLUMN project_crm_config.config IS 'Additional config: pipeline_id, stage_id, field mappings, etc.';

-- Sposta Calendar config da globale a per-progetto
CREATE TABLE IF NOT EXISTS project_calendar_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE UNIQUE,
    enabled BOOLEAN DEFAULT FALSE,
    provider VARCHAR(50) NOT NULL CHECK (provider IN ('google', 'microsoft')),

    -- OAuth tokens (encrypted)
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    expires_at TIMESTAMP WITH TIME ZONE,

    -- Calendar settings
    calendar_id VARCHAR(255) DEFAULT 'primary',
    timezone VARCHAR(50) DEFAULT 'Europe/Rome',

    -- Config
    config JSONB DEFAULT '{}', -- working hours, slot duration, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_calendar_config_project ON project_calendar_config(project_id);

COMMENT ON TABLE project_calendar_config IS 'Project-level calendar OAuth configuration (replaces global config)';
COMMENT ON COLUMN project_calendar_config.enabled IS 'If FALSE, no calendar integration for this project';
COMMENT ON COLUMN project_calendar_config.access_token_encrypted IS 'Encrypted OAuth access token';
COMMENT ON COLUMN project_calendar_config.refresh_token_encrypted IS 'Encrypted OAuth refresh token';
COMMENT ON COLUMN project_calendar_config.config IS 'Working hours, slot duration, blackout dates, etc.';

-- ============================================
-- PROMPT CONFIGURATION
-- ============================================

-- Placeholder configurabili per prompt (invece di hardcode in config.py)
CREATE TABLE IF NOT EXISTS prompt_placeholders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Frasi configurabili
    cancel_phrase TEXT DEFAULT 'Va bene, procedo con la cancellazione della telefonata.',
    cancellation_confirmation TEXT DEFAULT 'Cancellazione dei dati della telefonata eseguita.',
    goodbye_phrase TEXT DEFAULT 'Le auguro una buona giornata! Arrivederci.',

    -- Intent configuration (JSONB per flessibilità futura)
    intent_config JSONB DEFAULT '{
        "calendar_keywords": ["appuntamento", "colloquio", "incontro"],
        "cancel_keywords": ["cancella", "elimina", "rimuovi"],
        "confirm_keywords": ["sì", "si", "va bene", "ok", "certo"]
    }',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(project_id)
);

CREATE INDEX IF NOT EXISTS idx_prompt_placeholders_project ON prompt_placeholders(project_id);

COMMENT ON TABLE prompt_placeholders IS 'Configurable phrases for prompts (replaces hardcoded strings in realtime_session.py)';
COMMENT ON COLUMN prompt_placeholders.cancel_phrase IS 'What AI says when user presses DTMF 9 to cancel';
COMMENT ON COLUMN prompt_placeholders.cancellation_confirmation IS 'Confirmation message after data deletion';
COMMENT ON COLUMN prompt_placeholders.goodbye_phrase IS 'Farewell message at end of call';
COMMENT ON COLUMN prompt_placeholders.intent_config IS 'Keywords for intent detection (calendar, cancel, confirm) - future NLU integration';

-- ============================================
-- UPDATE TRIGGERS
-- ============================================

-- Update trigger for prompt_blocks
CREATE OR REPLACE FUNCTION update_prompt_blocks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_prompt_blocks_updated_at
BEFORE UPDATE ON prompt_blocks
FOR EACH ROW
EXECUTE FUNCTION update_prompt_blocks_updated_at();

-- Update trigger for project_crm_config
CREATE OR REPLACE FUNCTION update_project_crm_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_project_crm_config_updated_at
BEFORE UPDATE ON project_crm_config
FOR EACH ROW
EXECUTE FUNCTION update_project_crm_config_updated_at();

-- Update trigger for project_calendar_config
CREATE OR REPLACE FUNCTION update_project_calendar_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_project_calendar_config_updated_at
BEFORE UPDATE ON project_calendar_config
FOR EACH ROW
EXECUTE FUNCTION update_project_calendar_config_updated_at();

-- Update trigger for prompt_placeholders
CREATE OR REPLACE FUNCTION update_prompt_placeholders_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_prompt_placeholders_updated_at
BEFORE UPDATE ON prompt_placeholders
FOR EACH ROW
EXECUTE FUNCTION update_prompt_placeholders_updated_at();

-- ============================================
-- SEED DATA: Default Prompt Blocks
-- ============================================

-- Global personality blocks (tenant_id = NULL, is_public = TRUE)
INSERT INTO prompt_blocks (tenant_id, name, category, content, is_public, created_by) VALUES
(NULL, 'Empathetic Coach', 'personality', 'You are an empathetic coach who listens carefully and asks powerful questions. You create a safe space for reflection and growth. Your approach is supportive, non-judgmental, and focused on helping people discover their own insights.', TRUE, NULL),
(NULL, 'Experienced Mentor', 'personality', 'You are an experienced mentor who shares practical wisdom from years of experience. You offer different perspectives and help people see blind spots. Your style is direct but caring, combining tough love with genuine support.', TRUE, NULL),
(NULL, 'Energetic Trainer', 'personality', 'You are an energetic trainer focused on action and concrete results. You motivate people to push beyond their comfort zone and celebrate small wins. Your communication is clear, enthusiastic, and results-oriented.', TRUE, NULL)
ON CONFLICT DO NOTHING;

-- Global rules blocks
INSERT INTO prompt_blocks (tenant_id, name, category, content, is_public, created_by) VALUES
(NULL, 'Italian Conversation', 'rules', 'Speak in Italian. Keep responses concise (2-3 sentences max). Use professional but warm language. Avoid jargon unless the user uses it first.', TRUE, NULL),
(NULL, 'Socratic Method', 'rules', 'Use the Socratic method: ask questions instead of giving direct answers. Help the person discover insights through guided reflection. Follow up with "What else?" and "Tell me more about that."', TRUE, NULL),
(NULL, 'Structured Feedback', 'rules', 'Give feedback in 4 steps: (1) What went well? (2) What could improve? (3) Specific action to try next time (4) Check understanding with "Does this resonate with you?"', TRUE, NULL)
ON CONFLICT DO NOTHING;

-- Global domain blocks
INSERT INTO prompt_blocks (tenant_id, name, category, content, is_public, created_by) VALUES
(NULL, 'Consultative Selling', 'domain', 'Focus on understanding customer needs before presenting solutions. Ask about pain points, budget, timeline, and decision process. Handle objections with empathy and reframe them as opportunities to clarify value. Close with a clear next step.', TRUE, NULL),
(NULL, 'Negotiation Skills', 'domain', 'Prepare your BATNA (Best Alternative To Negotiated Agreement). Identify shared interests beyond positions. Use anchoring strategically. Look for win-win solutions. Separate people from problems.', TRUE, NULL),
(NULL, 'Leadership Development', 'domain', 'Develop leadership through: delegation (give ownership not tasks), feedback (timely and specific), coaching (ask don''t tell), and change management (communicate the why, involve people early).', TRUE, NULL)
ON CONFLICT DO NOTHING;

-- ============================================
-- BACKWARD COMPATIBILITY
-- ============================================

-- For existing projects without placeholders, create default entries
INSERT INTO prompt_placeholders (project_id)
SELECT id FROM projects
WHERE id NOT IN (SELECT project_id FROM prompt_placeholders)
ON CONFLICT (project_id) DO NOTHING;
