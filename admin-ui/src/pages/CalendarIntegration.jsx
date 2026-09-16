import { useState, useEffect } from 'react'
import {
  Card, Button, Space, Form, Input, Switch, Select, message, Typography, Descriptions, Tag, Alert, Divider, Row, Col, Tabs
} from 'antd'
import {
  CalendarOutlined, CheckCircleOutlined, GoogleOutlined, WindowsOutlined, SaveOutlined, SyncOutlined, LinkOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as calendarApi from '../api/calendar'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

function CalendarIntegration() {
  const { t, i18n } = useTranslation()
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
        message.error(t('calendar.loadError'))
      }
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSubmit = async (values) => {
    setSaving(true)
    try {
      await calendarApi.updateCalendarConfig('google', values)
      message.success(t('calendar.googleSaved'))
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || t('calendar.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const handleMicrosoftSubmit = async (values) => {
    setSaving(true)
    try {
      await calendarApi.updateCalendarConfig('microsoft', values)
      message.success(t('calendar.microsoftSaved'))
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || t('calendar.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const handleOAuthConnect = async (provider) => {
    try {
      const { auth_url } = await calendarApi.getOAuthUrl(provider)
      window.open(auth_url, '_blank', 'width=600,height=700')
      message.info(t('calendar.completeAuth'))
    } catch (error) {
      message.error(t('calendar.oauthUrlError'))
    }
  }

  const googleTabContent = (
    <Card loading={loading}>
      <Alert
        message={t('calendar.googleIntegration')}
        description={t('calendar.googleDescription')}
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      {config?.google?.connected && (
        <Alert
          message={t('calendar.connectionActive')}
          description={t('calendar.connectionActiveDetail', {
            account: config.google.email || t('calendar.connected'),
            lastSync: config.google.last_sync ? new Date(config.google.last_sync).toLocaleString(i18n.language) : t('crm.never'),
          })}
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
          label={t('calendar.enableGoogle')}
          valuePropName="checked"
        >
          <Switch checkedChildren={t('crm.active')} unCheckedChildren={t('crm.inactive')} />
        </Form.Item>

        <Divider />

        <Form.Item
          name="client_id"
          label="Client ID"
          rules={[{ required: true, message: t('calendar.enterClientId') }]}
          extra={t('calendar.googleClientIdExtra')}
        >
          <Input placeholder="123456789-xxx.apps.googleusercontent.com" />
        </Form.Item>

        <Form.Item
          name="client_secret"
          label="Client Secret"
          rules={[{ required: true, message: t('calendar.enterClientSecret') }]}
          extra={t('calendar.googleClientSecretExtra')}
        >
          <Input.Password placeholder="GOCSPX-..." />
        </Form.Item>

        <Divider orientation="left">{t('calendar.calendarSettings')}</Divider>

        <Form.Item
          name="calendar_id"
          label="Calendar ID"
          extra={t('calendar.calendarIdExtra')}
        >
          <Input placeholder="primary" />
        </Form.Item>

        <Form.Item
          name="event_duration"
          label={t('calendar.eventDuration')}
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
              {t('crm.saveConfig')}
            </Button>
            <Button
              icon={<LinkOutlined />}
              onClick={() => handleOAuthConnect('google')}
            >
              {t('calendar.connectGoogleAccount')}
            </Button>
          </Space>
        </Form.Item>
      </Form>

      <Divider />

      <Card title={t('calendar.googleQuickGuide')} size="small" type="inner">
        <Paragraph>
          <Text strong>{t('calendar.googleSetup')}:</Text>
        </Paragraph>
        <ol>
          <li><a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer">{t('calendar.goTo')} Google Cloud Console</a></li>
          <li>{t('calendar.googleStep2')}</li>
          <li>{t('calendar.googleStep3')}</li>
          <li>{t('calendar.googleStep4')}</li>
          <li>{t('calendar.googleStep5')}</li>
          <li>{t('calendar.authorizedRedirectUris')}: <code>{window.location.origin}/api/calendar/google/callback</code></li>
          <li>{t('calendar.copyClientIdSecret')}</li>
        </ol>
      </Card>
    </Card>
  )

  const microsoftTabContent = (
    <Card loading={loading}>
      <Alert
        message={t('calendar.microsoftIntegration')}
        description={t('calendar.microsoftDescription')}
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      {config?.microsoft?.connected && (
        <Alert
          message={t('calendar.connectionActive')}
          description={t('calendar.connectionActiveDetail', {
            account: config.microsoft.email || t('calendar.connected'),
            lastSync: config.microsoft.last_sync ? new Date(config.microsoft.last_sync).toLocaleString(i18n.language) : t('crm.never'),
          })}
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
          label={t('calendar.enableMicrosoft')}
          valuePropName="checked"
        >
          <Switch checkedChildren={t('crm.active')} unCheckedChildren={t('crm.inactive')} />
        </Form.Item>

        <Divider />

        <Form.Item
          name="client_id"
          label={t('calendar.applicationClientId')}
          rules={[{ required: true, message: t('calendar.enterClientId') }]}
          extra={t('calendar.msApplicationIdExtra')}
        >
          <Input placeholder="12345678-1234-1234-1234-123456789012" />
        </Form.Item>

        <Form.Item
          name="client_secret"
          label="Client Secret"
          rules={[{ required: true, message: t('calendar.enterClientSecret') }]}
          extra={t('calendar.msClientSecretExtra')}
        >
          <Input.Password />
        </Form.Item>

        <Form.Item
          name="tenant_id"
          label={t('calendar.directoryTenantId')}
          rules={[{ required: true, message: t('calendar.enterTenantId') }]}
          extra={t('calendar.msTenantIdExtra')}
        >
          <Input placeholder="common" />
        </Form.Item>

        <Divider orientation="left">{t('calendar.calendarSettings')}</Divider>

        <Form.Item
          name="calendar_id"
          label="Calendar ID"
          extra={t('calendar.msCalendarIdExtra')}
        >
          <Input placeholder="" />
        </Form.Item>

        <Form.Item
          name="event_duration"
          label={t('calendar.eventDuration')}
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
              {t('crm.saveConfig')}
            </Button>
            <Button
              icon={<LinkOutlined />}
              onClick={() => handleOAuthConnect('microsoft')}
            >
              {t('calendar.connectMicrosoftAccount')}
            </Button>
          </Space>
        </Form.Item>
      </Form>

      <Divider />

      <Card title={t('calendar.microsoftQuickGuide')} size="small" type="inner">
        <Paragraph>
          <Text strong>{t('calendar.azureSetup')}:</Text>
        </Paragraph>
        <ol>
          <li><a href="https://portal.azure.com" target="_blank" rel="noopener noreferrer">{t('calendar.goTo')} Azure Portal</a></li>
          <li>{t('calendar.msStep2')}</li>
          <li>{t('calendar.msStep3')}</li>
          <li>{t('calendar.msStep4')}</li>
          <li>{t('calendar.msStep5')}</li>
          <li>{t('calendar.redirectUriWeb')}: <code>{window.location.origin}/api/calendar/microsoft/callback</code></li>
          <li>{t('calendar.msStep7')}</li>
          <li>{t('calendar.msStep8')}</li>
          <li>{t('calendar.msStep9')}</li>
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
        <CalendarOutlined /> {t('calendar.title')}
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
