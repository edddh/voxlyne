-- Voxlyne - Repair Voice Engine Schema
-- Ensures M5 columns/indexes exist even if a previous migration run was partial.

-- ===========================================
-- PROJECTS: Voice Engine Configuration
-- ===========================================

ALTER TABLE projects ADD COLUMN IF NOT EXISTS voice_engine VARCHAR(50) DEFAULT 'openai_realtime';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS vapi_assistant_id VARCHAR(255);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS twilio_phone_number VARCHAR(50);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS call_direction VARCHAR(20) DEFAULT 'inbound';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS vapi_phone_number_id VARCHAR(255);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS elevenlabs_voice_id VARCHAR(255);

-- ===========================================
-- CALLS: Voice Engine & Direction Tracking
-- ===========================================

ALTER TABLE calls ADD COLUMN IF NOT EXISTS voice_engine VARCHAR(50);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS direction VARCHAR(20) DEFAULT 'inbound';
ALTER TABLE calls ADD COLUMN IF NOT EXISTS vapi_call_id VARCHAR(255);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS twilio_call_sid VARCHAR(255);

-- ===========================================
-- INDEXES
-- ===========================================

CREATE INDEX IF NOT EXISTS idx_projects_voice_engine ON projects(voice_engine);
CREATE INDEX IF NOT EXISTS idx_projects_call_direction ON projects(call_direction);
CREATE INDEX IF NOT EXISTS idx_calls_voice_engine ON calls(voice_engine);
CREATE INDEX IF NOT EXISTS idx_calls_direction ON calls(direction);
CREATE INDEX IF NOT EXISTS idx_calls_vapi_call_id ON calls(vapi_call_id);
CREATE INDEX IF NOT EXISTS idx_calls_twilio_call_sid ON calls(twilio_call_sid);
