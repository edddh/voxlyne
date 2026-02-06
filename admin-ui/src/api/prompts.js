import client from './client'

export const getPromptVersions = async (projectId, promptType) => {
  const response = await client.get(`/api/projects/${projectId}/prompts/${promptType}/versions`)
  return response.data.versions
}

export const createPromptVersion = async (projectId, promptType, content, activate = false) => {
  const response = await client.post(`/api/projects/${projectId}/prompts/${promptType}/versions`,
    { content },
    { params: { activate } }
  )
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

export const getPromptDiff = async (versionIdA, versionIdB) => {
  const response = await client.get(`/api/prompts/versions/${versionIdA}/diff/${versionIdB}`)
  return response.data
}
