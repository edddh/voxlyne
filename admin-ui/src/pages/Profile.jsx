import { useState, useEffect } from 'react'
import { Card, Descriptions, Tag, Form, Input, Button, message, Typography, Space, Row, Col, Select } from 'antd'
import { LockOutlined, GlobalOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as authApi from '../api/auth'
import { SUPPORTED_LANGUAGES } from '../i18n'

const { Title } = Typography

/**
 * Profilo - "Profilo"/"Impostazioni" in alto a destra puntavano entrambi
 * a rotte mai registrate (/profile, /settings): ProtectedRoute reindirizza
 * silenziosamente alla Dashboard senza nessun errore, sembrava che i link
 * non facessero nulla (maintainer, 20/08). Fuse in una sola pagina - nessun
 * concetto di "impostazioni personali" esiste ancora lato backend, solo
 * dati account + cambio password (gia' pronto, mai collegato a una UI).
 */
function Profile() {
  const { t, i18n } = useTranslation()
  const ROLE_LABELS = {
    super_admin: t('roles.super_admin'),
    admin: t('roles.admin'),
    creator: t('roles.creator'),
    power_user: t('roles.power_user'),
    user: t('roles.user'),
  }
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [changingPassword, setChangingPassword] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    authApi.getCurrentUser()
      .then(setUser)
      .catch(() => message.error(t('profile.loadError')))
      .finally(() => setLoading(false))
  }, [])

  const handleChangePassword = async (values) => {
    setChangingPassword(true)
    try {
      await authApi.changePassword(values.current_password, values.new_password)
      message.success(t('profile.passwordChanged'))
      form.resetFields()
    } catch (error) {
      message.error(error.response?.data?.detail || t('profile.passwordChangeError'))
    } finally {
      setChangingPassword(false)
    }
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>{t('userMenu.profile')}</Title>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={12}>
          <Card title={t('profile.yourAccount')} loading={loading}>
            {user && (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label={t('users.fullName')}>{user.full_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="Email">{user.email}</Descriptions.Item>
                <Descriptions.Item label={t('users.role')}>
                  <Tag color={user.role === 'super_admin' ? 'gold' : 'blue'}>
                    {ROLE_LABELS[user.role] || user.role}
                  </Tag>
                </Descriptions.Item>
                {user.tenant_name && (
                  <Descriptions.Item label="Tenant">{user.tenant_name}</Descriptions.Item>
                )}
                <Descriptions.Item label={t('users.lastLogin')}>
                  {user.last_login_at ? new Date(user.last_login_at).toLocaleString(i18n.language) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label={t('profile.accountCreated')}>
                  {new Date(user.created_at).toLocaleString(i18n.language)}
                </Descriptions.Item>
              </Descriptions>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title={t('profile.changePassword')}>
            <Form form={form} layout="vertical" onFinish={handleChangePassword}>
              <Form.Item
                name="current_password"
                label={t('profile.currentPassword')}
                rules={[{ required: true, message: t('profile.enterCurrentPassword') }]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
              </Form.Item>
              <Form.Item
                name="new_password"
                label={t('users.newPassword')}
                rules={[
                  { required: true, message: t('login.enterNewPassword') },
                  { min: 8, message: t('profile.min8chars') },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirm_password"
                label={t('login.confirmPasswordPlaceholder')}
                dependencies={['new_password']}
                rules={[
                  { required: true, message: t('login.confirmNewPassword') },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                      return Promise.reject(new Error(t('login.passwordsDontMatch')))
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" loading={changingPassword}>
                    {t('profile.changePassword')}
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title={t('language.label')}>
            <Select
              value={i18n.language?.split('-')[0] || 'it'}
              onChange={(value) => i18n.changeLanguage(value)}
              style={{ width: '100%', maxWidth: 280 }}
              suffixIcon={<GlobalOutlined />}
              options={SUPPORTED_LANGUAGES.map((lang) => ({ value: lang.code, label: lang.label }))}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Profile
