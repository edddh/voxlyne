import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Modal, Form, Input, Select, message, Tag, Popconfirm,
  Typography, Tooltip, Alert,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ArrowLeftOutlined, ApiOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as credentialsApi from '../api/credentials'
import * as tenantsApi from '../api/tenants'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

// service_type -> provider options, matching CredentialsManager's known kinds
// (app/services/credentials/manager.py _get_env_fallback / test_connection)
const PROVIDER_OPTIONS = {
  voice: ['openai_realtime', 'vapi', 'xai'],
  telephony: ['twilio', 'livekit', 'zadarma'],
  tts: ['elevenlabs', 'elevenlabs_agent'],
  crm: ['hubspot', 'generic_webhook'],
  calendar: ['google_calendar', 'ms_graph', 'calcom'],
  llm: ['openai'], // per gli embedding della knowledge base RAG (app/services/rag/embeddings.py)
}

function TenantCredentials() {
  const { t, i18n } = useTranslation()
  const { tenantId } = useParams()
  const navigate = useNavigate()

  const [tenant, setTenant] = useState(null)
  const [credentials, setCredentials] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadTenant()
    loadCredentials()
  }, [tenantId])

  const loadTenant = async () => {
    try {
      const data = await tenantsApi.getTenant(tenantId)
      setTenant(data)
    } catch (error) {
      message.error(t('tenantCredentials.loadTenantError'))
    }
  }

  const loadCredentials = async () => {
    setLoading(true)
    try {
      const data = await credentialsApi.getTenantCredentials(tenantId)
      setCredentials(data)
    } catch (error) {
      message.error(t('tenantCredentials.loadCredentialsError'))
    } finally {
      setLoading(false)
    }
  }

  const openModal = () => {
    form.resetFields()
    form.setFieldsValue({ credential_key: 'default', data: '{\n  "api_key": ""\n}' })
    setModalOpen(true)
  }

  const handleSubmit = async (values) => {
    let parsedData
    try {
      parsedData = JSON.parse(values.data)
    } catch (e) {
      message.error(t('tenantCredentials.invalidJson'))
      return
    }

    setSaving(true)
    try {
      await credentialsApi.createTenantCredential(tenantId, {
        service_type: values.service_type,
        provider: values.provider,
        credential_key: values.credential_key || 'default',
        data: parsedData,
      })
      message.success(t('tenantCredentials.savedAsDefault'))
      setModalOpen(false)
      loadCredentials()
    } catch (error) {
      message.error(error.response?.data?.detail || t('tenantCredentials.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (credentialId) => {
    try {
      await credentialsApi.deleteTenantCredential(tenantId, credentialId)
      message.success(t('tenantCredentials.deleted'))
      loadCredentials()
    } catch (error) {
      message.error(error.response?.data?.detail || t('tenantCredentials.deleteError'))
    }
  }

  const handleTest = async (credentialId) => {
    setTestingId(credentialId)
    try {
      const result = await credentialsApi.testTenantCredential(tenantId, credentialId)
      if (result.success) {
        message.success(result.message || t('tenantCredentials.connectionOk'))
      } else {
        message.error(result.message || t('tenantCredentials.connectionFailed'))
      }
    } catch (error) {
      message.error(error.response?.data?.detail || t('tenantCredentials.testError'))
    } finally {
      setTestingId(null)
    }
  }

  const columns = [
    { title: t('tenantCredentials.category'), dataIndex: 'service_type', key: 'service_type', render: (v) => <Tag>{v}</Tag> },
    { title: 'Provider', dataIndex: 'provider', key: 'provider' },
    { title: t('tenantCredentials.key'), dataIndex: 'credential_key', key: 'credential_key', render: (v) => <code>{v}</code> },
    {
      title: t('tenantCredentials.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => <Tag color={active ? 'green' : 'red'}>{active ? t('tenantCredentials.active') : t('tenantCredentials.disabled')}</Tag>,
    },
    {
      title: t('tenantCredentials.lastUsed'),
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (v) => (v ? new Date(v).toLocaleString(i18n.language) : '—'),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title={t('tenantCredentials.testConnection')}>
            <Button
              icon={<ApiOutlined />}
              size="small"
              loading={testingId === record.id}
              onClick={() => handleTest(record.id)}
            />
          </Tooltip>
          <Popconfirm
            title={t('tenantCredentials.confirmDelete')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('promptHistory.yes')}
            cancelText={t('promptHistory.no')}
          >
            <Tooltip title={t('common.delete')}>
              <Button icon={<DeleteOutlined />} size="small" danger />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tenants')}>
          {t('tenantCredentials.backToTenants')}
        </Button>
      </Space>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>
          {t('tenantCredentials.title')} - {tenant?.name || tenantId}
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openModal}>
          {t('tenantCredentials.newCredential')}
        </Button>
      </div>

      <Paragraph type="secondary">
        {t('tenantCredentials.description')}
      </Paragraph>

      <Table
        scroll={{ x: 'max-content' }}
        dataSource={credentials}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
      />

      <Modal
        title={t('tenantCredentials.newTenantCredential')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="service_type"
            label={t('tenantCredentials.category')}
            rules={[{ required: true, message: t('tenantCredentials.selectCategory') }]}
          >
            <Select
              placeholder={t('tenantCredentials.selectCategory')}
              options={Object.keys(PROVIDER_OPTIONS).map((k) => ({ value: k, label: k }))}
              onChange={() => form.setFieldValue('provider', undefined)}
            />
          </Form.Item>

          <Form.Item shouldUpdate={(prev, cur) => prev.service_type !== cur.service_type} noStyle>
            {({ getFieldValue }) => {
              const serviceType = getFieldValue('service_type')
              const providerOptions = PROVIDER_OPTIONS[serviceType] || []
              return (
                <Form.Item
                  name="provider"
                  label="Provider"
                  rules={[{ required: true, message: t('tenantCredentials.selectProvider') }]}
                >
                  <Select
                    placeholder={t('tenantCredentials.selectProviderPlaceholder')}
                    options={providerOptions.map((p) => ({ value: p, label: p }))}
                    showSearch
                    allowClear
                    // Provider names beyond the known list (e.g. new/custom
                    // ones) can still be typed - the backend accepts any string.
                    onSearch={() => {}}
                    notFoundContent={t('tenantCredentials.typeCustomProvider')}
                  />
                </Form.Item>
              )
            }}
          </Form.Item>

          <Form.Item name="credential_key" label={t('tenantCredentials.referenceKey')} tooltip={t('tenantCredentials.referenceKeyTooltip')}>
            <Input placeholder="default" />
          </Form.Item>

          <Form.Item
            name="data"
            label={t('tenantCredentials.dataJson')}
            tooltip='Es. per xai: {"api_key": "..."} - per livekit: {"url": "wss://...", "api_key": "...", "api_secret": "..."}'
            rules={[{ required: true, message: t('tenantCredentials.enterDataJson') }]}
          >
            <TextArea rows={6} />
          </Form.Item>

          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('tenantCredentials.encryptionNotice')}
          />

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={saving}>
                {t('common.save')}
              </Button>
              <Button onClick={() => setModalOpen(false)}>{t('common.cancel')}</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default TenantCredentials
