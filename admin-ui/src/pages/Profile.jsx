import { useState, useEffect } from 'react'
import { Card, Descriptions, Tag, Form, Input, Button, message, Typography, Space, Row, Col } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import * as authApi from '../api/auth'

const { Title } = Typography

const ROLE_LABELS = {
  super_admin: 'Super Admin',
  admin: 'Admin',
  creator: 'Creator',
  power_user: 'Power User',
  user: 'User',
}

/**
 * Profilo - "Profilo"/"Impostazioni" in alto a destra puntavano entrambi
 * a rotte mai registrate (/profile, /settings): ProtectedRoute reindirizza
 * silenziosamente alla Dashboard senza nessun errore, sembrava che i link
 * non facessero nulla (maintainer, 20/08). Fuse in una sola pagina - nessun
 * concetto di "impostazioni personali" esiste ancora lato backend, solo
 * dati account + cambio password (gia' pronto, mai collegato a una UI).
 */
function Profile() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [changingPassword, setChangingPassword] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    authApi.getCurrentUser()
      .then(setUser)
      .catch(() => message.error('Errore caricamento profilo'))
      .finally(() => setLoading(false))
  }, [])

  const handleChangePassword = async (values) => {
    setChangingPassword(true)
    try {
      await authApi.changePassword(values.current_password, values.new_password)
      message.success('Password cambiata')
      form.resetFields()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nel cambio password')
    } finally {
      setChangingPassword(false)
    }
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>Profilo</Title>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={12}>
          <Card title="Il tuo account" loading={loading}>
            {user && (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="Nome">{user.full_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="Email">{user.email}</Descriptions.Item>
                <Descriptions.Item label="Ruolo">
                  <Tag color={user.role === 'super_admin' ? 'gold' : 'blue'}>
                    {ROLE_LABELS[user.role] || user.role}
                  </Tag>
                </Descriptions.Item>
                {user.tenant_name && (
                  <Descriptions.Item label="Tenant">{user.tenant_name}</Descriptions.Item>
                )}
                <Descriptions.Item label="Ultimo accesso">
                  {user.last_login_at ? new Date(user.last_login_at).toLocaleString('it-IT') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Account creato">
                  {new Date(user.created_at).toLocaleString('it-IT')}
                </Descriptions.Item>
              </Descriptions>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="Cambia password">
            <Form form={form} layout="vertical" onFinish={handleChangePassword}>
              <Form.Item
                name="current_password"
                label="Password attuale"
                rules={[{ required: true, message: 'Inserisci la password attuale' }]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
              </Form.Item>
              <Form.Item
                name="new_password"
                label="Nuova password"
                rules={[
                  { required: true, message: 'Inserisci la nuova password' },
                  { min: 8, message: 'Almeno 8 caratteri' },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirm_password"
                label="Conferma nuova password"
                dependencies={['new_password']}
                rules={[
                  { required: true, message: 'Conferma la nuova password' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                      return Promise.reject(new Error('Le password non coincidono'))
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" loading={changingPassword}>
                    Cambia password
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Profile
