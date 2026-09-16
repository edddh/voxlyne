import { useState, useEffect } from 'react'
import {
  Card, Button, Space, Form, Input, Switch, message, Typography, Descriptions, Tag, Alert, Divider, Row, Col
} from 'antd'
import { ApiOutlined, CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as crmApi from '../api/crm'

const { Title, Text, Paragraph } = Typography

function CRMIntegration() {
  const { t, i18n } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [config, setConfig] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const data = await crmApi.getCRMConfig()
      setConfig(data)
      form.setFieldsValue({
        enabled: data.enabled || false,
        api_key: data.api_key || '',
        portal_id: data.portal_id || '',
        default_pipeline: data.default_pipeline || '',
        default_stage: data.default_stage || '',
        sync_contacts: data.sync_contacts !== false,
        sync_deals: data.sync_deals !== false,
        create_tasks: data.create_tasks || false,
      })
    } catch (error) {
      if (error.response?.status === 404) {
        // No config yet
        form.setFieldsValue({
          enabled: false,
          sync_contacts: true,
          sync_deals: true,
          create_tasks: false,
        })
      } else {
        message.error(t('crm.loadError'))
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values) => {
    setSaving(true)
    try {
      await crmApi.updateCRMConfig(values)
      message.success(t('crm.saved'))
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || t('crm.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await crmApi.testCRMConnection()
      setTestResult(result)
      if (result.success) {
        message.success(t('crm.connectionOk'))
      } else {
        message.error(t('crm.connectionFailed'))
      }
    } catch (error) {
      setTestResult({
        success: false,
        message: error.response?.data?.detail || t('crm.testError'),
      })
      message.error(t('crm.testError'))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        <ApiOutlined /> {t('crm.title')}
      </Title>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Alert
            message={t('crm.hubspotIntegration')}
            description={t('crm.hubspotDescription')}
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        </Col>

        {config && config.enabled && (
          <Col span={24}>
            <Card size="small">
              <Space>
                <Text strong>{t('crm.status')}:</Text>
                <Tag color="green" icon={<CheckCircleOutlined />}>
                  {t('crm.integrationActive')}
                </Tag>
                <Divider type="vertical" />
                <Text type="secondary">
                  {t('crm.lastSync')}: {config.last_sync ? new Date(config.last_sync).toLocaleString(i18n.language) : t('crm.never')}
                </Text>
              </Space>
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card title={t('crm.configuration')} loading={loading}>
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
            >
              <Form.Item
                name="enabled"
                label={t('crm.enableIntegration')}
                valuePropName="checked"
              >
                <Switch checkedChildren={t('crm.active')} unCheckedChildren={t('crm.inactive')} />
              </Form.Item>

              <Divider />

              <Form.Item
                name="api_key"
                label={t('crm.hubspotApiKey')}
                rules={[
                  { required: true, message: t('crm.enterApiKey') },
                ]}
                extra={t('crm.apiKeyExtra')}
              >
                <Input.Password placeholder="pat-..." />
              </Form.Item>

              <Form.Item
                name="portal_id"
                label={t('crm.portalId')}
                rules={[
                  { required: true, message: t('crm.enterPortalId') },
                ]}
                extra={t('crm.portalIdExtra')}
              >
                <Input placeholder="12345678" />
              </Form.Item>

              <Divider orientation="left">{t('crm.pipelineAndStage')}</Divider>

              <Form.Item
                name="default_pipeline"
                label={t('crm.defaultPipeline')}
                extra={t('crm.defaultPipelineExtra')}
              >
                <Input placeholder="default" />
              </Form.Item>

              <Form.Item
                name="default_stage"
                label={t('crm.defaultStage')}
                extra={t('crm.defaultStageExtra')}
              >
                <Input placeholder="appointmentscheduled" />
              </Form.Item>

              <Divider orientation="left">{t('crm.syncOptions')}</Divider>

              <Form.Item
                name="sync_contacts"
                label={t('crm.syncContacts')}
                valuePropName="checked"
                extra={t('crm.syncContactsExtra')}
              >
                <Switch />
              </Form.Item>

              <Form.Item
                name="sync_deals"
                label={t('crm.syncDeals')}
                valuePropName="checked"
                extra={t('crm.syncDealsExtra')}
              >
                <Switch />
              </Form.Item>

              <Form.Item
                name="create_tasks"
                label={t('crm.createFollowupTasks')}
                valuePropName="checked"
                extra={t('crm.createFollowupTasksExtra')}
              >
                <Switch />
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
                    icon={<SyncOutlined />}
                    onClick={testConnection}
                    loading={testing}
                  >
                    {t('crm.testConnection')}
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        {testResult && (
          <Col span={24}>
            <Alert
              message={testResult.success ? t('crm.testSucceeded') : t('crm.testFailed')}
              description={
                <div>
                  <Paragraph>{testResult.message}</Paragraph>
                  {testResult.portal_id && (
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="Portal ID">{testResult.portal_id}</Descriptions.Item>
                      <Descriptions.Item label="Account Name">{testResult.account_name}</Descriptions.Item>
                    </Descriptions>
                  )}
                </div>
              }
              type={testResult.success ? 'success' : 'error'}
              showIcon
              closable
              onClose={() => setTestResult(null)}
            />
          </Col>
        )}

        <Col span={24}>
          <Card title={t('crm.quickGuide')} size="small">
            <Paragraph>
              <Text strong>{t('crm.howToGetApiKey')}:</Text>
            </Paragraph>
            <ol>
              <li>{t('crm.guideStep1')}</li>
              <li>{t('crm.guideStep2')}</li>
              <li>{t('crm.guideStep3')}</li>
              <li>{t('crm.guideStep4')}</li>
              <li>{t('crm.guideStep5')}</li>
            </ol>

            <Divider />

            <Paragraph>
              <Text strong>{t('crm.howToFindPortalId')}:</Text>
            </Paragraph>
            <ol>
              <li>{t('crm.guideStep6')}</li>
              <li>{t('crm.guideStep7')}</li>
              <li>{t('crm.guideStep8')}</li>
            </ol>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default CRMIntegration
