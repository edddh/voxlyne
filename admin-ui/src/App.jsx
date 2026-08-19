import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import AppLayout from './layouts/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Analytics from './pages/Analytics'
import Profile from './pages/Profile'
import Users from './pages/Users'
import Tenants from './pages/Tenants'
import Templates from './pages/Templates'
import Projects from './pages/Projects'
import ProjectEdit from './pages/ProjectEdit'
import ProjectConfig from './pages/ProjectConfig'
import PromptHistory from './pages/PromptHistory'
import Calls from './pages/Calls'
import CallDetail from './pages/CallDetail'
import CRMIntegration from './pages/CRMIntegration'
import CalendarIntegration from './pages/CalendarIntegration'
import TenantCredentials from './pages/TenantCredentials'

function ProtectedRoute({ children, allowedRoles, fallback = '/' }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div style={{ padding: 50, textAlign: 'center' }}>Caricamento...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    const to = typeof fallback === 'function' ? fallback(user) : fallback
    return <Navigate to={to} replace />
  }

  return children
}

// Atterraggio di default per chi non vede la Dashboard (vedi sotto):
// creator lavora su contenuti/progetti, user e' sola lettura sulle
// chiamate - stessa pagina "/calls" per entrambi sarebbe stata comoda
// da scrivere ma sbagliata per creator, che su /calls non ha nulla da
// fare di suo.
function landingFor(user) {
  return user.role === 'creator' ? '/projects' : '/calls'
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route
          index
          element={
            // Stessi ruoli di /analytics (app/routers/analytics.py:34) - "/"
            // è la pagina di atterraggio di default dopo il login per
            // chiunque, quindi creator/user ci finivano comunque anche
            // senza passare dal menu, con un 403 inghiottito in silenzio
            // che si vedeva come una dashboard sempre a zero.
            <ProtectedRoute allowedRoles={['admin', 'super_admin', 'power_user']} fallback={landingFor}>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route path="users" element={<Users />} />
        <Route
          path="tenants"
          element={
            <ProtectedRoute allowedRoles={['super_admin']}>
              <Tenants />
            </ProtectedRoute>
          }
        />
        <Route
          path="templates"
          element={
            <ProtectedRoute allowedRoles={['super_admin']}>
              <Templates />
            </ProtectedRoute>
          }
        />
        <Route
          path="tenants/:tenantId/credentials"
          element={
            <ProtectedRoute allowedRoles={['admin', 'super_admin']}>
              <TenantCredentials />
            </ProtectedRoute>
          }
        />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id/edit" element={<ProjectEdit />} />
        <Route path="projects/:id/config" element={<ProjectConfig />} />
        <Route path="projects/:id/history" element={<PromptHistory />} />
        <Route path="calls" element={<Calls />} />
        <Route path="calls/:id" element={<CallDetail />} />
        <Route path="profile" element={<Profile />} />
        <Route
          path="analytics"
          element={
            <ProtectedRoute allowedRoles={['admin', 'super_admin', 'power_user']}>
              <Analytics />
            </ProtectedRoute>
          }
        />
        <Route path="integrations/crm" element={<CRMIntegration />} />
        <Route path="integrations/calendar" element={<CalendarIntegration />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
