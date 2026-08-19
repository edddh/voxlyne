/**
 * Templates API Client
 * Super admin template management endpoints
 */

import client from './client';

/**
 * List all global templates
 * @param {string} category - Optional filter by category
 * @returns {Promise<{templates: Array, total: number}>}
 */
export const listTemplates = async (category = null) => {
  const params = category ? { category } : {};
  const response = await client.get('/api/templates', { params });
  return response.data;
};

/**
 * List templates assigned to the current user's tenant - what "Crea da
 * Template" (Projects.jsx) uses, as opposed to listTemplates() above
 * (the full catalog, super_admin only).
 * @returns {Promise<{templates: Array, total: number}>}
 */
export const getAssignedTemplates = async () => {
  const response = await client.get('/api/templates/assigned');
  return response.data;
};

/**
 * Create a new global template
 * @param {Object} data - Template data
 * @returns {Promise<Object>} Created template
 */
export const createTemplate = async (data) => {
  const response = await client.post('/api/templates', data);
  return response.data;
};

/**
 * Get single template by ID
 * @param {string} templateId - Template UUID
 * @returns {Promise<Object>} Template details
 */
export const getTemplate = async (templateId) => {
  const response = await client.get(`/api/templates/${templateId}`);
  return response.data;
};

/**
 * Update a template
 * @param {string} templateId - Template UUID
 * @param {Object} data - Updated template data
 * @returns {Promise<Object>} Updated template
 */
export const updateTemplate = async (templateId, data) => {
  const response = await client.put(`/api/templates/${templateId}`, data);
  return response.data;
};

/**
 * Assign template to tenants
 * @param {string} templateId - Template UUID
 * @param {Array<string>} tenantIds - Array of tenant UUIDs
 * @returns {Promise<Object>} Assignment result
 */
export const assignToTenants = async (templateId, tenantIds) => {
  const response = await client.post(`/api/templates/${templateId}/assign`, {
    tenant_ids: tenantIds,
  });
  return response.data;
};

/**
 * Get template assignments
 * @param {string} templateId - Template UUID
 * @returns {Promise<{assignments: Array, total: number}>}
 */
export const getAssignments = async (templateId) => {
  const response = await client.get(`/api/templates/${templateId}/assignments`);
  return response.data;
};

/**
 * Remove template assignment from tenant
 * @param {string} templateId - Template UUID
 * @param {string} tenantId - Tenant UUID
 * @returns {Promise<void>}
 */
export const unassignFromTenant = async (templateId, tenantId) => {
  await client.delete(`/api/templates/${templateId}/assignments/${tenantId}`);
};
