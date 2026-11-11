-- Voxlyne - Admin Panel Schema
-- Milestone 4: Multi-tenant + User Management + Prompt Versioning
--
-- This migration adds:
-- - tenants: Multi-tenant isolation
-- - users: User accounts with RBAC
-- - api_keys: API key management
-- - refresh_tokens: JWT refresh token tracking
-- - prompt_versions: Prompt versioning with history
-- - prompt_version_history: Audit trail for prompt changes
-- - call_prompt_versions: Track which prompt version was used for each call

-- ===========================================
-- MULTI-TENANT SUPPORT
-- ===========================================

-- Tenants Table
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_tenants_slug ON tenants(slug);
CREATE INDEX idx_tenants_is_active ON tenants(is_active);

-- Auto-update trigger for tenants
CREATE TRIGGER update_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE tenants IS 'Multi-tenant organizations';
COMMENT ON COLUMN tenants.slug IS 'URL-friendly unique identifier';
COMMENT ON COLUMN tenants.settings IS 'Tenant-specific configuration (branding, limits, etc.)';

-- ===========================================
-- USERS TABLE (RBAC)
-- ===========================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,

    -- Authentication
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,

    -- Profile
    full_name VARCHAR(255),
    avatar_url VARCHAR(500),

    -- Role-Based Access Control
    role VARCHAR(50) NOT NULL DEFAULT 'user' CHECK (role IN (
        'super_admin',   -- Full system access, manages all tenants
        'admin',         -- Tenant admin, manages own tenant
        'creator',       -- Creates/edits prompts and projects
        'power_user',    -- Analytics and read access
        'user'           -- Standard user (no admin UI access)
    )),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    email_verified BOOLEAN DEFAULT FALSE,

    -- Tracking
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_is_active ON users(is_active);

-- Auto-update trigger for users
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE users IS 'User accounts with role-based access control';
COMMENT ON COLUMN users.role IS 'RBAC role: super_admin, admin, creator, power_user, user';
COMMENT ON COLUMN users.tenant_id IS 'NULL for super_admin (global), otherwise tenant-scoped';

-- ===========================================
-- API KEYS TABLE
-- ===========================================

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,

    -- Key identity
    name VARCHAR(255) NOT NULL,
    key_hash VARCHAR(255) NOT NULL,
    key_prefix VARCHAR(10) NOT NULL,  -- First 8 chars for display (e.g., "asc_1234...")

    -- Permissions
    scopes JSONB DEFAULT '["read"]',  -- ["read", "write", "admin"]

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,

    -- Audit
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX idx_api_keys_key_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_keys_is_active ON api_keys(is_active);

COMMENT ON TABLE api_keys IS 'API keys for programmatic access';
COMMENT ON COLUMN api_keys.key_hash IS 'Hashed API key (bcrypt or similar)';
COMMENT ON COLUMN api_keys.key_prefix IS 'First 8 characters for identification';
COMMENT ON COLUMN api_keys.scopes IS 'Allowed API scopes';

-- ===========================================
-- REFRESH TOKENS TABLE
-- ===========================================

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Token
    token_hash VARCHAR(255) NOT NULL,

    -- Expiration
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Metadata
    user_agent TEXT,
    ip_address INET,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at);

COMMENT ON TABLE refresh_tokens IS 'JWT refresh tokens for session management';

-- ===========================================
-- PROMPT VERSIONING
-- ===========================================

-- Prompt Versions Table
CREATE TABLE IF NOT EXISTS prompt_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Version identity
    prompt_type VARCHAR(1) NOT NULL CHECK (prompt_type IN ('A', 'B')),
    version INTEGER NOT NULL,

    -- Content
    content TEXT NOT NULL,

    -- Status
    is_active BOOLEAN DEFAULT FALSE,

    -- Audit
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Unique constraint: one version number per project/type combination
    UNIQUE(project_id, prompt_type, version)
);

CREATE INDEX idx_prompt_versions_project ON prompt_versions(project_id, prompt_type);
CREATE INDEX idx_prompt_versions_active ON prompt_versions(project_id, prompt_type, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE prompt_versions IS 'Versioned prompts for A/B testing and rollback';
COMMENT ON COLUMN prompt_versions.prompt_type IS 'A = conversation prompt, B = extraction prompt';
COMMENT ON COLUMN prompt_versions.is_active IS 'Only one version per type can be active';

-- Prompt Version History Table (Audit Trail)
CREATE TABLE IF NOT EXISTS prompt_version_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,

    -- Action
    action VARCHAR(50) NOT NULL CHECK (action IN (
        'created',
        'activated',
        'deactivated',
        'rollback'
    )),

    -- Audit
    performed_by UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}',  -- Additional context (e.g., rollback source version)

    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_prompt_history_version ON prompt_version_history(prompt_version_id);
CREATE INDEX idx_prompt_history_created ON prompt_version_history(created_at DESC);

COMMENT ON TABLE prompt_version_history IS 'Audit trail for prompt version changes';

-- Call Prompt Versions Table (Track which version was used)
CREATE TABLE IF NOT EXISTS call_prompt_versions (
    call_id UUID PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
    prompt_a_version_id UUID REFERENCES prompt_versions(id),
    prompt_b_version_id UUID REFERENCES prompt_versions(id)
);

CREATE INDEX idx_call_prompts_a ON call_prompt_versions(prompt_a_version_id);
CREATE INDEX idx_call_prompts_b ON call_prompt_versions(prompt_b_version_id);

COMMENT ON TABLE call_prompt_versions IS 'Tracks which prompt versions were used for each call';

-- ===========================================
-- EXTEND EXISTING TABLES FOR MULTI-TENANT
-- ===========================================

-- Add tenant_id to projects
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);

-- Add tenant_id to calls
ALTER TABLE calls
    ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_calls_tenant ON calls(tenant_id);

-- ===========================================
-- SEED DEFAULT TENANT AND SUPER ADMIN
-- ===========================================

-- Create default tenant
INSERT INTO tenants (id, name, slug, is_active, settings)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Default',
    'default',
    TRUE,
    '{"max_projects": 10, "max_users": 50}'::jsonb
) ON CONFLICT (slug) DO NOTHING;

-- Update existing projects to belong to default tenant
UPDATE projects
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;

-- Update existing calls to belong to default tenant
UPDATE calls
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;

-- No administrator is seeded. Create the first local super-admin with
-- scripts/create_admin.py after running migrations.

-- ===========================================
-- HELPER FUNCTIONS
-- ===========================================

-- Function to get next prompt version number
CREATE OR REPLACE FUNCTION get_next_prompt_version(
    p_project_id UUID,
    p_prompt_type VARCHAR(1)
) RETURNS INTEGER AS $$
DECLARE
    next_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version), 0) + 1
    INTO next_version
    FROM prompt_versions
    WHERE project_id = p_project_id
      AND prompt_type = p_prompt_type;

    RETURN next_version;
END;
$$ LANGUAGE plpgsql;

-- Function to activate a prompt version (deactivates others)
CREATE OR REPLACE FUNCTION activate_prompt_version(
    p_version_id UUID,
    p_user_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_project_id UUID;
    v_prompt_type VARCHAR(1);
BEGIN
    -- Get version details
    SELECT project_id, prompt_type
    INTO v_project_id, v_prompt_type
    FROM prompt_versions
    WHERE id = p_version_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Deactivate current active version
    UPDATE prompt_versions
    SET is_active = FALSE
    WHERE project_id = v_project_id
      AND prompt_type = v_prompt_type
      AND is_active = TRUE;

    -- Activate new version
    UPDATE prompt_versions
    SET is_active = TRUE
    WHERE id = p_version_id;

    -- Log history
    INSERT INTO prompt_version_history (prompt_version_id, action, performed_by)
    VALUES (p_version_id, 'activated', p_user_id);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- ===========================================
-- MIGRATE EXISTING PROMPTS TO VERSIONING
-- ===========================================

-- Create version 1 for existing project prompts
INSERT INTO prompt_versions (project_id, prompt_type, version, content, is_active, created_at)
SELECT
    id,
    'A',
    1,
    prompt_a,
    TRUE,
    created_at
FROM projects
WHERE prompt_a IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM prompt_versions pv
      WHERE pv.project_id = projects.id AND pv.prompt_type = 'A'
  );

INSERT INTO prompt_versions (project_id, prompt_type, version, content, is_active, created_at)
SELECT
    id,
    'B',
    1,
    prompt_b,
    TRUE,
    created_at
FROM projects
WHERE prompt_b IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM prompt_versions pv
      WHERE pv.project_id = projects.id AND pv.prompt_type = 'B'
  );

-- Log initial versions
INSERT INTO prompt_version_history (prompt_version_id, action, metadata)
SELECT id, 'created', '{"source": "migration_005", "note": "Initial version from existing prompt"}'::jsonb
FROM prompt_versions
WHERE NOT EXISTS (
    SELECT 1 FROM prompt_version_history pvh
    WHERE pvh.prompt_version_id = prompt_versions.id
);

COMMENT ON FUNCTION get_next_prompt_version IS 'Returns next available version number for a project/type';
COMMENT ON FUNCTION activate_prompt_version IS 'Activates a prompt version and deactivates others of same type';
