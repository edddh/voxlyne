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

// Endpoints whose own 401 means "credenziali sbagliate", non "sessione
// scaduta" - non devono innescare il tentativo di refresh/redirect qui
// sotto. Trovato: un login con password sbagliata veniva trattato come
// sessione scaduta (nessun refreshToken ancora presente al primo
// tentativo -> localStorage.clear() + redirect forzato via
// window.location.href), quindi l'utente vedeva un lampo/reload della
// pagina invece del normale messaggio d'errore "Credenziali non valide"
// gestito da Login.jsx.
const AUTH_ENDPOINTS_EXEMPT_FROM_REFRESH = ['/api/auth/login', '/api/auth/refresh']

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const isExemptAuthEndpoint = AUTH_ENDPOINTS_EXEMPT_FROM_REFRESH.some((path) =>
      originalRequest?.url?.includes(path)
    )

    if (error.response?.status === 401 && !originalRequest._retry && !isExemptAuthEndpoint) {
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
