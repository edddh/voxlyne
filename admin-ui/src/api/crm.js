import client from './client'

export const getCrmStatus = async (callId) => {
  const response = await client.get(`/api/crm/calls/${callId}/status`)
  return response.data
}

export const retryCrmSync = async (callId) => {
  const response = await client.post(`/api/crm/calls/${callId}/retry`)
  return response.data
}

export const getCrmSyncLog = async (params = {}) => {
  const response = await client.get('/api/crm/sync-log', { params })
  return response.data
}

export const getCrmStats = async () => {
  const response = await client.get('/api/crm/stats')
  return response.data
}

export const testCrmConnection = async (data) => {
  const response = await client.post('/api/crm/test-connection', data)
  return response.data
}

export const getCrmProviders = async () => {
  const response = await client.get('/api/crm/providers')
  return response.data
}
