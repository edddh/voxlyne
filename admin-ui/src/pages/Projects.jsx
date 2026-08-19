import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Modal, Form, Select, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card, Row, Col, Divider, Spin, Alert
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, HistoryOutlined, SettingOutlined, ApiOutlined, CheckOutlined, InfoCircleOutlined, ThunderboltOutlined, CopyOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as credentialsApi from '../api/credentials'
import * as templatesApi from '../api/templates'
import { useAuth } from '../hooks/useAuth'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const NEW_VOICE_ENGINES = ['livekit_xai', 'livekit_openai', 'xai_sip_direct', 'openai_sip_direct', 'elevenlabs_agent']

function Projects() {
  const navigate = useNavigate()
  const { isSuperAdmin } = useAuth()
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
  const [provisioningId, setProvisioningId] = useState(null)
  const [provisionResult, setProvisionResult] = useState(null)
  const [provisionModalOpen, setProvisionModalOpen] = useState(false)

  // "Crea da Template" (maintainer, 20/08: "anche crea da template non fa
  // nulla" - puntava alla pagina di gestione template, super_admin-only,
  // quindi per chiunque altro non faceva letteralmente nulla di visibile
  // - vedi GET /api/templates/assigned, app/routers/templates.py).
  const [fromTemplateModalOpen, setFromTemplateModalOpen] = useState(false)
  const [assignedTemplates, setAssignedTemplates] = useState([])
  const [loadingAssignedTemplates, setLoadingAssignedTemplates] = useState(false)
  const [creatingFromTemplate, setCreatingFromTemplate] = useState(false)
  const [fromTemplateForm] = Form.useForm()
  const noAutofillProps = {
    autoComplete: 'new-password',
    'data-lpignore': 'true',
    'data-1p-ignore': 'true',
  }

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
        language: project.language || 'it',
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
        language: 'it',
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
      } else if (values.provider === 'openai_realtime') {
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
        credData.data = {
          url: values.url,
          secret: values.secret || '',
        }
      } else if (values.provider === 'google_calendar') {
        credData.data = {
          access_token: values.access_token,
          refresh_token: values.refresh_token || '',
          client_id: values.client_id || '',
          client_secret: values.client_secret || '',
        }
      } else if (values.provider === 'ms_graph') {
        credData.data = {
          access_token: values.access_token,
          refresh_token: values.refresh_token || '',
          client_id: values.client_id || '',
          client_secret: values.client_secret || '',
          tenant_id: values.tenant_id || '',
        }
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

  const handleTestCredential = async (credential) => {
    const credentialId = credential.id
    setTestingCredential(credentialId)
    try {
      const result = await credentialsApi.testProjectCredential(editingProject.id, credentialId)
      if (result.success) {
        message.success(result.message || 'Connessione riuscita')
      } else {
        const isElevenLabs = credential.provider === 'elevenlabs'
        const missingVoicePermission = typeof result.error === 'string' && (
          result.error.includes('missing_permissions') || result.error.includes('voices_read')
        )
        if (isElevenLabs && missingVoicePermission) {
          message.error('Connessione fallita. Permessi richiesti ElevenLabs: Text to Speech = Access, Voices = Read')
        } else {
          message.error(result.message || 'Connessione fallita')
        }
      }
    } catch (error) {
      message.error('Errore test connessione')
    } finally {
      setTestingCredential(null)
    }
  }

  const providersByServiceType = {
    voice: [
      { value: 'vapi', label: 'Vapi.ai' },
      { value: 'openai_realtime', label: 'OpenAI Realtime' },
    ],
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
          <Input.Password placeholder="sk-..." {...noAutofillProps} />
        </Form.Item>
      )
    }

    if (selectedProvider === 'openai_realtime') {
      return (
        <Form.Item
          name="api_key"
          label="API Key"
          rules={[{ required: true, message: 'Inserisci API Key' }]}
          style={commonStyle}
        >
          <Input.Password placeholder="sk-..." {...noAutofillProps} />
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
            <Input.Password {...noAutofillProps} />
          </Form.Item>
        </>
      )
    }

    if (selectedProvider === 'elevenlabs') {
      return (
        <Form.Item
          name="api_key"
          label={(
            <Space size={6}>
              <span>API Key</span>
              <Tooltip title="Permessi richiesti in ElevenLabs: Text to Speech = Access, Voices = Read">
                <InfoCircleOutlined />
              </Tooltip>
            </Space>
          )}
          rules={[{ required: true, message: 'Inserisci API Key' }]}
          style={commonStyle}
        >
          <Input.Password {...noAutofillProps} />
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
          <Input.Password {...noAutofillProps} />
        </Form.Item>
      )
    }

    if (selectedProvider === 'generic_webhook') {
      return (
        <>
          <Form.Item
            name="url"
            label="Webhook URL"
            rules={[{ required: true, message: 'Inserisci Webhook URL' }]}
            style={commonStyle}
          >
            <Input placeholder="https://example.com/webhook" />
          </Form.Item>
          <Form.Item name="secret" label="Secret (opzionale)" style={commonStyle}>
            <Input.Password placeholder="HMAC secret per firma webhook" {...noAutofillProps} />
          </Form.Item>
        </>
      )
    }

    if (selectedProvider === 'google_calendar') {
      return (
        <>
          <Form.Item
            name="access_token"
            label="Access Token"
            rules={[{ required: true, message: 'Inserisci Access Token' }]}
            style={commonStyle}
          >
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="refresh_token" label="Refresh Token (opzionale)" style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="client_id" label="Client ID (opzionale)" style={commonStyle}>
            <Input />
          </Form.Item>
          <Form.Item name="client_secret" label="Client Secret (opzionale)" style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
        </>
      )
    }

    if (selectedProvider === 'ms_graph') {
      return (
        <>
          <Form.Item
            name="access_token"
            label="Access Token"
            rules={[{ required: true, message: 'Inserisci Access Token' }]}
            style={commonStyle}
          >
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="refresh_token" label="Refresh Token (opzionale)" style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="client_id" label="Client ID (opzionale)" style={commonStyle}>
            <Input />
          </Form.Item>
          <Form.Item name="client_secret" label="Client Secret (opzionale)" style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="tenant_id" label="Tenant ID (opzionale)" style={commonStyle}>
            <Input />
          </Form.Item>
        </>
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

  const handleProvisionRuntime = async (project) => {
    setProvisioningId(project.id)
    try {
      const result = await credentialsApi.provisionProjectRuntime(project.id)
      setProvisionResult(result)
      setProvisionModalOpen(true)
      message.success('Istanza runtime generata')
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nella generazione del runtime')
    } finally {
      setProvisioningId(null)
    }
  }

  const openFromTemplateModal = async () => {
    setFromTemplateModalOpen(true)
    fromTemplateForm.resetFields()
    setLoadingAssignedTemplates(true)
    try {
      const data = await templatesApi.getAssignedTemplates()
      setAssignedTemplates(data.templates || [])
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nel caricamento dei template assegnati')
    } finally {
      setLoadingAssignedTemplates(false)
    }
  }

  const handleCreateFromTemplate = async (values) => {
    setCreatingFromTemplate(true)
    try {
      const project = await projectsApi.createProjectFromTemplate(values.template_id, {
        name: values.name,
        slug: values.slug,
        description: values.description,
      })
      message.success(`Progetto "${project.name}" creato dal template`)
      setFromTemplateModalOpen(false)
      loadProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nella creazione del progetto')
    } finally {
      setCreatingFromTemplate(false)
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
      title: 'Lingua',
      dataIndex: 'language',
      key: 'language',
      align: 'center',
      render: (lang) => {
        const flags = { it: '🇮🇹', en: '🇬🇧', es: '🇪🇸', fr: '🇫🇷', de: '🇩🇪' }
        return <span>{flags[lang] || '🌐'} {(lang || 'it').toUpperCase()}</span>
      },
    },
    {
      title: 'Engine',
      key: 'voice_engine',
      align: 'center',
      render: (_, record) => {
        const engine = record.voice_engine || 'openai_realtime'
        const direction = record.call_direction || 'inbound'
        const ENGINE_LABELS = {
          openai_realtime: 'OpenAI RT',
          vapi: 'Vapi',
          livekit_xai: 'LiveKit + xAI',
          livekit_openai: 'LiveKit + OpenAI',
          xai_sip_direct: 'SIP diretto + xAI',
          openai_sip_direct: 'SIP diretto + OpenAI',
          elevenlabs_agent: 'ElevenLabs Agent',
        }
        const ENGINE_COLORS = {
          openai_realtime: 'geekblue',
          vapi: 'cyan',
          livekit_xai: 'volcano',
          livekit_openai: 'volcano',
          xai_sip_direct: 'gold',
          openai_sip_direct: 'gold',
          elevenlabs_agent: 'magenta',
        }
        return (
          <Space direction="vertical" size={0}>
            <Tag color={ENGINE_COLORS[engine] || 'default'}>
              {ENGINE_LABELS[engine] || engine}
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
              icon={<SettingOutlined />}
              size="small"
              onClick={() => openModal(record)}
            />
          </Tooltip>
          <Tooltip title="Configura (SIP, CRM, Calendar)">
            <Button
              icon={<ApiOutlined />}
              size="small"
              onClick={() => navigate(`/projects/${record.id}/config`)}
            />
          </Tooltip>
          {isSuperAdmin && NEW_VOICE_ENGINES.includes(record.voice_engine) && (
            // maintainer, 20/08: "non si riuscirebbe a evitare 'Genera
            // servizio runtime'? mi sembra una cosa che va al di la'
            // delle funzionalita' tipiche di un admin di tenant" -
            // azione infrastrutturale, stesso require_roles(["super_
            // admin"]) del backend (era ["admin","super_admin"]).
            <Tooltip title="Genera servizio runtime (config + systemd, come earlier-prototype) - solo super admin">
              <Button
                icon={<ThunderboltOutlined />}
                size="small"
                loading={provisioningId === record.id}
                onClick={() => handleProvisionRuntime(record)}
              />
            </Tooltip>
          )}
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
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>Progetti</Title>
        <Space>
          <Button type="default" onClick={openFromTemplateModal}>
            Crea da Template
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
            Nuovo Progetto
          </Button>
        </Space>
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
        scroll={{ x: 'max-content' }}
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
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="language" label="Lingua chiamata">
                <Select
                  options={[
                    { value: 'it', label: '🇮🇹 Italiano' },
                    { value: 'en', label: '🇬🇧 English' },
                    { value: 'es', label: '🇪🇸 Español' },
                    { value: 'fr', label: '🇫🇷 Français' },
                    { value: 'de', label: '🇩🇪 Deutsch' },
                  ]}
                />
              </Form.Item>
            </Col>
            {editingProject && (
              <Col xs={24} sm={12}>
                <Form.Item name="is_active" label="Stato" valuePropName="checked">
                  <Switch checkedChildren="Attivo" unCheckedChildren="Inattivo" />
                </Form.Item>
              </Col>
            )}
          </Row>
          <Divider orientation="left" style={{ fontSize: 13 }}>Voice Engine (M5)</Divider>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="voice_engine" label="Voice Engine">
                <Select
                  options={[
                    { value: 'openai_realtime', label: 'OpenAI Realtime (Inbound)' },
                    { value: 'vapi', label: 'Vapi + ElevenLabs (Outbound)' },
                    { value: 'livekit_xai', label: 'LiveKit + xAI (Inbound, in sviluppo)' },
                    { value: 'livekit_openai', label: 'LiveKit + OpenAI (Inbound, in sviluppo)' },
                    { value: 'xai_sip_direct', label: 'SIP diretto + xAI voice-to-voice (Inbound, in sviluppo)' },
                    { value: 'openai_sip_direct', label: 'SIP diretto + OpenAI (Inbound, in sviluppo)' },
                    { value: 'elevenlabs_agent', label: 'ElevenLabs Agent (Inbound, in sviluppo)' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item noStyle shouldUpdate={(prev, curr) => prev.voice_engine !== curr.voice_engine}>
                {({ getFieldValue }) => {
                  const isNewProvider = NEW_VOICE_ENGINES.includes(getFieldValue('voice_engine'))
                  return (
                    <Form.Item name="call_direction" label="Direzione Chiamata">
                      <Select
                        options={
                          isNewProvider
                            ? [{ value: 'inbound', label: 'Solo Inbound' }]
                            : [
                                { value: 'inbound', label: 'Solo Inbound' },
                                { value: 'outbound', label: 'Solo Outbound' },
                                { value: 'both', label: 'Inbound + Outbound' },
                              ]
                        }
                      />
                    </Form.Item>
                  )
                }}
              </Form.Item>
            </Col>
          </Row>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.voice_engine !== curr.voice_engine}>
            {({ getFieldValue }) =>
              NEW_VOICE_ENGINES.includes(getFieldValue('voice_engine')) ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="Provider in fase di completamento"
                  description="Questo motore vocale è stato importato da earlier-prototype (voice_core/runtime) ma non è ancora collegato alla pipeline di simulazione di test: selezionabile e salvabile, ma una chiamata in ingresso userà ancora il fallback finché l'integrazione non è completata (vedi README, Milestone 5)."
                />
              ) : null
            }
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.voice_engine !== curr.voice_engine}>
            {({ getFieldValue }) =>
              getFieldValue('voice_engine') === 'vapi' ? (
                <>
                  <Form.Item name="vapi_assistant_id" label="Vapi Assistant ID">
                    <Input placeholder="ID assistente Vapi (dalla dashboard Vapi)" />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col xs={24} sm={12}>
                      <Form.Item name="twilio_phone_number" label="Numero Twilio (da)">
                        <Input placeholder="+4915123456789" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12}>
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
              Solo per eccezioni: queste credenziali valgono solo per questo progetto e hanno la precedenza
              su tutto il resto. Normalmente non serve configurare nulla qui — il progetto eredita
              automaticamente le chiavi API del tenant (Tenant → Credenziali); solo se il tenant non ne ha,
              si usa il fallback globale da .env.
            </Text>

            {credentialsLoading ? (
              <div style={{ textAlign: 'center', padding: 20 }}>
                <Spin />
              </div>
            ) : (
              <>
                <Table
                  scroll={{ x: 'max-content' }}
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
                              onClick={() => handleTestCredential(record)}
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
        <Form form={credForm} layout="vertical" onFinish={handleCredentialSubmit} autoComplete="off">
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

      <Modal
        title="Servizio runtime generato"
        open={provisionModalOpen}
        onCancel={() => setProvisionModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setProvisionModalOpen(false)}>
            Chiudi
          </Button>,
        ]}
        width={720}
      >
        {provisionResult && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`Progetto "${provisionResult.project_slug}" - motore ${provisionResult.engine_type} - porta ${provisionResult.port}`}
              description="Config, credenziali (dal Credentials Manager del tenant/progetto) e systemd unit sono stati scritti su disco. L'app non ha i permessi di root: esegui questi comandi sul server per attivare il servizio."
            />
            <Paragraph>
              <Text strong>File generati:</Text>
              <br />
              <Text code>{provisionResult.config_path}</Text>
              <br />
              <Text code>{provisionResult.env_path}</Text>
              <br />
              <Text code>{provisionResult.start_script_path}</Text>
            </Paragraph>
            <Paragraph>
              <Text strong>Comandi da eseguire (sudo):</Text>
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflowX: 'auto' }}>
                {provisionResult.install_commands.join('\n')}
              </pre>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={() => {
                  navigator.clipboard.writeText(provisionResult.install_commands.join('\n'))
                  message.success('Copiato negli appunti')
                }}
              >
                Copia comandi
              </Button>
            </Paragraph>
          </>
        )}
      </Modal>

      <Modal
        title="Crea da Template"
        open={fromTemplateModalOpen}
        onCancel={() => setFromTemplateModalOpen(false)}
        footer={null}
        width={600}
      >
        {loadingAssignedTemplates ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : assignedTemplates.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="Nessun template assegnato"
            description="Il tuo tenant non ha ancora nessun template assegnato - contatta un super admin per farne assegnare uno dalla pagina Template."
          />
        ) : (
          <Form form={fromTemplateForm} layout="vertical" onFinish={handleCreateFromTemplate}>
            <Form.Item
              name="template_id"
              label="Template"
              rules={[{ required: true, message: 'Seleziona un template' }]}
            >
              <Select
                placeholder="Scegli un template..."
                options={assignedTemplates.map((t) => ({
                  value: t.id,
                  label: t.template_category ? `${t.name} (${t.template_category})` : t.name,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="name"
              label="Nome del nuovo progetto"
              rules={[{ required: true, message: 'Inserisci nome' }]}
            >
              <Input placeholder="es: Comune di Sampletown - URP" />
            </Form.Item>
            <Form.Item
              name="slug"
              label="Slug"
              rules={[
                { required: true, message: 'Inserisci slug' },
                { pattern: /^[a-z0-9-]+$/, message: 'Solo lettere minuscole, numeri e trattini' },
              ]}
            >
              <Input placeholder="es: comune-sampletown-urp" />
            </Form.Item>
            <Form.Item name="description" label="Descrizione (opzionale)">
              <TextArea rows={2} />
            </Form.Item>
            <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
              Copia prompt, frase di apertura, voce, lingua e configurazione output del template.
              Numero di telefono e credenziali restano da collegare separatamente per il nuovo progetto.
            </Text>
            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={creatingFromTemplate}>
                  Crea progetto
                </Button>
                <Button onClick={() => setFromTemplateModalOpen(false)}>Annulla</Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  )
}

export default Projects
