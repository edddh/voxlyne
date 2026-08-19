import { useState, useEffect } from 'react'
import {
  Card, Button, Space, Form, Input, Switch, Select, message, Typography, Descriptions, Tag, Alert, Divider, Row, Col, Tabs
} from 'antd'
import {
  CalendarOutlined, CheckCircleOutlined, GoogleOutlined, WindowsOutlined, SaveOutlined, SyncOutlined, LinkOutlined
} from '@ant-design/icons'
import * as calendarApi from '../api/calendar'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

function CalendarIntegration() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [config, setConfig] = useState(null)
  const [activeTab, setActiveTab] = useState('google')
  const [googleForm] = Form.useForm()
  const [microsoftForm] = Form.useForm()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const data = await calendarApi.getCalendarConfig()
      setConfig(data)

      // Google
      if (data.google) {
        googleForm.setFieldsValue({
          enabled: data.google.enabled || false,
          client_id: data.google.client_id || '',
          client_secret: data.google.client_secret || '',
          calendar_id: data.google.calendar_id || 'primary',
          event_duration: data.google.event_duration || 60,
          default_timezone: data.google.default_timezone || 'Europe/Rome',
        })
      }

      // Microsoft
      if (data.microsoft) {
        microsoftForm.setFieldsValue({
          enabled: data.microsoft.enabled || false,
          client_id: data.microsoft.client_id || '',
          client_secret: data.microsoft.client_secret || '',
          tenant_id: data.microsoft.tenant_id || '',
          calendar_id: data.microsoft.calendar_id || '',
          event_duration: data.microsoft.event_duration || 60,
          default_timezone: data.microsoft.default_timezone || 'Europe/Rome',
        })
      }
    } catch (error) {
      if (error.response?.status === 404) {
        // No config yet
        googleForm.setFieldsValue({
          enabled: false,
          calendar_id: 'primary',
          event_duration: 60,
          default_timezone: 'Europe/Rome',
        })
        microsoftForm.setFieldsValue({
          enabled: false,
          event_duration: 60,
          default_timezone: 'Europe/Rome',
        })
      } else {
        message.error('Errore caricamento configurazione')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSubmit = async (values) => {
    setSaving(true)
    try {
      await calendarApi.updateCalendarConfig('google', values)
      message.success('Configurazione Google salvata')
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const handleMicrosoftSubmit = async (values) => {
    setSaving(true)
    try {
      await calendarApi.updateCalendarConfig('microsoft', values)
      message.success('Configurazione Microsoft salvata')
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const handleOAuthConnect = async (provider) => {
    try {
      const { auth_url } = await calendarApi.getOAuthUrl(provider)
      window.open(auth_url, '_blank', 'width=600,height=700')
      message.info('Completa l\'autenticazione nella finestra popup')
    } catch (error) {
      message.error('Errore generazione URL OAuth')
    }
  }

  const googleTabContent = (
    <Card loading={loading}>
      <Alert
        message="Integrazione Google Calendar"
        description="Crea automaticamente eventi nel calendario Google per ogni chiamata. Richiede un progetto Google Cloud con Google Calendar API abilitata."
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      {config?.google?.connected && (
        <Alert
          message="Connessione Attiva"
          description={`Account: ${config.google.email || 'Connesso'} • Ultimo sync: ${config.google.last_sync ? new Date(config.google.last_sync).toLocaleString('it-IT') : 'Mai'}`}
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Form
        form={googleForm}
        layout="vertical"
        onFinish={handleGoogleSubmit}
      >
        <Form.Item
          name="enabled"
          label="Abilita Google Calendar"
          valuePropName="checked"
        >
          <Switch checkedChildren="Attivo" unCheckedChildren="Inattivo" />
        </Form.Item>

        <Divider />

        <Form.Item
          name="client_id"
          label="Client ID"
          rules={[{ required: true, message: 'Inserisci client ID' }]}
          extra="Client ID dalla Google Cloud Console"
        >
          <Input placeholder="123456789-xxx.apps.googleusercontent.com" />
        </Form.Item>

        <Form.Item
          name="client_secret"
          label="Client Secret"
          rules={[{ required: true, message: 'Inserisci client secret' }]}
          extra="Client Secret dalla Google Cloud Console"
        >
          <Input.Password placeholder="GOCSPX-..." />
        </Form.Item>

        <Divider orientation="left">Impostazioni Calendario</Divider>

        <Form.Item
          name="calendar_id"
          label="Calendar ID"
          extra="ID del calendario da usare (default: 'primary' per calendario principale)"
        >
          <Input placeholder="primary" />
        </Form.Item>

        <Form.Item
          name="event_duration"
          label="Durata Evento (minuti)"
        >
          <Input type="number" placeholder="60" />
        </Form.Item>

        <Form.Item
          name="default_timezone"
          label="Timezone"
        >
          <Select>
            <Select.Option value="Europe/Rome">Europe/Rome (IT)</Select.Option>
            <Select.Option value="Europe/London">Europe/London (UK)</Select.Option>
            <Select.Option value="America/New_York">America/New_York (EST)</Select.Option>
            <Select.Option value="America/Los_Angeles">America/Los_Angeles (PST)</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SaveOutlined />}
              loading={saving}
            >
              Salva Configurazione
            </Button>
            <Button
              icon={<LinkOutlined />}
              onClick={() => handleOAuthConnect('google')}
            >
              Connetti Account Google
            </Button>
          </Space>
        </Form.Item>
      </Form>

      <Divider />

      <Card title="Guida Rapida Google" size="small" type="inner">
        <Paragraph>
          <Text strong>Setup Google Cloud:</Text>
        </Paragraph>
        <ol>
          <li>Vai su <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer">Google Cloud Console</a></li>
          <li>Crea un nuovo progetto o seleziona uno esistente</li>
          <li>Abilita "Google Calendar API"</li>
          <li>Vai in "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"</li>
          <li>Tipo applicazione: Web application</li>
          <li>Authorized redirect URIs: <code>{window.location.origin}/api/calendar/google/callback</code></li>
          <li>Copia Client ID e Client Secret</li>
        </ol>
      </Card>
    </Card>
  )

  const microsoftTabContent = (
    <Card loading={loading}>
      <Alert
        message="Integrazione Microsoft Outlook"
        description="Crea automaticamente eventi nel calendario Microsoft Outlook/365 per ogni chiamata. Richiede un'app registrata in Azure AD."
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      {config?.microsoft?.connected && (
        <Alert
          message="Connessione Attiva"
          description={`Account: ${config.microsoft.email || 'Connesso'} • Ultimo sync: ${config.microsoft.last_sync ? new Date(config.microsoft.last_sync).toLocaleString('it-IT') : 'Mai'}`}
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Form
        form={microsoftForm}
        layout="vertical"
        onFinish={handleMicrosoftSubmit}
      >
        <Form.Item
          name="enabled"
          label="Abilita Microsoft Calendar"
          valuePropName="checked"
        >
          <Switch checkedChildren="Attivo" unCheckedChildren="Inattivo" />
        </Form.Item>

        <Divider />

        <Form.Item
          name="client_id"
          label="Application (client) ID"
          rules={[{ required: true, message: 'Inserisci client ID' }]}
          extra="Application ID da Azure AD"
        >
          <Input placeholder="12345678-1234-1234-1234-123456789012" />
        </Form.Item>

        <Form.Item
          name="client_secret"
          label="Client Secret"
          rules={[{ required: true, message: 'Inserisci client secret' }]}
          extra="Client Secret (value) da Azure AD"
        >
          <Input.Password />
        </Form.Item>

        <Form.Item
          name="tenant_id"
          label="Directory (tenant) ID"
          rules={[{ required: true, message: 'Inserisci tenant ID' }]}
          extra="Tenant ID da Azure AD (usa 'common' per multi-tenant)"
        >
          <Input placeholder="common" />
        </Form.Item>

        <Divider orientation="left">Impostazioni Calendario</Divider>

        <Form.Item
          name="calendar_id"
          label="Calendar ID"
          extra="ID del calendario (lascia vuoto per calendario predefinito)"
        >
          <Input placeholder="" />
        </Form.Item>

        <Form.Item
          name="event_duration"
          label="Durata Evento (minuti)"
        >
          <Input type="number" placeholder="60" />
        </Form.Item>

        <Form.Item
          name="default_timezone"
          label="Timezone"
        >
          <Select>
            <Select.Option value="Europe/Rome">Europe/Rome (IT)</Select.Option>
            <Select.Option value="Europe/London">Europe/London (UK)</Select.Option>
            <Select.Option value="America/New_York">America/New_York (EST)</Select.Option>
            <Select.Option value="America/Los_Angeles">America/Los_Angeles (PST)</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SaveOutlined />}
              loading={saving}
            >
              Salva Configurazione
            </Button>
            <Button
              icon={<LinkOutlined />}
              onClick={() => handleOAuthConnect('microsoft')}
            >
              Connetti Account Microsoft
            </Button>
          </Space>
        </Form.Item>
      </Form>

      <Divider />

      <Card title="Guida Rapida Microsoft" size="small" type="inner">
        <Paragraph>
          <Text strong>Setup Azure AD:</Text>
        </Paragraph>
        <ol>
          <li>Vai su <a href="https://portal.azure.com" target="_blank" rel="noopener noreferrer">Azure Portal</a></li>
          <li>Apri "Azure Active Directory" → "App registrations"</li>
          <li>Clicca "New registration"</li>
          <li>Nome: "Ascolta Calendar"</li>
          <li>Supported account types: Scegli in base alle tue esigenze</li>
          <li>Redirect URI (Web): <code>{window.location.origin}/api/calendar/microsoft/callback</code></li>
          <li>Dopo la creazione, vai in "Certificates & secrets" → crea un Client Secret</li>
          <li>Vai in "API permissions" → "Add permission" → "Microsoft Graph" → "Delegated" → aggiungi: Calendars.ReadWrite, offline_access</li>
          <li>Copia Application ID, Tenant ID e Client Secret value</li>
        </ol>
      </Card>
    </Card>
  )

  const tabItems = [
    {
      key: 'google',
      label: (
        <span>
          <GoogleOutlined /> Google Calendar
        </span>
      ),
      children: googleTabContent,
    },
    {
      key: 'microsoft',
      label: (
        <span>
          <WindowsOutlined /> Microsoft Outlook
        </span>
      ),
      children: microsoftTabContent,
    },
  ]

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        <CalendarOutlined /> Integrazione Calendario
      </Title>

      <Tabs
        items={tabItems}
        activeKey={activeTab}
        onChange={setActiveTab}
      />
    </div>
  )
}

export default CalendarIntegration
