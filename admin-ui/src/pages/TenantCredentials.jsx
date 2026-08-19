import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Modal, Form, Input, Select, message, Tag, Popconfirm,
  Typography, Tooltip, Alert,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ArrowLeftOutlined, ApiOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
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
      message.error('Errore caricamento tenant')
    }
  }

  const loadCredentials = async () => {
    setLoading(true)
    try {
      const data = await credentialsApi.getTenantCredentials(tenantId)
      setCredentials(data)
    } catch (error) {
      message.error('Errore caricamento credenziali')
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
      message.error('Il campo "Dati" deve essere JSON valido, es: {"api_key": "..."}')
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
      message.success('Credenziale salvata come default per il tenant')
      setModalOpen(false)
      loadCredentials()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (credentialId) => {
    try {
      await credentialsApi.deleteTenantCredential(tenantId, credentialId)
      message.success('Credenziale eliminata')
      loadCredentials()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore eliminazione')
    }
  }

  const handleTest = async (credentialId) => {
    setTestingId(credentialId)
    try {
      const result = await credentialsApi.testTenantCredential(tenantId, credentialId)
      if (result.success) {
        message.success(result.message || 'Connessione riuscita')
      } else {
        message.error(result.message || 'Connessione fallita')
      }
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore test connessione')
    } finally {
      setTestingId(null)
    }
  }

  const columns = [
    { title: 'Categoria', dataIndex: 'service_type', key: 'service_type', render: (v) => <Tag>{v}</Tag> },
    { title: 'Provider', dataIndex: 'provider', key: 'provider' },
    { title: 'Chiave', dataIndex: 'credential_key', key: 'credential_key', render: (v) => <code>{v}</code> },
    {
      title: 'Stato',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => <Tag color={active ? 'green' : 'red'}>{active ? 'Attiva' : 'Disattivata'}</Tag>,
    },
    {
      title: 'Ultimo utilizzo',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (v) => (v ? new Date(v).toLocaleString('it-IT') : '—'),
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title="Testa connessione">
            <Button
              icon={<ApiOutlined />}
              size="small"
              loading={testingId === record.id}
              onClick={() => handleTest(record.id)}
            />
          </Tooltip>
          <Popconfirm
            title="Eliminare questa credenziale?"
            onConfirm={() => handleDelete(record.id)}
            okText="Sì"
            cancelText="No"
          >
            <Tooltip title="Elimina">
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
          Torna ai tenant
        </Button>
      </Space>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Title level={3} style={{ margin: 0 }}>
          Credenziali - {tenant?.name || tenantId}
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openModal}>
          Nuova credenziale
        </Button>
      </div>

      <Paragraph type="secondary">
        Queste credenziali (chiavi API LLM, voce, telefonia, CRM, calendario) sono il
        default per <b>tutti i progetti di questo tenant</b>. Un progetto può impostare
        una propria credenziale per lo stesso servizio/provider per sovrascrivere il
        default del tenant; se nessuna delle due è presente si usa la variabile
        d'ambiente globale (.env) come ultimo fallback.
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
        title="Nuova credenziale tenant"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="service_type"
            label="Categoria"
            rules={[{ required: true, message: 'Seleziona una categoria' }]}
          >
            <Select
              placeholder="Seleziona categoria"
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
                  rules={[{ required: true, message: 'Seleziona o inserisci un provider' }]}
                >
                  <Select
                    placeholder="Seleziona provider"
                    options={providerOptions.map((p) => ({ value: p, label: p }))}
                    showSearch
                    allowClear
                    // Provider names beyond the known list (e.g. new/custom
                    // ones) can still be typed - the backend accepts any string.
                    onSearch={() => {}}
                    notFoundContent="Digita un nome provider personalizzato"
                  />
                </Form.Item>
              )
            }}
          </Form.Item>

          <Form.Item name="credential_key" label="Chiave di riferimento" tooltip="Utile per avere più credenziali per lo stesso provider (es. 'main', 'backup')">
            <Input placeholder="default" />
          </Form.Item>

          <Form.Item
            name="data"
            label="Dati (JSON)"
            tooltip='Es. per xai: {"api_key": "..."} - per livekit: {"url": "wss://...", "api_key": "...", "api_secret": "..."}'
            rules={[{ required: true, message: 'Inserisci i dati della credenziale in formato JSON' }]}
          >
            <TextArea rows={6} />
          </Form.Item>

          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="I dati verranno cifrati prima di essere salvati nel database."
          />

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={saving}>
                Salva
              </Button>
              <Button onClick={() => setModalOpen(false)}>Annulla</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default TenantCredentials
