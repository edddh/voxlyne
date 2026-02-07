import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import AppLayout from './layouts/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
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

function ProtectedRoute({ children, allowedRoles }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div style={{ padding: 50, textAlign: 'center' }}>Caricamento...</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to="/" replace />
  }

  return children
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
        <Route index element={<Dashboard />} />
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
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id/edit" element={<ProjectEdit />} />
        <Route path="projects/:id/config" element={<ProjectConfig />} />
        <Route path="projects/:id/history" element={<PromptHistory />} />
        <Route path="calls" element={<Calls />} />
        <Route path="calls/:id" element={<CallDetail />} />
        <Route path="integrations/crm" element={<CRMIntegration />} />
        <Route path="integrations/calendar" element={<CalendarIntegration />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
