import client from './client'

export const getTenants = async (params = {}) => {
  const response = await client.get('/api/tenants', { params })
  return response.data
}

export const getTenant = async (id) => {
  const response = await client.get(`/api/tenants/${id}`)
  return response.data
}

export const createTenant = async (data) => {
  const response = await client.post('/api/tenants', data)
  return response.data
}

export const updateTenant = async (id, data) => {
  const response = await client.patch(`/api/tenants/${id}`, data)
  return response.data
}

export const deleteTenant = async (id) => {
  const response = await client.delete(`/api/tenants/${id}`)
  return response.data
}
