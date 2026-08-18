/**
 * Telephony provisioning API client - connect a real phone number to a
 * project (xAI byo_trunk registration + Zadarma SIP redirect, or manual
 * instructions when Zadarma API credentials aren't configured).
 */
import client from './client'

export const connectNumber = async (projectId, { phone_number, name }) => {
  const response = await client.post('/api/telephony/connect-number', {
    project_id: projectId,
    phone_number,
    name,
  })
  return response.data
}

export const disconnectNumber = async (projectId, phone_number) => {
  const response = await client.post('/api/telephony/disconnect-number', {
    project_id: projectId,
    phone_number,
  })
  return response.data
}

// Riusa l'API Fase 3 esistente (app/routers/agent_versions.py) per elencare
// i numeri gia' collegati a questo progetto - non serve un endpoint dedicato.
export const listConnectedNumbers = async (projectId) => {
  const response = await client.get('/api/inbound-endpoints', { params: { project_id: projectId } })
  return response.data
}
