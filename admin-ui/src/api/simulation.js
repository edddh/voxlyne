import client from './client'

export const simulateConversation = async (projectId, promptA, messages) => {
  const response = await client.post(`/api/projects/${projectId}/simulate`, {
    prompt_a: promptA,
    messages,
  })
  return response.data
}
