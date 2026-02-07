/**
 * Project Configuration API Client
 * Per-project SIP, CRM, Calendar, and Placeholder configuration
 */

import client from './client';

// ===========================================
// SIP Configuration
// ===========================================

/**
 * Get SIP configuration for project
 * @param {string} projectId - Project UUID
 * @returns {Promise<Object>} SIP config
 */
export const getSIPConfig = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/config/sip`);
  return response.data;
};

/**
 * Update SIP configuration
 * @param {string} projectId - Project UUID
 * @param {Object} data - SIP config (sip_address, sip_username, sip_password)
 * @returns {Promise<Object>} Updated SIP config
 */
export const updateSIPConfig = async (projectId, data) => {
  const response = await client.put(`/api/projects/${projectId}/config/sip`, data);
  return response.data;
};

// ===========================================
// CRM Configuration
// ===========================================

/**
 * Get CRM configuration for project
 * @param {string} projectId - Project UUID
 * @returns {Promise<Object>} CRM config
 */
export const getCRMConfig = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/config/crm`);
  return response.data;
};

/**
 * Update CRM configuration
 * @param {string} projectId - Project UUID
 * @param {Object} data - CRM config (provider, credentials, config)
 * @returns {Promise<Object>} Updated CRM config
 */
export const updateCRMConfig = async (projectId, data) => {
  const response = await client.put(`/api/projects/${projectId}/config/crm`, data);
  return response.data;
};

/**
 * Test CRM connection
 * @param {string} projectId - Project UUID
 * @returns {Promise<Object>} Test result
 */
export const testCRMConnection = async (projectId) => {
  const response = await client.post(`/api/projects/${projectId}/config/crm/test`);
  return response.data;
};

// ===========================================
// Calendar Configuration
// ===========================================

/**
 * Get Calendar configuration for project
 * @param {string} projectId - Project UUID
 * @returns {Promise<Object>} Calendar config
 */
export const getCalendarConfig = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/config/calendar`);
  return response.data;
};

/**
 * Update Calendar configuration
 * @param {string} projectId - Project UUID
 * @param {Object} data - Calendar config (provider, credentials, config)
 * @returns {Promise<Object>} Updated Calendar config
 */
export const updateCalendarConfig = async (projectId, data) => {
  const response = await client.put(`/api/projects/${projectId}/config/calendar`, data);
  return response.data;
};

/**
 * Get OAuth authorization URL for Calendar provider
 * @param {string} projectId - Project UUID
 * @param {string} provider - 'google' or 'microsoft'
 * @returns {Promise<{oauth_url: string}>} OAuth URL
 */
export const getCalendarOAuthUrl = async (projectId, provider) => {
  const response = await client.get(`/api/projects/${projectId}/config/calendar/oauth-url`, {
    params: { provider },
  });
  return response.data;
};

// ===========================================
// Prompt Placeholders
// ===========================================

/**
 * Get prompt placeholders for project
 * @param {string} projectId - Project UUID
 * @returns {Promise<Object>} Placeholders (cancel_phrase, goodbye_phrase, etc.)
 */
export const getPlaceholders = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/config/placeholders`);
  return response.data;
};

/**
 * Update prompt placeholders
 * @param {string} projectId - Project UUID
 * @param {Object} data - Placeholders (cancel_phrase, goodbye_phrase, intent_config)
 * @returns {Promise<Object>} Updated placeholders
 */
export const updatePlaceholders = async (projectId, data) => {
  const response = await client.put(`/api/projects/${projectId}/config/placeholders`, data);
  return response.data;
};
