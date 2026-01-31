-- Ascolta - Initial Database Schema
-- Milestone 1: Voice Communication MVP
--
-- This migration creates the minimal schema for M1:
-- - calls: Track phone calls
-- - transcripts: Store conversation transcripts
--
-- Note: projects, settings, records, metrics tables will be added in M2

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ===========================================
-- Calls Table
-- ===========================================
-- Tracks all incoming phone calls
-- Note: project_id will be added in M2 migration

CREATE TABLE IF NOT EXISTS calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Caller information
    phone_number VARCHAR(50),

    -- Call status
    status VARCHAR(50) NOT NULL DEFAULT 'pending_consent' CHECK (status IN (
        'pending_consent',  -- Waiting for GDPR consent
        'consented',        -- Consent given, interview starting
        'in_progress',      -- Interview in progress
        'completed',        -- Interview completed successfully
        'processing',       -- Post-processing (JSON/PDF generation)
        'processed',        -- Fully processed with outputs
        'declined',         -- User declined consent
        'cancelled'         -- User pressed DTMF cancel key
    )),

    -- GDPR consent tracking
    consent_given BOOLEAN DEFAULT FALSE,
    consent_timestamp TIMESTAMP WITH TIME ZONE,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,

    -- OpenAI session tracking
    openai_session_id VARCHAR(255),

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_created_at ON calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_phone_number ON calls(phone_number);

-- ===========================================
-- Transcripts Table
-- ===========================================
-- Stores conversation messages
-- CASCADE delete ensures transcripts are removed when call is deleted (GDPR)

CREATE TABLE IF NOT EXISTS transcripts (
    id SERIAL PRIMARY KEY,
    call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,

    -- Message content
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,

    -- Timing
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for efficient call transcript retrieval
CREATE INDEX IF NOT EXISTS idx_transcripts_call_id ON transcripts(call_id);

-- ===========================================
-- Trigger: Auto-update updated_at
-- ===========================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_calls_updated_at
    BEFORE UPDATE ON calls
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================
-- Comments for documentation
-- ===========================================

COMMENT ON TABLE calls IS 'Phone calls received by the system';
COMMENT ON COLUMN calls.status IS 'Call lifecycle status';
COMMENT ON COLUMN calls.consent_given IS 'GDPR consent flag - if false, no data should be persisted';
COMMENT ON COLUMN calls.openai_session_id IS 'OpenAI Realtime API session identifier';

COMMENT ON TABLE transcripts IS 'Conversation transcripts - deleted with call for GDPR compliance';
COMMENT ON COLUMN transcripts.role IS 'Message sender: user (caller), assistant (AI), system';
