-- Voxlyne - Service Credentials
-- Milestone 5.5: Generalize credentials storage for all services
--
-- This migration:
-- - Renames crm_credentials → service_credentials
-- - Adds entity_type (project/tenant) and service_type (crm/voice/telephony/tts/calendar)
-- - Migrates existing CRM credentials to new schema
-- - Enables per-project API keys for Vapi, Twilio, ElevenLabs, etc.

-- ===========================================
-- Service Credentials Table
-- ===========================================
-- Stores encrypted credentials for all external services (CRM, Voice, Telephony, TTS, Calendar)
-- Supports both project-level and tenant-level credentials (tenant-ready for future multi-tenancy)

CREATE TABLE IF NOT EXISTS service_credentials (
    id SERIAL PRIMARY KEY,

    -- Entity ownership (project now, tenant in future)
    entity_type VARCHAR(20) NOT NULL DEFAULT 'project'
        CHECK (entity_type IN ('project', 'tenant')),
    entity_id UUID NOT NULL,

    -- Service type and provider
    service_type VARCHAR(50) NOT NULL
        CHECK (service_type IN ('crm', 'voice', 'telephony', 'tts', 'calendar')),
    provider VARCHAR(50) NOT NULL,           -- 'hubspot', 'vapi', 'twilio', 'elevenlabs', 'google_calendar', 'ms_graph', etc.
    credential_key VARCHAR(100) NOT NULL,    -- Reference key (e.g., 'main', 'backup', 'hubspot_example')

    -- Encrypted credential data (Fernet-encrypted JSON)
    encrypted_data TEXT NOT NULL,

    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,     -- For OAuth tokens

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Unique constraint: one credential per entity/service/provider/key combination
    UNIQUE(entity_type, entity_id, service_type, provider, credential_key)
);

-- Indexes for efficient querying
CREATE INDEX idx_service_credentials_entity ON service_credentials(entity_type, entity_id);
CREATE INDEX idx_service_credentials_service ON service_credentials(service_type);
CREATE INDEX idx_service_credentials_provider ON service_credentials(provider);
CREATE INDEX idx_service_credentials_active ON service_credentials(is_active) WHERE is_active = TRUE;

-- Trigger for updated_at
CREATE TRIGGER update_service_credentials_updated_at
    BEFORE UPDATE ON service_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Migrate Existing CRM Credentials
-- ===========================================
-- Copy data from crm_credentials (if exists) to service_credentials

DO $$
BEGIN
    -- Check if crm_credentials table exists
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'crm_credentials') THEN
        -- Migrate data
        INSERT INTO service_credentials (
            entity_type,
            entity_id,
            service_type,
            provider,
            credential_key,
            encrypted_data,
            is_active,
            last_used_at,
            expires_at,
            created_at,
            updated_at
        )
        SELECT
            'project',              -- entity_type
            project_id,             -- entity_id (maps to project_id)
            'crm',                  -- service_type
            provider,
            credential_key,
            encrypted_data,
            is_active,
            last_used_at,
            expires_at,
            created_at,
            updated_at
        FROM crm_credentials
        ON CONFLICT (entity_type, entity_id, service_type, provider, credential_key) DO NOTHING;

        -- Drop old table after migration
        DROP TABLE crm_credentials;

        RAISE NOTICE 'Migrated crm_credentials to service_credentials and dropped old table';
    ELSE
        RAISE NOTICE 'crm_credentials table does not exist, skipping migration';
    END IF;
END $$;

-- ===========================================
-- Comments for Documentation
-- ===========================================

COMMENT ON TABLE service_credentials IS 'Encrypted credentials for all external services (CRM, Voice, Telephony, TTS, Calendar) - supports project and tenant levels';
COMMENT ON COLUMN service_credentials.entity_type IS 'Entity type: project (current), tenant (future multi-tenancy)';
COMMENT ON COLUMN service_credentials.entity_id IS 'UUID of entity (project_id or tenant_id)';
COMMENT ON COLUMN service_credentials.service_type IS 'Service category: crm, voice, telephony, tts, calendar';
COMMENT ON COLUMN service_credentials.provider IS 'Provider name: hubspot, vapi, twilio, elevenlabs, google_calendar, ms_graph, etc.';
COMMENT ON COLUMN service_credentials.credential_key IS 'Reference key for multiple credentials of same provider (e.g., "main", "backup")';
COMMENT ON COLUMN service_credentials.encrypted_data IS 'Fernet-encrypted JSON containing API keys, tokens, secrets';
COMMENT ON COLUMN service_credentials.expires_at IS 'Token expiration for OAuth providers (Google Calendar, MS Graph)';

-- ===========================================
-- Examples of Credential Data Structures
-- ===========================================
-- (These are stored as encrypted JSON in encrypted_data column)
--
-- Vapi (voice):
-- {"api_key": "sk-..."}
--
-- Twilio (telephony):
-- {"account_sid": "AC...", "auth_token": "..."}
--
-- ElevenLabs (tts):
-- {"api_key": "..."}
--
-- HubSpot (crm):
-- {"access_token": "...", "refresh_token": "..."}
--
-- Google Calendar (calendar):
-- {"client_id": "...", "client_secret": "...", "access_token": "...", "refresh_token": "..."}
