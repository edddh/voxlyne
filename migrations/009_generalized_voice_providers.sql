-- Ascolta - Generalized Voice/Telephony Providers
-- Milestone 5: adds the columns needed to select and configure the new
-- provider modes ported from earlier-prototype (LiveKit + xAI/OpenAI realtime,
-- direct SIP xAI/OpenAI, ElevenLabs conversational agent), alongside the
-- existing openai_realtime/vapi engines. Additive only - does not modify
-- or renumber migrations 001-008.
--
-- New voice_engine values used at the application level (see
-- app.services.voice.base.VoiceEngineType): livekit_xai, livekit_openai,
-- xai_sip_direct, openai_sip_direct, elevenlabs_agent. voice_engine stays a
-- plain VARCHAR (no DB-level CHECK/enum), consistent with 006_voice_engine.sql.

-- ===========================================
-- PROJECTS: new provider selectors + config
-- ===========================================

-- Orthogonal to voice_engine: which underlying AI model powers the realtime
-- conversation for engines that support both (livekit_xai/livekit_openai,
-- xai_sip_direct/openai_sip_direct already encode this in the engine name,
-- but this column lets a single LiveKit engine implementation branch on it).
ALTER TABLE projects ADD COLUMN IF NOT EXISTS ai_provider VARCHAR(20) DEFAULT 'openai';

-- LiveKit: which registered agent worker/dispatch rule serves this project.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS livekit_agent_name VARCHAR(255);

-- ElevenLabs conversational agent: provisioned agent id for this project.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS elevenlabs_agent_id VARCHAR(255);

-- Which telephony/SIP trunk provider delivers inbound calls for this project.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS sip_trunk_provider VARCHAR(50);

-- Catch-all for provider-specific extras that don't merit their own column
-- (e.g. LiveKit dispatch rule id, ElevenLabs tool-webhook url override).
-- Kept separate from output_config (which is for post-call output wiring:
-- pdf/email/webhook/crm/calendar), since this is inbound runtime config.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS voice_provider_config JSONB DEFAULT '{}'::jsonb;

-- ===========================================
-- CALLS: runtime mode + provider-specific call identifiers
-- ===========================================

ALTER TABLE calls ADD COLUMN IF NOT EXISTS runtime_mode VARCHAR(50);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS livekit_room_name VARCHAR(255);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS elevenlabs_conversation_id VARCHAR(255);

-- ===========================================
-- INDEXES
-- ===========================================

CREATE INDEX IF NOT EXISTS idx_projects_ai_provider ON projects(ai_provider);
CREATE INDEX IF NOT EXISTS idx_projects_sip_trunk_provider ON projects(sip_trunk_provider);
CREATE INDEX IF NOT EXISTS idx_calls_runtime_mode ON calls(runtime_mode);
CREATE INDEX IF NOT EXISTS idx_calls_livekit_room_name ON calls(livekit_room_name);
