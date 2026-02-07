import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Modal, Form, Select, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card, Row, Col, Divider, Spin
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, HistoryOutlined, EyeOutlined, ApiOutlined, CheckOutlined, EyeInvisibleOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as credentialsApi from '../api/credentials'

const { Title, Text } = Typography
const { TextArea } = Input

function Projects() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState(null)
  const [form] = Form.useForm()

  // Credentials state
  const [credentials, setCredentials] = useState([])
  const [credentialsLoading, setCredentialsLoading] = useState(false)
  const [credModalOpen, setCredModalOpen] = useState(false)
  const [credForm] = Form.useForm()
  const [selectedServiceType, setSelectedServiceType] = useState(null)
  const [selectedProvider, setSelectedProvider] = useState(null)
  const [testingCredential, setTestingCredential] = useState(null)

  useEffect(() => {
    loadProjects()
  }, [page, pageSize, search])

  const loadProjects = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (search) params.search = search
      const data = await projectsApi.getProjects(params)
      setProjects(data.projects || data)
      setTotal(data.total || data.length)
    } catch (error) {
      message.error('Errore caricamento progetti')
    } finally {
      setLoading(false)
    }
  }

  const openModal = async (project = null) => {
    setEditingProject(project)
    form.resetFields()
    if (project) {
      form.setFieldsValue({
        name: project.name,
        slug: project.slug,
        description: project.description,
        is_active: project.is_active,
        voice_engine: project.voice_engine || 'openai_realtime',
        call_direction: project.call_direction || 'inbound',
        vapi_assistant_id: project.vapi_assistant_id,
        twilio_phone_number: project.twilio_phone_number,
        vapi_phone_number_id: project.vapi_phone_number_id,
        elevenlabs_voice_id: project.elevenlabs_voice_id,
      })
      // Load credentials for this project
      await loadCredentials(project.id)
    } else {
      form.setFieldsValue({
        is_active: true,
        voice_engine: 'openai_realtime',
        call_direction: 'inbound',
      })
      setCredentials([])
    }
    setModalOpen(true)
  }

  const loadCredentials = async (projectId) => {
    setCredentialsLoading(true)
    try {
      const creds = await credentialsApi.getProjectCredentials(projectId)
      setCredentials(creds)
    } catch (error) {
      message.error('Errore caricamento credenziali')
    } finally {
      setCredentialsLoading(false)
    }
  }

  const openCredentialModal = () => {
    credForm.resetFields()
    setSelectedServiceType(null)
    setSelectedProvider(null)
    setCredModalOpen(true)
  }

  const handleCredentialSubmit = async (values) => {
    if (!editingProject) {
      message.error('Salva prima il progetto')
      return
    }

    try {
      const credData = {
        service_type: values.service_type,
        provider: values.provider,
        credential_key: values.credential_key || 'default',
        data: {},
      }

      // Build data object based on provider
      if (values.provider === 'vapi') {
        credData.data = { api_key: values.api_key }
      } else if (values.provider === 'twilio') {
        credData.data = {
          account_sid: values.account_sid,
          auth_token: values.auth_token,
        }
      } else if (values.provider === 'elevenlabs') {
        credData.data = { api_key: values.api_key }
      } else if (values.provider === 'hubspot') {
        credData.data = { access_token: values.access_token }
      } else if (values.provider === 'generic_webhook') {
        credData.data = { secret: values.secret || '' }
      }

      await credentialsApi.createProjectCredential(editingProject.id, credData)
      message.success('Credenziali salvate')
      setCredModalOpen(false)
      await loadCredentials(editingProject.id)
    } catch (error) {
      message.error(error.message || 'Errore salvataggio credenziali')
    }
  }

  const handleDeleteCredential = async (credentialId) => {
    try {
      await credentialsApi.deleteProjectCredential(editingProject.id, credentialId)
      message.success('Credenziali eliminate')
      await loadCredentials(editingProject.id)
    } catch (error) {
      message.error('Errore eliminazione credenziali')
    }
  }

  const handleTestCredential = async (credentialId) => {
    setTestingCredential(credentialId)
    try {
      const result = await credentialsApi.testProjectCredential(editingProject.id, credentialId)
      if (result.success) {
        message.success(result.message || 'Connessione riuscita')
      } else {
        message.error(result.message || 'Connessione fallita')
      }
    } catch (error) {
      message.error('Errore test connessione')
    } finally {
      setTestingCredential(null)
    }
  }

  const providersByServiceType = {
    voice: [{ value: 'vapi', label: 'Vapi.ai' }],
    telephony: [{ value: 'twilio', label: 'Twilio' }],
    tts: [{ value: 'elevenlabs', label: 'ElevenLabs' }],
    crm: [
      { value: 'hubspot', label: 'HubSpot' },
      { value: 'generic_webhook', label: 'Generic Webhook' },
    ],
    calendar: [
      { value: 'google_calendar', label: 'Google Calendar' },
      { value: 'ms_graph', label: 'Microsoft Graph' },
    ],
  }

  const renderCredentialFields = () => {
    if (!selectedProvider) return null

    const commonStyle = { marginBottom: 16 }

    if (selectedProvider === 'vapi') {
      return (
        <Form.Item
          name="api_key"
          label="API Key"
          rules={[{ required: true, message: 'Inserisci API Key' }]}
          style={commonStyle}
        >
          <Input.Password placeholder="sk-..." />
        </Form.Item>
      )
    }

    if (selectedProvider === 'twilio') {
      return (
        <>
          <Form.Item
            name="account_sid"
            label="Account SID"
            rules={[{ required: true, message: 'Inserisci Account SID' }]}
            style={commonStyle}
          >
            <Input placeholder="AC..." />
          </Form.Item>
          <Form.Item
            name="auth_token"
            label="Auth Token"
            rules={[{ required: true, message: 'Inserisci Auth Token' }]}
            style={commonStyle}
          >
            <Input.Password />
          </Form.Item>
        </>
      )
    }

    if (selectedProvider === 'elevenlabs') {
      return (
        <Form.Item
          name="api_key"
          label="API Key"
          rules={[{ required: true, message: 'Inserisci API Key' }]}
          style={commonStyle}
        >
          <Input.Password />
        </Form.Item>
      )
    }

    if (selectedProvider === 'hubspot') {
      return (
        <Form.Item
          name="access_token"
          label="Access Token"
          rules={[{ required: true, message: 'Inserisci Access Token' }]}
          style={commonStyle}
        >
          <Input.Password />
        </Form.Item>
      )
    }

    if (selectedProvider === 'generic_webhook') {
      return (
        <Form.Item name="secret" label="Secret (opzionale)" style={commonStyle}>
          <Input.Password placeholder="HMAC secret per firma webhook" />
        </Form.Item>
      )
    }

    return null
  }

  const handleSubmit = async (values) => {
    try {
      if (editingProject) {
        await projectsApi.updateProject(editingProject.id, values)
        message.success('Progetto aggiornato')
      } else {
        await projectsApi.createProject(values)
        message.success('Progetto creato')
      }
      setModalOpen(false)
      loadProjects()
    } catch (error) {
      const msg = error.response?.data?.detail || 'Errore'
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await projectsApi.deleteProject(id)
      message.success('Progetto disattivato')
      loadProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore')
    }
  }

  const columns = [
    {
      title: 'Nome',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{record.description}</Text>
        </Space>
      ),
    },
    {
      title: 'Slug',
      dataIndex: 'slug',
      key: 'slug',
      render: (slug) => <code>{slug}</code>,
    },
    {
      title: 'Stato',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? 'Attivo' : 'Inattivo'}</Tag>
      ),
    },
    {
      title: 'Engine',
      key: 'voice_engine',
      align: 'center',
      render: (_, record) => {
        const engine = record.voice_engine || 'openai_realtime'
        const direction = record.call_direction || 'inbound'
        return (
          <Space direction="vertical" size={0}>
            <Tag color={engine === 'vapi' ? 'cyan' : 'geekblue'}>
              {engine === 'vapi' ? 'Vapi' : 'OpenAI RT'}
            </Tag>
            <Tag color={direction === 'outbound' ? 'orange' : direction === 'both' ? 'purple' : 'default'} style={{ fontSize: 10 }}>
              {direction === 'outbound' ? 'Outbound' : direction === 'both' ? 'In+Out' : 'Inbound'}
            </Tag>
          </Space>
        )
      },
    },
    {
      title: 'Chiamate',
      dataIndex: 'call_count',
      key: 'calls',
      align: 'center',
      render: (count) => count || 0,
    },
    {
      title: 'Prompt A',
      key: 'prompt_a',
      align: 'center',
      render: (_, record) => (
        <Tag color={record.prompt_a ? 'blue' : 'default'}>
          {record.prompt_a ? `v${record.prompt_a_version || 1}` : 'Non configurato'}
        </Tag>
      ),
    },
    {
      title: 'Prompt B',
      key: 'prompt_b',
      align: 'center',
      render: (_, record) => (
        <Tag color={record.prompt_b ? 'purple' : 'default'}>
          {record.prompt_b ? `v${record.prompt_b_version || 1}` : 'Non configurato'}
        </Tag>
      ),
    },
    {
      title: 'Creato',
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => new Date(date).toLocaleDateString('it-IT'),
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title="Modifica Prompt">
            <Button
              icon={<EditOutlined />}
              size="small"
              type="primary"
              onClick={() => navigate(`/projects/${record.id}/edit`)}
            />
          </Tooltip>
          <Tooltip title="Storico Prompt">
            <Button
              icon={<HistoryOutlined />}
              size="small"
              onClick={() => navigate(`/projects/${record.id}/history`)}
            />
          </Tooltip>
          <Tooltip title="Impostazioni">
            <Button
              icon={<EyeOutlined />}
              size="small"
              onClick={() => openModal(record)}
            />
          </Tooltip>
          {record.slug !== 'default' && (
            <Popconfirm
              title="Disattivare questo progetto?"
              description="Il progetto non sarà più utilizzabile."
              onConfirm={() => handleDelete(record.id)}
              okText="Sì"
              cancelText="No"
            >
              <Tooltip title="Disattiva">
                <Button icon={<DeleteOutlined />} size="small" danger />
              </Tooltip>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>Progetti</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
          Nuovo Progetto
        </Button>
      </div>

      <Input
        placeholder="Cerca progetti..."
        prefix={<SearchOutlined />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ width: 250, marginBottom: 16 }}
        allowClear
      />

      <Table
        dataSource={projects}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
          showSizeChanger: true,
          showTotal: (t) => `Totale: ${t} progetti`,
        }}
      />

      <Modal
        title={editingProject ? 'Modifica Progetto' : 'Nuovo Progetto'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={800}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label="Nome"
            rules={[{ required: true, message: 'Inserisci nome' }]}
          >
            <Input placeholder="es: Screening Sviluppatori" />
          </Form.Item>
          <Form.Item
            name="slug"
            label="Slug"
            rules={[
              { required: true, message: 'Inserisci slug' },
              { pattern: /^[a-z0-9-]+$/, message: 'Solo lettere minuscole, numeri e trattini' },
            ]}
          >
            <Input disabled={!!editingProject} placeholder="es: screening-dev" />
          </Form.Item>
          <Form.Item
            name="description"
            label="Descrizione"
          >
            <TextArea rows={3} placeholder="Descrizione del progetto..." />
          </Form.Item>
          {editingProject && (
            <Form.Item name="is_active" label="Stato" valuePropName="checked">
              <Switch checkedChildren="Attivo" unCheckedChildren="Inattivo" />
            </Form.Item>
          )}
          <Divider orientation="left" style={{ fontSize: 13 }}>Voice Engine (M5)</Divider>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="voice_engine" label="Voice Engine">
                <Select
                  options={[
                    { value: 'openai_realtime', label: 'OpenAI Realtime (Inbound)' },
                    { value: 'vapi', label: 'Vapi + ElevenLabs (Outbound)' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="call_direction" label="Direzione Chiamata">
                <Select
                  options={[
                    { value: 'inbound', label: 'Solo Inbound' },
                    { value: 'outbound', label: 'Solo Outbound' },
                    { value: 'both', label: 'Inbound + Outbound' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.voice_engine !== curr.voice_engine}>
            {({ getFieldValue }) =>
              getFieldValue('voice_engine') === 'vapi' ? (
                <>
                  <Form.Item name="vapi_assistant_id" label="Vapi Assistant ID">
                    <Input placeholder="ID assistente Vapi (dalla dashboard Vapi)" />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item name="twilio_phone_number" label="Numero Twilio (da)">
                        <Input placeholder="+4915123456789" />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="vapi_phone_number_id" label="Vapi Phone Number ID">
                        <Input placeholder="ID numero in Vapi" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item name="elevenlabs_voice_id" label="ElevenLabs Voice ID">
                    <Input placeholder="ID voce ElevenLabs (tedesco)" />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingProject ? 'Salva' : 'Crea'}
              </Button>
              <Button onClick={() => setModalOpen(false)}>Annulla</Button>
            </Space>
          </Form.Item>
        </Form>

        {editingProject && (
          <>
            <Divider orientation="left">
              <Space>
                <ApiOutlined /> API Credentials (M5.5)
              </Space>
            </Divider>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 16 }}>
              Configura chiavi API specifiche per questo progetto. Se non configurate, verranno usate le chiavi globali da .env
            </Text>

            {credentialsLoading ? (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <Spin />
              </div>
            ) : (
              <>
                <Table
                  dataSource={credentials}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  style={{ marginBottom: 16 }}
                  columns={[
                    {
                      title: 'Service',
                      dataIndex: 'service_type',
                      key: 'service_type',
                      render: (type) => (
                        <Tag color="blue">{type}</Tag>
                      ),
                    },
                    {
                      title: 'Provider',
                      dataIndex: 'provider',
                      key: 'provider',
                      render: (provider) => <code>{provider}</code>,
                    },
                    {
                      title: 'Key',
                      dataIndex: 'credential_key',
                      key: 'key',
                      render: (key) => <Text type="secondary">{key}</Text>,
                    },
                    {
                      title: 'Status',
                      dataIndex: 'is_active',
                      key: 'status',
                      render: (active) => (
                        <Tag color={active ? 'green' : 'default'}>
                          {active ? 'Active' : 'Inactive'}
                        </Tag>
                      ),
                    },
                    {
                      title: 'Created',
                      dataIndex: 'created_at',
                      key: 'created',
                      render: (date) => new Date(date).toLocaleDateString('it-IT'),
                    },
                    {
                      title: 'Actions',
                      key: 'actions',
                      render: (_, record) => (
                        <Space size="small">
                          <Tooltip title="Test Connection">
                            <Button
                              icon={<CheckOutlined />}
                              size="small"
                              loading={testingCredential === record.id}
                              onClick={() => handleTestCredential(record.id)}
                            />
                          </Tooltip>
                          <Popconfirm
                            title="Eliminare credenziali?"
                            onConfirm={() => handleDeleteCredential(record.id)}
                            okText="Sì"
                            cancelText="No"
                          >
                            <Button icon={<DeleteOutlined />} size="small" danger />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
                <Button
                  type="dashed"
                  icon={<PlusOutlined />}
                  onClick={openCredentialModal}
                  block
                >
                  Aggiungi Credenziali
                </Button>
              </>
            )}
          </>
        )}
      </Modal>

      {/* Credential Modal */}
      <Modal
        title="Aggiungi API Credentials"
        open={credModalOpen}
        onCancel={() => setCredModalOpen(false)}
        footer={null}
        width={500}
      >
        <Form form={credForm} layout="vertical" onFinish={handleCredentialSubmit}>
          <Form.Item
            name="service_type"
            label="Service Type"
            rules={[{ required: true, message: 'Seleziona tipo servizio' }]}
          >
            <Select
              placeholder="Seleziona tipo servizio"
              onChange={(value) => {
                setSelectedServiceType(value)
                setSelectedProvider(null)
                credForm.setFieldsValue({ provider: undefined })
              }}
              options={[
                { value: 'voice', label: 'Voice Engine' },
                { value: 'telephony', label: 'Telephony' },
                { value: 'tts', label: 'Text-to-Speech' },
                { value: 'crm', label: 'CRM' },
                { value: 'calendar', label: 'Calendar' },
              ]}
            />
          </Form.Item>

          {selectedServiceType && (
            <Form.Item
              name="provider"
              label="Provider"
              rules={[{ required: true, message: 'Seleziona provider' }]}
            >
              <Select
                placeholder="Seleziona provider"
                onChange={setSelectedProvider}
                options={providersByServiceType[selectedServiceType] || []}
              />
            </Form.Item>
          )}

          <Form.Item
            name="credential_key"
            label="Reference Key (opzionale)"
            tooltip="Usa per gestire multiple credenziali dello stesso provider"
          >
            <Input placeholder="default" />
          </Form.Item>

          {renderCredentialFields()}

          {selectedProvider && (
            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit">
                  Salva
                </Button>
                <Button onClick={() => setCredModalOpen(false)}>Annulla</Button>
              </Space>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}

export default Projects
