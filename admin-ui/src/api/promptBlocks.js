/**
 * Prompt Blocks API Client
 * Building blocks for prompt composer
 */

import client from './client';

/**
 * List prompt blocks visible to current user
 * @param {string} category - Optional filter (personality, rules, domain, custom)
 * @returns {Promise<{blocks: Array, total: number}>}
 */
export const listBlocks = async (category = null) => {
  const params = category ? { category } : {};
  const response = await client.get('/api/prompt-blocks', { params });
  return response.data;
};

/**
 * Create a new prompt block
 * @param {Object} data - Block data (name, category, content, is_public)
 * @returns {Promise<Object>} Created block
 */
export const createBlock = async (data) => {
  const response = await client.post('/api/prompt-blocks', data);
  return response.data;
};

/**
 * Get single block by ID
 * @param {string} blockId - Block UUID
 * @returns {Promise<Object>} Block details
 */
export const getBlock = async (blockId) => {
  const response = await client.get(`/api/prompt-blocks/${blockId}`);
  return response.data;
};

/**
 * Update a prompt block
 * @param {string} blockId - Block UUID
 * @param {Object} data - Updated block data
 * @returns {Promise<Object>} Updated block
 */
export const updateBlock = async (blockId, data) => {
  const response = await client.put(`/api/prompt-blocks/${blockId}`, data);
  return response.data;
};

/**
 * Delete a prompt block
 * @param {string} blockId - Block UUID
 * @returns {Promise<void>}
 */
export const deleteBlock = async (blockId) => {
  await client.delete(`/api/prompt-blocks/${blockId}`);
};
