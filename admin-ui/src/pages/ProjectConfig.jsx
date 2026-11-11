import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Tabs, Form, Input, Button, Select, message, Typography, Space, Divider, Alert, Spin, Switch, TimePicker, Checkbox
} from 'antd'
import { SaveOutlined, CheckCircleOutlined, ArrowLeftOutlined, ApiOutlined, LinkOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as projectConfigApi from '../api/projectConfig'
import * as projectsApi from '../api/projects'
import TelephonyTab from '../components/TelephonyTab'
import KnowledgeBaseTab from '../components/KnowledgeBaseTab'
import PdfEmailTab from '../components/PdfEmailTab'
import CalcomTab from '../components/CalcomTab'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * Project Configuration Page
 * 4 tabs: SIP Address, CRM Integration, Calendar Integration, Prompt Placeholders
 */
function ProjectConfig() {
  const { t } = useTranslation()
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
      message.error(t('projectConfig.loadProjectError'))
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
      message.success(t('projectConfig.sipSaved'))
    } catch (error) {
      if (error.errorFields) return
      message.error(t('projectConfig.sipSaveError') + ': ' + error.message)
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
      message.success(t('projectConfig.crmSaved'))
    } catch (error) {
      if (error.errorFields) return
      message.error(t('projectConfig.crmSaveError') + ': ' + error.message)
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
        message.success(t('projectConfig.crmTestOk'))
      } else {
        message.error(t('projectConfig.crmTestFailed') + ': ' + result.error)
      }
    } catch (error) {
      message.error(t('projectConfig.testConnectionError') + ': ' + error.message)
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
      message.success(t('projectConfig.calendarSaved'))
    } catch (error) {
      if (error.errorFields) return
      message.error(t('projectConfig.calendarSaveError') + ': ' + error.message)
    } finally {
      setSaving(false)
    }
  }

  const handleConnectCalendar = async () => {
    try {
      const provider = calendarForm.getFieldValue('provider')
      if (!provider) {
        message.warning(t('projectConfig.selectProviderFirst'))
        return
      }
      const { oauth_url } = await projectConfigApi.getCalendarOAuthUrl(projectId, provider)
      window.open(oauth_url, '_blank', 'width=600,height=800')
      message.info(t('projectConfig.completeAuthInWindow'))
    } catch (error) {
      message.error(t('projectConfig.oauthUrlError') + ': ' + error.message)
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
          message.error(t('projectConfig.invalidIntentJson'))
          setSaving(false)
          return
        }
      }

      await projectConfigApi.updatePlaceholders(projectId, {
        ...values,
        intent_config: intentConfig,
      })
      message.success(t('projectConfig.placeholdersSaved'))
    } catch (error) {
      if (error.errorFields) return
      message.error(t('projectConfig.placeholdersSaveError') + ': ' + error.message)
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
      label: t('projectConfig.sipAddress'),
      children: (
        <Form form={sipForm} layout="vertical">
          <Alert
            message={t('projectConfig.sipConfiguration')}
            description={t('projectConfig.sipConfigDescription')}
            type="info"
            showIcon
            style={{ marginBottom: 24 }}
          />

          <Form.Item
            name="sip_address"
            label={t('projectConfig.sipAddress')}
            rules={[{ required: true, message: t('projectConfig.enterSipAddress') }]}
            tooltip="Format: sip:demo@sip.example.test"
          >
            <Input placeholder="sip:demo@sip.example.test" />
          </Form.Item>

          <Form.Item
            name="sip_username"
            label={t('projectConfig.sipUsername')}
          >
            <Input placeholder={t('projectConfig.optional')} />
          </Form.Item>

          <Form.Item
            name="sip_password"
            label={t('projectConfig.sipPassword')}
          >
            <Input.Password placeholder={t('projectConfig.leaveEmptyPassword')} />
          </Form.Item>

          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSaveSIP}
            loading={saving}
          >
            {t('projectConfig.saveSipConfig')}
          </Button>
        </Form>
      ),
    },
    {
      key: 'crm',
      label: t('projectConfig.crmIntegration'),
      children: (
        <Form form={crmForm} layout="vertical">
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text strong>{t('projectConfig.enableCrmIntegration')}</Text>
              <Switch checked={crmEnabled} onChange={setCrmEnabled} />
            </Space>
          </div>

          {crmEnabled && (
            <>
              <Form.Item
                name="provider"
                label={t('projectConfig.crmProvider')}
                rules={[{ required: true }]}
              >
                <Select onChange={setCrmProvider} placeholder={t('tenantCredentials.selectProviderPlaceholder')}>
                  <Select.Option value="hubspot">HubSpot</Select.Option>
                  <Select.Option value="salesforce">Salesforce</Select.Option>
                  <Select.Option value="webhook">{t('projectConfig.genericWebhook')}</Select.Option>
                </Select>
              </Form.Item>

              {crmProvider === 'hubspot' && (
                <>
                  <Form.Item
                    name="hubspot_api_key"
                    label={t('crm.hubspotApiKey')}
                    rules={[{ required: true, message: t('crm.enterApiKey') }]}
                  >
                    <Input.Password placeholder={t('crm.enterApiKey')} />
                  </Form.Item>

                  <Form.Item
                    name="hubspot_portal_id"
                    label={t('crm.portalId')}
                  >
                    <Input placeholder={t('projectConfig.optional')} />
                  </Form.Item>

                  <Space>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      onClick={handleSaveCRM}
                      loading={saving}
                    >
                      {t('projectConfig.saveConfiguration')}
                    </Button>

                    <Button
                      icon={<ApiOutlined />}
                      onClick={handleTestCRM}
                      loading={testing}
                    >
                      {t('crm.testConnection')}
                    </Button>
                  </Space>

                  {crmTestResult && (
                    <Alert
                      style={{ marginTop: 16 }}
                      message={crmTestResult.success ? t('projectConfig.connectionSuccessful') : t('projectConfig.connectionFailedTitle')}
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
                    label={t('projectConfig.webhookSecret')}
                  >
                    <Input.Password placeholder={t('projectConfig.optionalHmacSecret')} />
                  </Form.Item>

                  <Button
                    type="primary"
                    icon={<SaveOutlined />}
                    onClick={handleSaveCRM}
                    loading={saving}
                  >
                    {t('projectConfig.saveConfiguration')}
                  </Button>
                </>
              )}
            </>
          )}

          {!crmEnabled && (
            <Alert
              message={t('projectConfig.crmDisabled')}
              description={t('projectConfig.crmDisabledDescription')}
              type="info"
            />
          )}
        </Form>
      ),
    },
    {
      key: 'calendar',
      label: t('nav.integrationsCalendar'),
      children: (
        <Form form={calendarForm} layout="vertical">
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text strong>{t('projectConfig.enableCalendarIntegration')}</Text>
              <Switch checked={calendarEnabled} onChange={setCalendarEnabled} />
            </Space>
          </div>

          {calendarEnabled && (
            <>
              <Form.Item
                name="provider"
                label={t('projectConfig.calendarProvider')}
                rules={[{ required: true }]}
              >
                <Select onChange={setCalendarProvider} placeholder={t('tenantCredentials.selectProviderPlaceholder')}>
                  <Select.Option value="google">Google Calendar</Select.Option>
                  <Select.Option value="microsoft">Microsoft Outlook</Select.Option>
                </Select>
              </Form.Item>

              {calendarProvider && (
                <>
                  <Alert
                    message={calendarConnected ? t('projectConfig.connected') : t('projectConfig.notConnected')}
                    description={
                      calendarConnected
                        ? t('projectConfig.calendarConnectedDescription')
                        : t('projectConfig.calendarNotConnectedDescription')
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
                    {calendarConnected ? t('projectConfig.reconnect') : t('projectConfig.connect')} {calendarProvider === 'google' ? 'Google' : 'Microsoft'} Calendar
                  </Button>

                  {calendarConnected && (
                    <>
                      <Form.Item
                        name="calendar_id"
                        label={t('projectConfig.calendar')}
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
                        {t('projectConfig.saveConfiguration')}
                      </Button>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {!calendarEnabled && (
            <Alert
              message={t('projectConfig.calendarDisabled')}
              description={t('projectConfig.calendarDisabledDescription')}
              type="info"
            />
          )}
        </Form>
      ),
    },
    {
      key: 'placeholders',
      label: t('projectConfig.promptPlaceholders'),
      children: (
        <Form form={placeholdersForm} layout="vertical">
          <Alert
            message={t('projectConfig.customizablePhrases')}
            description={t('projectConfig.customizablePhrasesDescription')}
            type="info"
            showIcon
            style={{ marginBottom: 24 }}
          />

          <Form.Item
            name="cancel_phrase"
            label={t('projectConfig.cancellationPhrase')}
            tooltip={t('projectConfig.cancellationPhraseTooltip')}
          >
            <TextArea
              rows={2}
              placeholder="Va bene, procedo con la cancellazione della telefonata."
            />
          </Form.Item>

          <Form.Item
            name="cancellation_confirmation"
            label={t('projectConfig.cancellationConfirmation')}
            tooltip={t('projectConfig.cancellationConfirmationTooltip')}
          >
            <TextArea
              rows={2}
              placeholder="Cancellazione dei dati della telefonata eseguita."
            />
          </Form.Item>

          <Form.Item
            name="goodbye_phrase"
            label={t('projectConfig.goodbyePhrase')}
            tooltip={t('projectConfig.goodbyePhraseTooltip')}
          >
            <TextArea
              rows={2}
              placeholder="Le auguro una buona giornata! Arrivederci."
            />
          </Form.Item>

          <Divider />

          <Form.Item
            name="intent_config"
            label={t('projectConfig.intentConfigAdvanced')}
            tooltip={t('projectConfig.intentConfigTooltip')}
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
            {t('projectConfig.savePlaceholders')}
          </Button>
        </Form>
      ),
    },
    {
      key: 'telephony',
      label: t('projectConfig.telephony'),
      children: <TelephonyTab projectId={projectId} project={project} />,
    },
    {
      key: 'knowledge-base',
      label: t('projectConfig.knowledgeBase'),
      children: <KnowledgeBaseTab projectId={projectId} />,
    },
    {
      key: 'pdf-email',
      label: t('projectConfig.pdfEmail'),
      children: <PdfEmailTab projectId={projectId} />,
    },
    {
      key: 'calcom',
      label: 'Cal.com',
      children: <CalcomTab projectId={projectId} />,
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
              {t('projectConfig.backToProjects')}
            </Button>
            <Title level={2} style={{ margin: 0 }}>
              {t('projectConfig.projectConfiguration')}: {project?.name}
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
