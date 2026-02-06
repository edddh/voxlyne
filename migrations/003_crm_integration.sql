-- Ascolta - CRM Integration
-- Milestone 3: Add CRM synchronization support
--
-- This migration adds:
-- - crm_sync_log: Track sync attempts to external CRM systems
-- - Extends records table with CRM tracking columns
-- - Supports HubSpot, generic webhooks, and future CRM providers

-- ===========================================
-- CRM Sync Log Table
-- ===========================================
-- Tracks all CRM synchronization attempts with retry support

CREATE TABLE IF NOT EXISTS crm_sync_log (
    id SERIAL PRIMARY KEY,

    -- Relations
    record_id INTEGER REFERENCES records(id) ON DELETE CASCADE,
    call_id UUID REFERENCES calls(id) ON DELETE CASCADE,

    -- Provider info
    provider VARCHAR(50) NOT NULL,           -- 'hubspot', 'salesforce', 'generic_webhook'
    operation VARCHAR(50) NOT NULL,          -- 'create_contact', 'create_deal', 'update_contact', 'webhook'

    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'success', 'failed', 'retrying')),

    -- Request/Response tracking
    request_payload JSONB,                   -- What we sent (sanitized, no secrets)
    external_id VARCHAR(255),                -- CRM record ID (HubSpot Contact ID, etc.)
    response_code INTEGER,                   -- HTTP status code
    response_body TEXT,                      -- Response (truncated if large)
    error_message TEXT,                      -- Human-readable error

    -- Retry tracking
    attempt_count INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    next_retry_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX idx_crm_sync_log_call_id ON crm_sync_log(call_id);
CREATE INDEX idx_crm_sync_log_record_id ON crm_sync_log(record_id);
CREATE INDEX idx_crm_sync_log_status ON crm_sync_log(status);
CREATE INDEX idx_crm_sync_log_provider ON crm_sync_log(provider);
CREATE INDEX idx_crm_sync_log_created_at ON crm_sync_log(created_at DESC);
CREATE INDEX idx_crm_sync_log_next_retry ON crm_sync_log(next_retry_at)
    WHERE status = 'retrying';

-- Trigger for updated_at
CREATE TRIGGER update_crm_sync_log_updated_at
    BEFORE UPDATE ON crm_sync_log
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Extend Records Table with CRM Tracking
-- ===========================================

ALTER TABLE records
    ADD COLUMN IF NOT EXISTS crm_synced BOOLEAN DEFAULT FALSE;
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS crm_synced_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS crm_external_id VARCHAR(255);
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS crm_provider VARCHAR(50);
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS crm_error TEXT;

CREATE INDEX IF NOT EXISTS idx_records_crm_synced ON records(crm_synced);
CREATE INDEX IF NOT EXISTS idx_records_crm_provider ON records(crm_provider);

-- ===========================================
-- Extend Output Config with CRM Settings
-- ===========================================
-- Update default project to include CRM config structure

UPDATE projects
SET output_config = output_config || '{
    "crm": {
        "enabled": false,
        "provider": "hubspot",
        "config": {
            "create_contact": true,
            "create_deal": false,
            "deal_pipeline": "default",
            "deal_stage": "appointmentscheduled"
        },
        "field_mapping": {}
    }
}'::jsonb
WHERE output_config->>'crm' IS NULL;

-- ===========================================
-- CRM Credentials Store (Encrypted)
-- ===========================================
-- Stores encrypted credentials per project/provider

CREATE TABLE IF NOT EXISTS crm_credentials (
    id SERIAL PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Provider identification
    provider VARCHAR(50) NOT NULL,           -- 'hubspot', 'salesforce', etc.
    credential_key VARCHAR(100) NOT NULL,    -- Reference key (e.g., 'hubspot_demo-organization')

    -- Encrypted credential data
    encrypted_data TEXT NOT NULL,            -- Fernet-encrypted JSON

    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,     -- For OAuth tokens

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(project_id, provider, credential_key)
);

CREATE INDEX idx_crm_credentials_project ON crm_credentials(project_id);
CREATE INDEX idx_crm_credentials_provider ON crm_credentials(provider);
CREATE INDEX idx_crm_credentials_key ON crm_credentials(credential_key);

-- Trigger for updated_at
CREATE TRIGGER update_crm_credentials_updated_at
    BEFORE UPDATE ON crm_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- CRM Metrics (Anonymous Aggregates)
-- ===========================================
-- Extend _gdpr_metrics with CRM stats

ALTER TABLE _gdpr_metrics
    ADD COLUMN IF NOT EXISTS crm_synced_count INTEGER DEFAULT 0;
ALTER TABLE _gdpr_metrics
    ADD COLUMN IF NOT EXISTS crm_failed_count INTEGER DEFAULT 0;

-- ===========================================
-- Comments for Documentation
-- ===========================================

COMMENT ON TABLE crm_sync_log IS 'Tracks CRM synchronization attempts with retry support';
COMMENT ON COLUMN crm_sync_log.provider IS 'CRM provider: hubspot, salesforce, generic_webhook';
COMMENT ON COLUMN crm_sync_log.operation IS 'Operation type: create_contact, create_deal, update_contact, webhook';
COMMENT ON COLUMN crm_sync_log.external_id IS 'External CRM record ID (e.g., HubSpot Contact ID)';
COMMENT ON COLUMN crm_sync_log.request_payload IS 'Sanitized request payload (no secrets)';
COMMENT ON COLUMN crm_sync_log.next_retry_at IS 'Scheduled time for next retry (exponential backoff)';

COMMENT ON TABLE crm_credentials IS 'Encrypted CRM credentials per project/provider';
COMMENT ON COLUMN crm_credentials.encrypted_data IS 'Fernet-encrypted JSON with API keys/tokens';
COMMENT ON COLUMN crm_credentials.expires_at IS 'Token expiration for OAuth providers';

COMMENT ON COLUMN records.crm_synced IS 'Whether record was successfully synced to CRM';
COMMENT ON COLUMN records.crm_external_id IS 'External CRM record ID for reference';
COMMENT ON COLUMN records.crm_provider IS 'CRM provider used for sync';
COMMENT ON COLUMN records.crm_error IS 'Last CRM sync error message';
