import client from './client'

export async function getProjectLlms(projectId) {
  const response = await client.get(`/api/elevenlabs/projects/${projectId}/llms`)
  return response.data.llms || []
}

export async function updateProjectLlm(projectId, llm) {
  const response = await client.put(`/api/elevenlabs/projects/${projectId}/llm`, { llm })
  return response.data
}
