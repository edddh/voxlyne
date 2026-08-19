import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Tabs, Form, Input, Button, Select, message, Typography, Space, Divider, Alert, Spin, Switch, TimePicker, Checkbox
} from 'antd'
import { SaveOutlined, CheckCircleOutlined, ArrowLeftOutlined, ApiOutlined, LinkOutlined } from '@ant-design/icons'
import * as projectConfigApi from '../api/projectConfig'
import * as projectsApi from '../api/projects'
import TelephonyTab from '../components/TelephonyTab'
import KnowledgeBaseTab from '../components/KnowledgeBaseTab'
import PdfEmailTab from '../components/PdfEmailTab'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * Project Configuration Page
 * 4 tabs: SIP Address, CRM Integration, Calendar Integration, Prompt Placeholders
 */
function ProjectConfig() {
  // La route e' registrata come "projects/:id/config" (App.jsx) - il
  // param si chiama "id", non "projectId". Prima di questo fix
  // useParams().projectId era sempre undefined, quindi ogni chiamata
  // API di questa pagina (SIP/CRM/Calendar/Placeholders) partiva verso
  // /api/projects/undefined/... (visto in log: 422 Unprocessable
  // Content) - il bottone "Configura" in Projects.jsx apriva la pagina
  // ma restava vuota/rotta (maintainer: "configura ... non si aprono").
  const { id: projectId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  // Forms
  const [sipForm] = Form.useForm()
  const [crmForm] = Form.useForm()
  const [calendarForm] = Form.useForm()
  const [placeholdersForm] = Form.useForm()

  // State
  const [crmEnabled, setCrmEnabled] = useState(false)
  const [crmProvider, setCrmProvider] = useState(null)
  const [crmTestResult, setCrmTestResult] = useState(null)

  const [calendarEnabled, setCalendarEnabled] = useState(false)
  const [calendarProvider, setCalendarProvider] = useState(null)
  const [calendarConnected, setCalendarConnected] = useState(false)

  useEffect(() => {
    loadProject()
    loadAllConfigs()
  }, [projectId])

  const loadProject = async () => {
    try {
      const data = await projectsApi.getProject(projectId)
      setProject(data)
    } catch (error) {
      message.error('Failed to load project')
      navigate('/projects')
    }
  }

  const loadAllConfigs = async () => {
    setLoading(true)
    try {
      await Promise.all([
        loadSIPConfig(),
        loadCRMConfig(),
        loadCalendarConfig(),
        loadPlaceholders(),
      ])
    } finally {
      setLoading(false)
    }
  }

  const loadSIPConfig = async () => {
    try {
      const data = await projectConfigApi.getSIPConfig(projectId)
      if (data) {
        sipForm.setFieldsValue({
          sip_address: data.sip_address,
          sip_username: data.sip_username,
          // Don't populate password for security
        })
      }
    } catch (error) {
      console.error('Failed to load SIP config:', error)
    }
  }

  const loadCRMConfig = async () => {
    try {
      const data = await projectConfigApi.getCRMConfig(projectId)
      if (data) {
        setCrmEnabled(data.enabled)
        setCrmProvider(data.provider)
        crmForm.setFieldsValue({
          provider: data.provider,
          hubspot_portal_id: data.hubspot_portal_id,
          webhook_url: data.webhook_url,
        })
      }
    } catch (error) {
      console.error('Failed to load CRM config:', error)
    }
  }

  const loadCalendarConfig = async () => {
    try {
      const data = await projectConfigApi.getCalendarConfig(projectId)
      if (data) {
        setCalendarEnabled(data.enabled)
        setCalendarProvider(data.provider)
        setCalendarConnected(!!data.access_token_encrypted)
        calendarForm.setFieldsValue({
          provider: data.provider,
          calendar_id: data.calendar_id || 'primary',
          timezone: data.timezone || 'Europe/Rome',
        })
      }
    } catch (error) {
      console.error('Failed to load Calendar config:', error)
    }
  }

  const loadPlaceholders = async () => {
    try {
      const data = await projectConfigApi.getPlaceholders(projectId)
      if (data) {
        placeholdersForm.setFieldsValue({
          cancel_phrase: data.cancel_phrase,
          cancellation_confirmation: data.cancellation_confirmation,
          goodbye_phrase: data.goodbye_phrase,
          intent_config: JSON.stringify(data.intent_config, null, 2),
        })
      }
    } catch (error) {
      console.error('Failed to load placeholders:', error)
    }
  }

  const handleSaveSIP = async () => {
    try {
      setSaving(true)
      const values = await sipForm.validateFields()
      await projectConfigApi.updateSIPConfig(projectId, values)
      message.success('SIP configuration saved')
    } catch (error) {
      if (error.errorFields) return
      message.error('Failed to save SIP config: ' + error.message)
    } finally {
      setSaving(false)
    }
  }

  const handleSaveCRM = async () => {
    try {
      setSaving(true)
      const values = await crmForm.validateFields()
      await projectConfigApi.updateCRMConfig(projectId, {
        ...values,
        enabled: crmEnabled,
      })
      message.success('CRM configuration saved')
    } catch (error) {
      if (error.errorFields) return
      message.error('Failed to save CRM config: ' + error.message)
    } finally {
      setSaving(false)
    }
  }

  const handleTestCRM = async () => {
    try {
      setTesting(true)
      setCrmTestResult(null)
      const result = await projectConfigApi.testCRMConnection(projectId)
      setCrmTestResult(result)
      if (result.success) {
        message.success('CRM connection successful!')
      } else {
        message.error('CRM connection failed: ' + result.error)
      }
    } catch (error) {
      message.error('Failed to test connection: ' + error.message)
    } finally {
      setTesting(false)
    }
  }

  const handleSaveCalendar = async () => {
    try {
      setSaving(true)
      const values = await calendarForm.validateFields()
      await projectConfigApi.updateCalendarConfig(projectId, {
        ...values,
        enabled: calendarEnabled,
      })
      message.success('Calendar configuration saved')
    } catch (error) {
      if (error.errorFields) return
      message.error('Failed to save Calendar config: ' + error.message)
    } finally {
      setSaving(false)
    }
  }

  const handleConnectCalendar = async () => {
    try {
      const provider = calendarForm.getFieldValue('provider')
      if (!provider) {
        message.warning('Please select a calendar provider first')
        return
      }
      const { oauth_url } = await projectConfigApi.getCalendarOAuthUrl(projectId, provider)
      window.open(oauth_url, '_blank', 'width=600,height=800')
      message.info('Complete authorization in the new window')
    } catch (error) {
      message.error('Failed to get OAuth URL: ' + error.message)
    }
  }

  const handleSavePlaceholders = async () => {
    try {
      setSaving(true)
      const values = await placeholdersForm.validateFields()

      // Parse intent_config JSON
      let intentConfig = {}
      if (values.intent_config) {
        try {
          intentConfig = JSON.parse(values.intent_config)
        } catch (e) {
          message.error('Invalid JSON in intent_config')
          setSaving(false)
          return
        }
      }

      await projectConfigApi.updatePlaceholders(projectId, {
        ...values,
        intent_config: intentConfig,
      })
      message.success('Placeholders saved')
    } catch (error) {
      if (error.errorFields) return
      message.error('Failed to save placeholders: ' + error.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading && !project) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  const tabItems = [
    {
      key: 'sip',
      label: 'SIP Address',
      children: (
        <Form form={sipForm} layout="vertical">
          <Alert
            message="SIP Configuration"
            description="Configure the SIP address for routing incoming calls to this project. Required for OpenAI Realtime voice calls."
            type="info"
            showIcon
            style={{ marginBottom: 24 }}
          />

          <Form.Item
            name="sip_address"
            label="SIP Address"
            rules={[{ required: true, message: 'Please enter SIP address' }]}
            tooltip="Format: +39 000 000 0000 admin@example.test"
          >
            <Input placeholder="+39 000 000 0000 admin@example.test" />
          </Form.Item>

          <Form.Item
            name="sip_username"
            label="SIP Username"
          >
            <Input placeholder="Optional" />
          </Form.Item>

          <Form.Item
            name="sip_password"
            label="SIP Password"
          >
            <Input.Password placeholder="Leave empty to keep current password" />
          </Form.Item>

          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSaveSIP}
            loading={saving}
          >
            Save SIP Configuration
          </Button>
        </Form>
      ),
    },
    {
      key: 'crm',
      label: 'CRM Integration',
      children: (
        <Form form={crmForm} layout="vertical">
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text strong>Enable CRM Integration</Text>
              <Switch checked={crmEnabled} onChange={setCrmEnabled} />
            </Space>
          </div>

          {crmEnabled && (
            <>
              <Form.Item
                name="provider"
                label="CRM Provider"
                rules={[{ required: true }]}
              >
                <Select onChange={setCrmProvider} placeholder="Select provider">
                  <Select.Option value="hubspot">HubSpot</Select.Option>
                  <Select.Option value="salesforce">Salesforce</Select.Option>
                  <Select.Option value="webhook">Generic Webhook</Select.Option>
                </Select>
              </Form.Item>

              {crmProvider === 'hubspot' && (
                <>
                  <Form.Item
                    name="hubspot_api_key"
                    label="HubSpot API Key"
                    rules={[{ required: true, message: 'Please enter API key' }]}
                  >
                    <Input.Password placeholder="Enter API key" />
                  </Form.Item>

                  <Form.Item
                    name="hubspot_portal_id"
                    label="Portal ID"
                  >
                    <Input placeholder="Optional" />
                  </Form.Item>

                  <Space>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      onClick={handleSaveCRM}
                      loading={saving}
                    >
                      Save Configuration
                    </Button>

                    <Button
                      icon={<ApiOutlined />}
                      onClick={handleTestCRM}
                      loading={testing}
                    >
                      Test Connection
                    </Button>
                  </Space>

                  {crmTestResult && (
                    <Alert
                      style={{ marginTop: 16 }}
                      message={crmTestResult.success ? 'Connection Successful' : 'Connection Failed'}
                      description={crmTestResult.message || crmTestResult.error}
                      type={crmTestResult.success ? 'success' : 'error'}
                      showIcon
                    />
                  )}
                </>
              )}

              {crmProvider === 'webhook' && (
                <>
                  <Form.Item
                    name="webhook_url"
                    label="Webhook URL"
                    rules={[{ required: true, type: 'url' }]}
                  >
                    <Input placeholder="https://your-webhook.com/endpoint" />
                  </Form.Item>

                  <Form.Item
                    name="webhook_secret"
                    label="Webhook Secret"
                  >
                    <Input.Password placeholder="Optional HMAC secret" />
                  </Form.Item>

                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    onClick={handleSaveCRM}
                    loading={saving}
                  >
                    Save Configuration
                  </Button>
                </>
              )}
            </>
          )}

          {!crmEnabled && (
            <Alert
              message="CRM integration is disabled"
              description="Enable to automatically sync call data to your CRM system"
              type="info"
            />
          )}
        </Form>
      ),
    },
    {
      key: 'calendar',
      label: 'Calendar Integration',
      children: (
        <Form form={calendarForm} layout="vertical">
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text strong>Enable Calendar Integration</Text>
              <Switch checked={calendarEnabled} onChange={setCalendarEnabled} />
            </Space>
          </div>

          {calendarEnabled && (
            <>
              <Form.Item
                name="provider"
                label="Calendar Provider"
                rules={[{ required: true }]}
              >
                <Select onChange={setCalendarProvider} placeholder="Select provider">
                  <Select.Option value="google">Google Calendar</Select.Option>
                  <Select.Option value="microsoft">Microsoft Outlook</Select.Option>
                </Select>
              </Form.Item>

              {calendarProvider && (
                <>
                  <Alert
                    message={calendarConnected ? 'Connected' : 'Not Connected'}
                    description={
                      calendarConnected
                        ? 'Calendar is connected and ready to use'
                        : 'Click below to authorize calendar access'
                    }
                    type={calendarConnected ? 'success' : 'warning'}
                    showIcon
                    icon={calendarConnected ? <CheckCircleOutlined /> : <LinkOutlined />}
                    style={{ marginBottom: 16 }}
                  />

                  <Button
                    type="primary"
                    icon={<LinkOutlined />}
                    onClick={handleConnectCalendar}
                    style={{ marginBottom: 16 }}
                  >
                    {calendarConnected ? 'Reconnect' : 'Connect'} {calendarProvider === 'google' ? 'Google' : 'Microsoft'} Calendar
                  </Button>

                  {calendarConnected && (
                    <>
                      <Form.Item
                        name="calendar_id"
                        label="Calendar"
                      >
                        <Input placeholder="primary" />
                      </Form.Item>

                      <Form.Item
                        name="timezone"
                        label="Timezone"
                      >
                        <Select>
                          <Select.Option value="Europe/Rome">Europe/Rome</Select.Option>
                          <Select.Option value="Europe/Berlin">Europe/Berlin</Select.Option>
                          <Select.Option value="America/New_York">America/New_York</Select.Option>
                        </Select>
                      </Form.Item>

                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={handleSaveCalendar}
                        loading={saving}
                      >
                        Save Configuration
                      </Button>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {!calendarEnabled && (
            <Alert
              message="Calendar integration is disabled"
              description="Enable to automatically schedule appointments from phone conversations"
              type="info"
            />
          )}
        </Form>
      ),
    },
    {
      key: 'placeholders',
      label: 'Prompt Placeholders',
      children: (
        <Form form={placeholdersForm} layout="vertical">
          <Alert
            message="Customizable Phrases"
            description="Configure the phrases used by the AI during conversations. These replace the default hardcoded values."
            type="info"
            showIcon
            style={{ marginBottom: 24 }}
          />

          <Form.Item
            name="cancel_phrase"
            label="Cancellation Phrase"
            tooltip="What the AI says when user requests data deletion"
          >
            <TextArea
              rows={2}
              placeholder="Va bene, procedo con la cancellazione della telefonata."
            />
          </Form.Item>

          <Form.Item
            name="cancellation_confirmation"
            label="Cancellation Confirmation"
            tooltip="Confirmation message after data deletion"
          >
            <TextArea
              rows={2}
              placeholder="Cancellazione dei dati della telefonata eseguita."
            />
          </Form.Item>

          <Form.Item
            name="goodbye_phrase"
            label="Goodbye Phrase"
            tooltip="How the AI ends the conversation"
          >
            <TextArea
              rows={2}
              placeholder="Le auguro una buona giornata! Arrivederci."
            />
          </Form.Item>

          <Divider />

          <Form.Item
            name="intent_config"
            label="Intent Configuration (Advanced)"
            tooltip="JSON configuration for intent detection keywords"
          >
            <TextArea
              rows={8}
              placeholder='{"calendar_keywords": ["appuntamento", "prenotazione"], "cancel_keywords": ["cancella", "elimina"]}'
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>

          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSavePlaceholders}
            loading={saving}
          >
            Save Placeholders
          </Button>
        </Form>
      ),
    },
    {
      key: 'telephony',
      label: 'Telefonia',
      children: <TelephonyTab projectId={projectId} />,
    },
    {
      key: 'knowledge-base',
      label: 'Knowledge Base',
      children: <KnowledgeBaseTab projectId={projectId} />,
    },
    {
      key: 'pdf-email',
      label: 'PDF & Email',
      children: <PdfEmailTab projectId={projectId} />,
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Card>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/projects')}
              style={{ marginBottom: 16 }}
            >
              Back to Projects
            </Button>
            <Title level={2} style={{ margin: 0 }}>
              Project Configuration: {project?.name}
            </Title>
            <Text type="secondary">{project?.slug}</Text>
          </div>

          <Tabs items={tabItems} />
        </Space>
      </Card>
    </div>
  )
}

export default ProjectConfig
