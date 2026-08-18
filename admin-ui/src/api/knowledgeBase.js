/**
 * Knowledge base (RAG) API client - per-project sources (crawled URLs or
 * uploaded documents), chunked and embedded into pgvector, searchable by
 * the voice agent's search_knowledge_base tool during a live call.
 */
import client from './client'

export const listSources = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/kb/sources`)
  return response.data.sources
}

export const addUrlSource = async (projectId, { url, max_pages, recrawl_interval_hours }) => {
  const response = await client.post(`/api/projects/${projectId}/kb/sources/url`, {
    url, max_pages, recrawl_interval_hours,
  })
  return response.data
}

export const addUploadSource = async (projectId, file) => {
  const formData = new FormData()
  formData.append('file', file)
  const response = await client.post(`/api/projects/${projectId}/kb/sources/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export const deleteSource = async (projectId, sourceId) => {
  await client.delete(`/api/projects/${projectId}/kb/sources/${sourceId}`)
}

export const reindexSource = async (projectId, sourceId) => {
  const response = await client.post(`/api/projects/${projectId}/kb/sources/${sourceId}/reindex`)
  return response.data
}

export const updateSchedule = async (projectId, sourceId, { recrawl_interval_hours, max_pages }) => {
  const response = await client.patch(`/api/projects/${projectId}/kb/sources/${sourceId}/schedule`, {
    recrawl_interval_hours, max_pages,
  })
  return response.data
}

export const searchKnowledgeBase = async (projectId, q, top_k = 5) => {
  const response = await client.get(`/api/projects/${projectId}/kb/search`, { params: { q, top_k } })
  return response.data
}
