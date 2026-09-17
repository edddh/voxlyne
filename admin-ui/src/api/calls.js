import client from './client'

export const getCalls = async (params = {}) => {
  const response = await client.get('/api/v2/calls', { params })
  return response.data
}

export const getCallsStats = async (params = {}) => {
  const response = await client.get('/api/v2/calls/stats', { params })
  return response.data
}

export const getCall = async (id) => {
  const response = await client.get(`/api/v2/calls/${id}`)
  return response.data
}

export const deleteSimulationCall = async (id) => {
  const response = await client.delete(`/api/v2/calls/${id}`)
  return response.data
}

export const getCallTranscript = async (id, format = 'json') => {
  const response = await client.get(`/api/v2/calls/${id}/transcript`, { params: { format } })
  return response.data
}

export const downloadCallPdf = async (id) => {
  const response = await client.get(`/api/v2/calls/${id}/pdf`, { responseType: 'blob' })
  return response.data
}

export const getCallJson = async (id) => {
  const response = await client.get(`/api/v2/calls/${id}/json`)
  return response.data
}

export const reprocessCall = async (id) => {
  const response = await client.post(`/api/calls/${id}/reprocess`)
  return response.data
}

// M5: Outbound calls
export const createOutboundCall = async (data) => {
  const response = await client.post('/api/outbound/call', data)
  return response.data
}

export const getOutboundCallStatus = async (id) => {
  const response = await client.get(`/api/outbound/call/${id}/status`)
  return response.data
}

export const hangupOutboundCall = async (id) => {
  const response = await client.post(`/api/outbound/call/${id}/hangup`)
  return response.data
}
