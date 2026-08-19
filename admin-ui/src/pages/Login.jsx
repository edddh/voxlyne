import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Space } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useAuth } from '../hooks/useAuth'
import { BRAND } from '../main'
import logo from '../assets/ascolta-logo.png'

const { Text } = Typography

function Login() {
  const [loading, setLoading] = useState(false)
  const { login, isAuthenticated } = useAuth()

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  const onFinish = async (values) => {
    setLoading(true)
    try {
      // Rete di sicurezza oltre al fix della tastiera (autoCapitalize
      // sull'Input sopra): normalizza comunque prima di inviare, cosi'
      // il login funziona anche se qualcos'altro (autofill, un browser
      // diverso) reintroduce maiuscole/spazi indesiderati. Solo trim
      // sulla password (mai lowercase - e' case-sensitive per design):
      // le tastiere/barra suggerimenti mobile a volte aggiungono uno
      // spazio finale quando si accetta un suggerimento.
      const emailToSend = values.email.trim().toLowerCase()
      const passwordToSend = values.password.trim()
      await login(emailToSend, passwordToSend)
      message.success('Login effettuato')

      // Il salvataggio password del browser non scattava: un login via
      // AJAX (axios), senza una vera navigazione di pagina dopo l'invio
      // del form, non basta da solo a far comparire il prompt "salva
      // password" nella maggior parte dei browser (a differenza di un
      // vero POST HTML con redirect). La Credential Management API e' il
      // modo esplicito per chiederlo comunque - supportata da Chrome/Edge,
      // ignorata senza errori dove non c'e' (Safari ha supporto parziale).
      if (window.PasswordCredential) {
        try {
          const cred = new window.PasswordCredential({
            id: emailToSend,
            password: passwordToSend,
            name: emailToSend,
          })
          await navigator.credentials.store(cred)
        } catch {
          // Best-effort - mai bloccare il login per questo.
        }
      }
    } catch (error) {
      const errorMessage = error.response?.data?.detail || 'Credenziali non valide'
      message.error(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: BRAND.bg,
      }}
    >
      <Card
        style={{
          width: 400,
          background: BRAND.bgContainer,
          border: `1px solid ${BRAND.border}`,
          boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
        }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ textAlign: 'center' }}>
            <img src={logo} alt="Ascolta" style={{ maxWidth: 220, height: 'auto' }} />
            <div style={{ marginTop: 8 }}>
              <Text style={{ color: BRAND.textDim }}>Admin Panel</Text>
            </div>
          </div>

          <Form
            name="login"
            onFinish={onFinish}
            layout="vertical"
            size="large"
          >
            <Form.Item
              name="email"
              rules={[
                { required: true, message: 'Inserisci email' },
                { type: 'email', message: 'Email non valida' },
              ]}
            >
              <Input
                id="email"
                prefix={<UserOutlined />}
                placeholder="Email"
                type="email"
                autoComplete="email"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[
                { required: true, message: 'Inserisci password' },
                { min: 6, message: 'Password troppo corta' },
              ]}
            >
              <Input.Password
                id="password"
                prefix={<LockOutlined />}
                placeholder="Password"
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block>
                Accedi
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </div>
  )
}

export default Login
