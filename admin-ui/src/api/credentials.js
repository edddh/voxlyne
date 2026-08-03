import client from './client'

/**
 * Get all credentials for a project
 * @param {string} projectId - Project UUID
 * @param {string} [serviceType] - Optional filter by service type
 * @returns {Promise<Array>} List of credential metadata (NO sensitive data)
 */
export const getProjectCredentials = async (projectId, serviceType = null) => {
  const params = {}
  if (serviceType) {
    params.service_type = serviceType
  }

  const response = await client.get(`/api/projects/${projectId}/credentials`, { params })
  return response.data.credentials || []
}

/**
 * Create or update credentials for a project
 * @param {string} projectId - Project UUID
 * @param {object} credentialData - Credential data
 * @param {string} credentialData.service_type - Service type (crm, voice, telephony, tts, calendar)
 * @param {string} credentialData.provider - Provider name (vapi, twilio, elevenlabs, hubspot, etc.)
 * @param {string} [credentialData.credential_key] - Optional reference key (default: 'default')
 * @param {object} credentialData.data - Credential key-value pairs (will be encrypted)
 * @param {string} [credentialData.expires_at] - Optional expiration date (ISO 8601)
 * @returns {Promise<object>} Created/updated credential metadata
 */
export const createProjectCredential = async (projectId, credentialData) => {
  const response = await client.post(`/api/projects/${projectId}/credentials`, credentialData)
  return response.data
}

/**
 * Delete credentials for a project
 * @param {string} projectId - Project UUID
 * @param {number} credentialId - Credential ID
 * @returns {Promise<object>} Success response
 */
export const deleteProjectCredential = async (projectId, credentialId) => {
  const response = await client.delete(`/api/projects/${projectId}/credentials/${credentialId}`)
  return response.data
}

/**
 * Test if credentials are valid
 * @param {string} projectId - Project UUID
 * @param {number} credentialId - Credential ID
 * @returns {Promise<object>} Test result with success/message
 */
export const testProjectCredential = async (projectId, credentialId) => {
  const response = await client.post(`/api/projects/${projectId}/credentials/${credentialId}/test`)
  return response.data
}

/**
 * Test credentials without saving them
 * @param {object} testData - Test data
 * @param {string} testData.service_type - Service type
 * @param {string} testData.provider - Provider name
 * @param {object} testData.data - Credential key-value pairs to test
 * @returns {Promise<object>} Test result with success/message
 */
export const testCredentialsWithoutSaving = async (testData) => {
  const response = await client.post('/api/credentials/test', testData)
  return response.data
}

// ===========================================
// Tenant-level credentials (M5)
//
// Same shape as the project-level functions above, but stored as the
// tenant's default - used by all of that tenant's projects unless a project
// sets its own override (see CredentialsManager.get_credentials_with_fallback).
// ===========================================

/**
 * Get all default credentials for a tenant
 * @param {string} tenantId - Tenant UUID
 * @param {string} [serviceType] - Optional filter by service type
 * @returns {Promise<Array>} List of credential metadata (NO sensitive data)
 */
export const getTenantCredentials = async (tenantId, serviceType = null) => {
  const params = {}
  if (serviceType) {
    params.service_type = serviceType
  }

  const response = await client.get(`/api/tenants/${tenantId}/credentials`, { params })
  return response.data.credentials || []
}

/**
 * Create or update a tenant-level default credential
 * @param {string} tenantId - Tenant UUID
 * @param {object} credentialData - Same shape as createProjectCredential
 * @returns {Promise<object>} Created/updated credential metadata
 */
export const createTenantCredential = async (tenantId, credentialData) => {
  const response = await client.post(`/api/tenants/${tenantId}/credentials`, credentialData)
  return response.data
}

/**
 * Delete a tenant-level default credential
 * @param {string} tenantId - Tenant UUID
 * @param {number} credentialId - Credential ID
 * @returns {Promise<object>} Success response
 */
export const deleteTenantCredential = async (tenantId, credentialId) => {
  const response = await client.delete(`/api/tenants/${tenantId}/credentials/${credentialId}`)
  return response.data
}

/**
 * Test a stored tenant-level credential
 * @param {string} tenantId - Tenant UUID
 * @param {number} credentialId - Credential ID
 * @returns {Promise<object>} Test result with success/message
 */
export const testTenantCredential = async (tenantId, credentialId) => {
  const response = await client.post(`/api/tenants/${tenantId}/credentials/${credentialId}/test`)
  return response.data
}
