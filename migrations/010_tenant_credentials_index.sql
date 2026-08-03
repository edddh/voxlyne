-- Ascolta - Tenant-level Credentials Index
-- Milestone 5: service_credentials.entity_type already allows 'tenant'
-- (see 007_service_credentials.sql CHECK constraint) but no tenant-level
-- row was ever created or queried until CredentialsManager.get_credentials_with_fallback
-- and the /api/tenants/{tenant_id}/credentials endpoints were added. No
-- schema change is required for that to work - this migration only adds a
-- partial index to keep the new tenant-credentials list/lookup queries fast
-- as the table grows.

CREATE INDEX IF NOT EXISTS idx_service_credentials_tenant_lookup
    ON service_credentials (entity_id, service_type, provider, credential_key)
    WHERE entity_type = 'tenant' AND is_active = TRUE;
