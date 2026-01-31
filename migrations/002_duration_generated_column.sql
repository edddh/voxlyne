-- Migration: Convert duration_seconds to Generated Column
-- This ensures duration is always accurate and automatically maintained by PostgreSQL

-- Drop the existing duration_seconds column
ALTER TABLE calls
DROP COLUMN IF EXISTS duration_seconds;

-- Add duration_seconds as a generated column
-- It automatically calculates the difference between ended_at and started_at
ALTER TABLE calls
ADD COLUMN duration_seconds INTEGER
GENERATED ALWAYS AS (
  CASE
    WHEN ended_at IS NOT NULL AND started_at IS NOT NULL
    THEN EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER
    ELSE NULL
  END
) STORED;

-- Add index for performance on duration-based queries
CREATE INDEX IF NOT EXISTS idx_calls_duration ON calls(duration_seconds)
WHERE duration_seconds IS NOT NULL;

-- Comment for documentation
COMMENT ON COLUMN calls.duration_seconds IS 'Call duration in seconds - automatically calculated from ended_at - started_at';
