-- Voxlyne - Calendar Integration
-- Milestone 3.5: Add calendar scheduling support
--
-- This migration adds:
-- - calendar_tokens: OAuth tokens for Google/Microsoft calendar providers
-- - calendar_events: Tracks created calendar events
-- - Extends records table with calendar tracking columns
-- - Extends output_config with calendar settings

-- ===========================================
-- Calendar OAuth Tokens Table
-- ===========================================
-- Stores encrypted OAuth tokens for calendar providers

CREATE TABLE IF NOT EXISTS calendar_tokens (
    id SERIAL PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- Provider identification
    provider VARCHAR(50) NOT NULL,           -- 'google', 'microsoft'
    account_email VARCHAR(255),              -- Calendar account email

    -- OAuth tokens (encrypted)
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT,
    token_type VARCHAR(50) DEFAULT 'Bearer',

    -- Token metadata
    expires_at TIMESTAMP WITH TIME ZONE,
    scopes TEXT[],                           -- OAuth scopes granted

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_refresh_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(project_id, provider, account_email)
);

CREATE INDEX idx_calendar_tokens_project ON calendar_tokens(project_id);
CREATE INDEX idx_calendar_tokens_provider ON calendar_tokens(provider);
CREATE INDEX idx_calendar_tokens_active ON calendar_tokens(is_active) WHERE is_active = TRUE;

-- Trigger for updated_at
CREATE TRIGGER update_calendar_tokens_updated_at
    BEFORE UPDATE ON calendar_tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Calendar Events Table
-- ===========================================
-- Tracks calendar events created for interviews

CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    record_id INTEGER REFERENCES records(id) ON DELETE CASCADE,
    call_id UUID REFERENCES calls(id) ON DELETE CASCADE,

    -- Provider info
    provider VARCHAR(50) NOT NULL,           -- 'google', 'microsoft'
    calendar_id VARCHAR(255),                -- Calendar ID (primary, work, etc.)

    -- Event details
    external_event_id VARCHAR(255),          -- Provider's event ID
    event_link VARCHAR(500),                 -- Link to view event

    -- Scheduling
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_minutes INTEGER DEFAULT 30,
    timezone VARCHAR(50) DEFAULT 'Europe/Rome',

    -- Participants
    organizer_email VARCHAR(255),
    attendee_emails TEXT[],                  -- Candidate + HR emails

    -- Status
    status VARCHAR(50) DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed', 'failed')),

    -- Invite tracking
    invite_sent BOOLEAN DEFAULT FALSE,
    invite_sent_at TIMESTAMP WITH TIME ZONE,
    invite_accepted BOOLEAN,
    invite_response_at TIMESTAMP WITH TIME ZONE,

    -- Error tracking
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_calendar_events_record ON calendar_events(record_id);
CREATE INDEX idx_calendar_events_call ON calendar_events(call_id);
CREATE INDEX idx_calendar_events_provider ON calendar_events(provider);
CREATE INDEX idx_calendar_events_scheduled ON calendar_events(scheduled_at);
CREATE INDEX idx_calendar_events_status ON calendar_events(status);

-- Trigger for updated_at
CREATE TRIGGER update_calendar_events_updated_at
    BEFORE UPDATE ON calendar_events
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Extend Records Table with Calendar Tracking
-- ===========================================

ALTER TABLE records
    ADD COLUMN IF NOT EXISTS calendar_event_id INTEGER REFERENCES calendar_events(id);
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS appointment_scheduled BOOLEAN DEFAULT FALSE;
ALTER TABLE records
    ADD COLUMN IF NOT EXISTS appointment_datetime TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_records_appointment ON records(appointment_scheduled)
    WHERE appointment_scheduled = TRUE;

-- ===========================================
-- Extend Output Config with Calendar Settings
-- ===========================================
-- Update default project to include calendar config structure

UPDATE projects
SET output_config = output_config || '{
    "calendar": {
        "enabled": false,
        "provider": "google",
        "calendar_id": "primary",
        "config": {
            "default_duration_minutes": 30,
            "slot_lookahead_days": 14,
            "working_hours_start": "09:00",
            "working_hours_end": "18:00",
            "working_days": [1, 2, 3, 4, 5],
            "timezone": "Europe/Rome",
            "buffer_minutes": 15
        },
        "event_template": {
            "title": "Colloquio HR - {candidate_name}",
            "description": "Colloquio di approfondimento con il candidato {candidate_name} per la posizione di {role}.",
            "location": "Da definire"
        }
    }
}'::jsonb
WHERE output_config->>'calendar' IS NULL;

-- ===========================================
-- Calendar Metrics (Anonymous)
-- ===========================================

ALTER TABLE _gdpr_metrics
    ADD COLUMN IF NOT EXISTS appointments_scheduled INTEGER DEFAULT 0;
ALTER TABLE _gdpr_metrics
    ADD COLUMN IF NOT EXISTS appointments_completed INTEGER DEFAULT 0;

-- ===========================================
-- Comments for Documentation
-- ===========================================

COMMENT ON TABLE calendar_tokens IS 'OAuth tokens for calendar provider authentication';
COMMENT ON COLUMN calendar_tokens.access_token_encrypted IS 'Fernet-encrypted OAuth access token';
COMMENT ON COLUMN calendar_tokens.refresh_token_encrypted IS 'Fernet-encrypted OAuth refresh token';
COMMENT ON COLUMN calendar_tokens.expires_at IS 'Token expiration time for refresh logic';

COMMENT ON TABLE calendar_events IS 'Tracks calendar events created for interview follow-ups';
COMMENT ON COLUMN calendar_events.external_event_id IS 'Provider event ID (Google Calendar event ID, etc.)';
COMMENT ON COLUMN calendar_events.attendee_emails IS 'Array of participant emails (candidate + HR)';

COMMENT ON COLUMN records.calendar_event_id IS 'Reference to created calendar event';
COMMENT ON COLUMN records.appointment_scheduled IS 'Whether an appointment was scheduled';
COMMENT ON COLUMN records.appointment_datetime IS 'Scheduled appointment date/time';
