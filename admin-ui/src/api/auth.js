import client from './client'

export const login = async (email, password) => {
  const response = await client.post('/api/auth/login', { email, password })
  return response.data
}

export const refresh = async (refreshToken) => {
  const response = await client.post('/api/auth/refresh', { refresh_token: refreshToken })
  return response.data
}

export const logout = async (refreshToken) => {
  const response = await client.post('/api/auth/logout', { refresh_token: refreshToken })
  return response.data
}

export const getCurrentUser = async () => {
  const response = await client.get('/api/auth/me')
  return response.data
}

export const changePassword = async (currentPassword, newPassword) => {
  const response = await client.post('/api/auth/change-password', null, {
    params: { current_password: currentPassword, new_password: newPassword },
  })
  return response.data
}

export const requestPasswordReset = async (email) => {
  const response = await client.post('/api/auth/forgot-password', { email })
  return response.data
}

export const confirmPasswordReset = async (token, newPassword) => {
  const response = await client.post('/api/auth/reset-password', {
    token,
    new_password: newPassword,
  })
  return response.data
}
