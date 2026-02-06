import client from './client'

export const getDashboardStats = async () => {
  const response = await client.get('/api/analytics/dashboard')
  return response.data
}

export const getCallTrends = async (period = 'week') => {
  const response = await client.get('/api/analytics/calls', { params: { period } })
  return response.data
}

export const getProjectStats = async () => {
  const response = await client.get('/api/analytics/projects')
  return response.data
}

export const getCallsByStatus = async (days = 30) => {
  const response = await client.get('/api/analytics/calls/by-status', { params: { days } })
  return response.data
}
