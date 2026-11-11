import { useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Space, Modal, Alert, Dropdown } from 'antd'
import { UserOutlined, LockOutlined, GlobalOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../hooks/useAuth'
import * as authApi from '../api/auth'
import { BRAND } from '../main'
import { BrandLogo } from '../components/BrandLogo'
import { SUPPORTED_LANGUAGES } from '../i18n'

const { Text } = Typography

function Login() {
  const { t, i18n } = useTranslation()
  const languageMenu = {
    selectedKeys: [i18n.language?.split('-')[0] || 'it'],
    items: SUPPORTED_LANGUAGES.map((lang) => ({ key: lang.code, label: lang.label })),
    onClick: ({ key }) => i18n.changeLanguage(key),
  }
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
      message.success(t('login.loginSuccess'))

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
      const errorMessage = error.response?.data?.detail || t('login.invalidCredentials')
      message.error(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const onForgotPassword = async (values) => {
    setForgotLoading(true)
    try {
      await authApi.requestPasswordReset(values.email.trim().toLowerCase())
      message.success(t('login.resetLinkSent'))
      setForgotOpen(false)
    } catch (error) {
      const errorMessage = error.response?.data?.detail || t('login.sendEmailFailed')
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
      message.success(t('login.passwordUpdated'))
      setSearchParams({})
    } catch (error) {
      const errorMessage = error.response?.data?.detail || t('login.resetFailed')
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
          <div style={{ textAlign: 'center', position: 'relative' }}>
            <BrandLogo alt="Voxlyne" style={{ maxWidth: 220, height: 'auto' }} />
            <Dropdown menu={languageMenu} placement="bottomRight">
              <Button
                type="text"
                icon={<GlobalOutlined />}
                title={t('language.label')}
                style={{ position: 'absolute', top: -8, right: -8 }}
              />
            </Dropdown>
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
                  message={t('login.setNewPasswordTitle')}
                  description={t('login.setNewPasswordDescription')}
                  style={{ marginBottom: 16 }}
                />
                <Form.Item
                  name="newPassword"
                  rules={[
                    { required: true, message: t('login.enterNewPassword') },
                    { min: 8, message: t('login.passwordTooShort') },
                  ]}
                >
                  <Input.Password
                    id="new-password"
                    prefix={<LockOutlined />}
                    placeholder={t('login.newPasswordPlaceholder')}
                    autoComplete="new-password"
                  />
                </Form.Item>
                <Form.Item
                  name="confirmPassword"
                  dependencies={['newPassword']}
                  rules={[
                    { required: true, message: t('login.confirmNewPassword') },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('newPassword') === value) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error(t('login.passwordsDontMatch')))
                      },
                    }),
                  ]}
                >
                  <Input.Password
                    id="confirm-password"
                    prefix={<LockOutlined />}
                    placeholder={t('login.confirmPasswordPlaceholder')}
                    autoComplete="new-password"
                  />
                </Form.Item>
              </>
            ) : (
              <>
                <Form.Item
                  name="email"
                  rules={[
                    { required: true, message: t('login.enterEmail') },
                    { type: 'email', message: t('login.invalidEmail') },
                  ]}
                >
                  <Input
                    id="email"
                    prefix={<UserOutlined />}
                    placeholder={t('login.emailPlaceholder')}
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
                    { required: true, message: t('login.enterPassword') },
                    { min: 6, message: t('login.passwordTooShort') },
                  ]}
                >
                  <Input.Password
                    id="password"
                    prefix={<LockOutlined />}
                    placeholder={t('login.passwordPlaceholder')}
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
                  {resetToken ? t('login.updatePassword') : t('login.signIn')}
                </Button>
                {resetToken ? (
                  <Button block onClick={() => setSearchParams({})}>
                    {t('login.backToLogin')}
                  </Button>
                ) : (
                  <Button type="link" block onClick={openForgotPassword}>
                    {t('login.forgotPassword')}
                  </Button>
                )}
              </Space>
            </Form.Item>
          </Form>
        </Space>
      </Card>

      <Modal
        open={forgotOpen}
        title={t('login.resetPasswordTitle')}
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
              { required: true, message: t('login.enterEmail') },
              { type: 'email', message: t('login.invalidEmail') },
            ]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder={t('login.accountEmailPlaceholder')}
              type="email"
              autoComplete="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={forgotLoading} block>
            {t('login.sendResetLink')}
          </Button>
        </Form>
      </Modal>
    </div>
  )
}

export default Login
