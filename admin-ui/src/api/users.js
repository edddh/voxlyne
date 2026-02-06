import client from './client'

export const getUsers = async (params = {}) => {
  const response = await client.get('/api/users', { params })
  return response.data
}

export const getUser = async (id) => {
  const response = await client.get(`/api/users/${id}`)
  return response.data
}

export const createUser = async (data) => {
  const response = await client.post('/api/users', data)
  return response.data
}

export const updateUser = async (id, data) => {
  const response = await client.patch(`/api/users/${id}`, data)
  return response.data
}

export const deleteUser = async (id) => {
  const response = await client.delete(`/api/users/${id}`)
  return response.data
}

export const resetUserPassword = async (id, newPassword) => {
  const response = await client.post(`/api/users/${id}/reset-password`, { new_password: newPassword })
  return response.data
}
