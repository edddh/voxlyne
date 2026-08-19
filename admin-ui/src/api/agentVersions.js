/**
 * Fase 2/3 kernel versioning (app/routers/agent_versions.py) - lo
 * strato che davvero determina cosa risponde l'agente in una chiamata
 * reale (resolve_inbound() legge da agent_versions.status='published',
 * non da projects.prompt_a direttamente - vedi app/services/
 * agent_versions.py). Distinto e non collegato al vecchio sistema in
 * prompts.js (prompt_versions), che ProjectEdit.jsx usava erroneamente
 * come unica fonte del prompt mostrato/salvato (19/08, maintainer: "non
 * vedo il prompt attuale per la chiamata").
 */
import client from './client'

export const listAgentVersions = async (projectId) => {
  const response = await client.get(`/api/projects/${projectId}/versions`)
  return response.data
}

export const publishVersion = async (projectId) => {
  const response = await client.post(`/api/projects/${projectId}/versions/publish`)
  return response.data
}

export const rollbackToVersion = async (projectId, versionId) => {
  const response = await client.post(`/api/projects/${projectId}/versions/${versionId}/rollback`)
  return response.data
}
