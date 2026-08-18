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
