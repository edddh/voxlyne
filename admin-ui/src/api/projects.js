import client from './client'

export const getProjects = async (params = {}) => {
  const response = await client.get('/api/projects', { params })
  return response.data
}

export const getProject = async (slug) => {
  const response = await client.get(`/api/projects/${slug}`)
  return response.data
}

export const createProject = async (data) => {
  const response = await client.post('/api/projects', data)
  return response.data
}

export const updateProject = async (id, data) => {
  const response = await client.patch(`/api/projects/${id}`, data)
  return response.data
}

export const deleteProject = async (id) => {
  const response = await client.delete(`/api/projects/${id}`)
  return response.data
}

// POST /api/projects/from-template/{template_id} takes name/slug/
// description/custom_variables as query params, not a JSON body (see
// app/routers/api.py). custom_variables is JSON-encoded here - the
// backend parses it back into an object.
export const createProjectFromTemplate = async (templateId, { name, slug, description, customVariables }) => {
  const response = await client.post(`/api/projects/from-template/${templateId}`, null, {
    params: {
      name,
      slug,
      description,
      custom_variables: customVariables ? JSON.stringify(customVariables) : undefined,
    },
  })
  return response.data
}

// Prompt versioning
export const getPromptVersions = async (projectId, promptType) => {
  const response = await client.get(`/api/projects/${projectId}/prompts/${promptType}/versions`)
  return response.data
}

export const createPromptVersion = async (projectId, promptType, data, activate = false) => {
  const response = await client.post(`/api/projects/${projectId}/prompts/${promptType}/versions`, data, {
    params: { activate },
  })
  return response.data
}

export const activatePromptVersion = async (versionId) => {
  const response = await client.post(`/api/prompts/versions/${versionId}/activate`)
  return response.data
}

export const rollbackPromptVersion = async (versionId) => {
  const response = await client.post(`/api/prompts/versions/${versionId}/rollback`)
  return response.data
}

export const getPromptDiff = async (versionA, versionB) => {
  const response = await client.get(`/api/prompts/versions/${versionA}/diff/${versionB}`)
  return response.data
}
