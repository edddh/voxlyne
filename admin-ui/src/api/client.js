import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || ''

const client = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - add auth token
client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('accessToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle token refresh
let isRefreshing = false
let failedQueue = []

const processQueue = (error, token = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  failedQueue = []
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            return client(originalRequest)
          })
          .catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('refreshToken')

      if (!refreshToken) {
        // TEMP DIAGNOSTIC (18/08, iPhone login bug - "flash e torna al
        // login"): alert() works on any device with no dev tools needed,
        // to see WHICH request 401'd and why refreshToken was missing.
        // Remove once diagnosed.
        window.alert(`[DEBUG] No refreshToken. Failing request: ${originalRequest.method} ${originalRequest.url}`)
        localStorage.clear()
        window.location.href = '/login'
        return Promise.reject(error)
      }

      try {
        const response = await axios.post(`${API_URL}/api/auth/refresh`, {
          refresh_token: refreshToken,
        })

        const { access_token } = response.data
        localStorage.setItem('accessToken', access_token)

        processQueue(null, access_token)
        originalRequest.headers.Authorization = `Bearer ${access_token}`

        return client(originalRequest)
      } catch (refreshError) {
        // TEMP DIAGNOSTIC - see note above. Remove once diagnosed.
        window.alert(
          `[DEBUG] Refresh failed. Original request: ${originalRequest.method} ${originalRequest.url} ` +
          `status=${error.response?.status}. Refresh error: ${refreshError.response?.status} ` +
          `${JSON.stringify(refreshError.response?.data || refreshError.message)}`
        )
        processQueue(refreshError, null)
        localStorage.clear()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export default client
