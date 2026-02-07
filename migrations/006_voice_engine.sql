-- Ascolta - Voice Engine Schema
-- Milestone 5: Dual Voice Engine + Outbound Calling
--
-- This migration adds:
-- - voice_engine and call_direction columns to projects
-- - voice_engine, direction, and provider IDs to calls
-- - Vapi/Twilio specific fields

-- ===========================================
-- PROJECTS: Voice Engine Configuration
-- ===========================================

-- Voice engine provider per project (openai_realtime or vapi)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS voice_engine VARCHAR(50) DEFAULT 'openai_realtime';

-- Vapi assistant ID (if using pre-configured assistant in Vapi dashboard)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS vapi_assistant_id VARCHAR(255);

-- Twilio phone number to call from (E.164 format, e.g. +4915123456789)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS twilio_phone_number VARCHAR(50);

-- Call direction: inbound, outbound, or both
ALTER TABLE projects ADD COLUMN IF NOT EXISTS call_direction VARCHAR(20) DEFAULT 'inbound';

-- Vapi phone number ID (Vapi's internal reference to Twilio number)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS vapi_phone_number_id VARCHAR(255);

-- ElevenLabs voice ID override (per project)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS elevenlabs_voice_id VARCHAR(255);

-- ===========================================
-- CALLS: Voice Engine & Direction Tracking
-- ===========================================

-- Which voice engine was used for this call
ALTER TABLE calls ADD COLUMN IF NOT EXISTS voice_engine VARCHAR(50);

-- Call direction: inbound or outbound
ALTER TABLE calls ADD COLUMN IF NOT EXISTS direction VARCHAR(20) DEFAULT 'inbound';

-- Vapi call ID (for calls made through Vapi)
ALTER TABLE calls ADD COLUMN IF NOT EXISTS vapi_call_id VARCHAR(255);

-- Twilio call SID (for tracking on Twilio side)
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
