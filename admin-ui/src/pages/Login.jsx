import { useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Space, Modal, Alert } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useAuth } from '../hooks/useAuth'
import * as authApi from '../api/auth'
import { BRAND } from '../main'
import logo from '../assets/ascolta-logo.png'

const { Text } = Typography

function Login() {
  const [loading, setLoading] = useState(false)
  const [forgotOpen, setForgotOpen] = useState(false)
  const [forgotLoading, setForgotLoading] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [loginForm] = Form.useForm()
  const [forgotForm] = Form.useForm()
  const { login, isAuthenticated } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const resetToken = searchParams.get('reset_token')

  if (isAuthenticated && !resetToken) {
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

  const onForgotPassword = async (values) => {
    setForgotLoading(true)
    try {
      await authApi.requestPasswordReset(values.email.trim().toLowerCase())
      message.success("Se l'account esiste, abbiamo inviato il link di reset.")
      setForgotOpen(false)
    } catch (error) {
      const errorMessage = error.response?.data?.detail || 'Invio email non riuscito'
      message.error(errorMessage)
    } finally {
      setForgotLoading(false)
    }
  }

  const openForgotPassword = () => {
    const currentEmail = loginForm.getFieldValue('email')
    forgotForm.setFieldsValue({ email: currentEmail })
    setForgotOpen(true)
  }

  const onResetPassword = async (values) => {
    setResetLoading(true)
    try {
      await authApi.confirmPasswordReset(resetToken, values.newPassword)
      message.success('Password aggiornata. Ora puoi accedere.')
      setSearchParams({})
    } catch (error) {
      const errorMessage = error.response?.data?.detail || 'Reset password non riuscito'
      message.error(errorMessage)
    } finally {
      setResetLoading(false)
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
        padding: 16,
      }}
    >
      <Card
        style={{
          width: '100%',
          maxWidth: 400,
          minHeight: resetToken ? 0 : 360,
          background: BRAND.bgContainer,
          border: `1px solid ${BRAND.border}`,
          boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
        }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ textAlign: 'center' }}>
            <img src={logo} alt="Ascolta" style={{ maxWidth: 220, height: 'auto' }} />
          </div>

          <Form
            form={loginForm}
            name={resetToken ? 'reset-password' : 'login'}
            onFinish={resetToken ? onResetPassword : onFinish}
            layout="vertical"
            size="large"
          >
            {resetToken ? (
              <>
                <Alert
                  type="info"
                  showIcon
                  message="Imposta una nuova password"
                  description="Il link di reset è monouso. Dopo il cambio password dovrai accedere di nuovo."
                  style={{ marginBottom: 16 }}
                />
                <Form.Item
                  name="newPassword"
                  rules={[
                    { required: true, message: 'Inserisci la nuova password' },
                    { min: 8, message: 'Password troppo corta' },
                  ]}
                >
                  <Input.Password
                    id="new-password"
                    prefix={<LockOutlined />}
                    placeholder="Nuova password"
                    autoComplete="new-password"
                  />
                </Form.Item>
                <Form.Item
                  name="confirmPassword"
                  dependencies={['newPassword']}
                  rules={[
                    { required: true, message: 'Conferma la nuova password' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('newPassword') === value) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error('Le password non coincidono'))
                      },
                    }),
                  ]}
                >
                  <Input.Password
                    id="confirm-password"
                    prefix={<LockOutlined />}
                    placeholder="Conferma password"
                    autoComplete="new-password"
                  />
                </Form.Item>
              </>
            ) : (
              <>
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
              </>
            )}

            <Form.Item>
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={resetToken ? resetLoading : loading}
                  block
                >
                  {resetToken ? 'Aggiorna password' : 'Accedi'}
                </Button>
                {resetToken ? (
                  <Button block onClick={() => setSearchParams({})}>
                    Torna al login
                  </Button>
                ) : (
                  <Button type="link" block onClick={openForgotPassword}>
                    Password dimenticata?
                  </Button>
                )}
              </Space>
            </Form.Item>
          </Form>
        </Space>
      </Card>

      <Modal
        open={forgotOpen}
        title="Reset password"
        footer={null}
        onCancel={() => setForgotOpen(false)}
        destroyOnClose
        centered
        styles={{
          content: {
            background: BRAND.bgContainer,
            border: `1px solid ${BRAND.border}`,
          },
          header: {
            background: BRAND.bgContainer,
            borderBottom: `1px solid ${BRAND.border}`,
          },
        }}
      >
        <Form form={forgotForm} layout="vertical" onFinish={onForgotPassword}>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: 'Inserisci email' },
              { type: 'email', message: 'Email non valida' },
            ]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="Email account"
              type="email"
              autoComplete="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={forgotLoading} block>
            Invia link di reset
          </Button>
        </Form>
      </Modal>
    </div>
  )
}

export default Login
