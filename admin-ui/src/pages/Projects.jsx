import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Modal, Form, Select, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card, Row, Col, Divider, Spin, Alert
} from 'antd'
import { PlusOutlined, EditOutlined, SearchOutlined, HistoryOutlined, SettingOutlined, ApiOutlined, CheckOutlined, InfoCircleOutlined, ThunderboltOutlined, CopyOutlined, DeleteOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as projectsApi from '../api/projects'
import * as credentialsApi from '../api/credentials'
import * as templatesApi from '../api/templates'
import { useAuth } from '../hooks/useAuth'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const NEW_VOICE_ENGINES = ['livekit_xai', 'livekit_openai', 'xai_sip_direct', 'openai_sip_direct', 'elevenlabs_agent']

function Projects() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const { isSuperAdmin, isAdmin } = useAuth()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('active')
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
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const noAutofillProps = {
    autoComplete: 'new-password',
    'data-lpignore': 'true',
    'data-1p-ignore': 'true',
  }

  useEffect(() => {
    loadProjects()
  }, [page, pageSize, search, statusFilter])

  const loadProjects = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (search) params.search = search
      if (statusFilter === 'active') params.active_only = true
      if (statusFilter === 'inactive') params.active_only = false
      if (statusFilter === 'all') params.active_only = null
      const data = await projectsApi.getProjects(params)
      const rawProjects = data.projects || data
      setProjects(rawProjects)
      setTotal(data.total || rawProjects.length)
    } catch (error) {
      message.error(t('projects.loadError'))
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
        language: project.language || 'en',
        voice_engine: project.voice_engine || 'xai_sip_direct',
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
        language: 'en',
        voice_engine: 'xai_sip_direct',
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
      message.error(t('projects.loadCredentialsError'))
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
      message.error(t('projects.saveProjectFirst'))
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
      message.success(t('projects.credentialsSaved'))
      setCredModalOpen(false)
      credForm.resetFields()
      setSelectedServiceType(null)
      setSelectedProvider(null)
      await loadCredentials(editingProject.id)
    } catch (error) {
      message.error(error.message || t('projects.credentialsSaveError'))
    }
  }

  const handleDeleteCredential = async (credentialId) => {
    try {
      await credentialsApi.deleteProjectCredential(editingProject.id, credentialId)
      message.success(t('projects.credentialsDeleted'))
      await loadCredentials(editingProject.id)
    } catch (error) {
      message.error(t('projects.credentialsDeleteError'))
    }
  }

  const handleTestCredential = async (credential) => {
    const credentialId = credential.id
    setTestingCredential(credentialId)
    try {
      const result = await credentialsApi.testProjectCredential(editingProject.id, credentialId)
      if (result.success) {
        message.success(result.message || t('tenantCredentials.connectionOk'))
      } else {
        const isElevenLabs = credential.provider === 'elevenlabs'
        const missingVoicePermission = typeof result.error === 'string' && (
          result.error.includes('missing_permissions') || result.error.includes('voices_read')
        )
        if (isElevenLabs && missingVoicePermission) {
          message.error(t('projects.elevenPermissionsError'))
        } else {
          message.error(result.message || t('tenantCredentials.connectionFailed'))
        }
      }
    } catch (error) {
      message.error(t('tenantCredentials.testError'))
    } finally {
      setTestingCredential(null)
    }
  }

  const providersByServiceType = {
    voice: [
      { value: 'vapi', label: 'Vapi.ai' },
      { value: 'openai_realtime', label: 'OpenAI Realtime' },
      { value: 'xai', label: 'xAI (Grok Voice)' },
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
          rules={[{ required: true, message: t('projects.enterApiKey') }]}
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
          rules={[{ required: true, message: t('projects.enterApiKey') }]}
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
            rules={[{ required: true, message: t('projects.enterAccountSid') }]}
            style={commonStyle}
          >
            <Input placeholder="AC..." />
          </Form.Item>
          <Form.Item
            name="auth_token"
            label="Auth Token"
            rules={[{ required: true, message: t('projects.enterAuthToken') }]}
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
              <Tooltip title={t('projects.elevenPermissionsTooltip')}>
                <InfoCircleOutlined />
              </Tooltip>
            </Space>
          )}
          rules={[{ required: true, message: t('projects.enterApiKey') }]}
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
          rules={[{ required: true, message: t('projects.enterAccessToken') }]}
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
            rules={[{ required: true, message: t('projects.enterWebhookUrl') }]}
            style={commonStyle}
          >
            <Input placeholder="https://example.com/webhook" />
          </Form.Item>
          <Form.Item name="secret" label={t('projects.secretOptional')} style={commonStyle}>
            <Input.Password placeholder={t('projects.hmacSecretPlaceholder')} {...noAutofillProps} />
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
            rules={[{ required: true, message: t('projects.enterAccessToken') }]}
            style={commonStyle}
          >
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="refresh_token" label={t('projects.refreshTokenOptional')} style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="client_id" label={t('projects.clientIdOptional')} style={commonStyle}>
            <Input />
          </Form.Item>
          <Form.Item name="client_secret" label={t('projects.clientSecretOptional')} style={commonStyle}>
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
            rules={[{ required: true, message: t('projects.enterAccessToken') }]}
            style={commonStyle}
          >
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="refresh_token" label={t('projects.refreshTokenOptional')} style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="client_id" label={t('projects.clientIdOptional')} style={commonStyle}>
            <Input />
          </Form.Item>
          <Form.Item name="client_secret" label={t('projects.clientSecretOptional')} style={commonStyle}>
            <Input.Password {...noAutofillProps} />
          </Form.Item>
          <Form.Item name="tenant_id" label={t('projects.tenantIdOptional')} style={commonStyle}>
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
        message.success(t('projects.updated'))
      } else {
        await projectsApi.createProject(values)
        message.success(t('projects.created'))
      }
      setModalOpen(false)
      loadProjects()
    } catch (error) {
      const msg = error.response?.data?.detail || t('projects.createError')
      if (!editingProject && error.response?.status === 409 && /slug/i.test(msg)) {
        form.setFields([{ name: 'slug', errors: [msg] }])
        return
      }
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await projectsApi.deleteProject(id)
      message.success(t('projects.deactivated'))
      loadProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || t('common.error'))
    }
  }

  const handleReactivate = async (project) => {
    try {
      await projectsApi.updateProject(project.id, { is_active: true })
      message.success(t('projects.reactivated'))
      loadProjects()
    } catch (error) {
      message.error(error.response?.data?.detail || t('common.error'))
    }
  }

  const handleProvisionRuntime = async (project) => {
    setProvisioningId(project.id)
    try {
      const result = await credentialsApi.provisionProjectRuntime(project.id)
      setProvisionResult(result)
      setProvisionModalOpen(true)
      message.success(t('projects.runtimeGenerated'))
    } catch (error) {
      message.error(error.response?.data?.detail || t('projects.runtimeGenerationError'))
    } finally {
      setProvisioningId(null)
    }
  }

  const openFromTemplateModal = async () => {
    setFromTemplateModalOpen(true)
    setSelectedTemplate(null)
    fromTemplateForm.resetFields()
    setLoadingAssignedTemplates(true)
    try {
      const data = await templatesApi.getAssignedTemplates()
      setAssignedTemplates(data.templates || [])
    } catch (error) {
      message.error(error.response?.data?.detail || t('projects.loadAssignedTemplatesError'))
    } finally {
      setLoadingAssignedTemplates(false)
    }
  }

  // maintainer, 20/08: "il template dovrebbe avere dei campi custom che
  // chiede di riempire quando si effettua l'importazione" - appena si
  // sceglie un template, i suoi {{key}} diventano campi del form,
  // pre-compilati con i valori di default del template.
  const handleTemplateSelect = (templateId) => {
    const template = assignedTemplates.find((t) => t.id === templateId)
    setSelectedTemplate(template || null)
    const varFields = {}
    for (const field of template?.custom_variables_schema || []) {
      varFields[`var__${field.key}`] = template.custom_variables?.[field.key] ?? field.default ?? ''
    }
    fromTemplateForm.setFieldsValue(varFields)
  }

  const handleCreateFromTemplate = async (values) => {
    setCreatingFromTemplate(true)
    try {
      const customVariables = {}
      for (const field of selectedTemplate?.custom_variables_schema || []) {
        customVariables[field.key] = values[`var__${field.key}`] || ''
      }
      const project = await projectsApi.createProjectFromTemplate(values.template_id, {
        name: values.name,
        slug: values.slug,
        description: values.description,
        customVariables,
      })
      message.success(t('projects.createdFromTemplate', { name: project.name }))
      setFromTemplateModalOpen(false)
      loadProjects()
    } catch (error) {
      const msg = error.response?.data?.detail || t('projects.createError')
      if (error.response?.status === 409 && /slug/i.test(msg)) {
        fromTemplateForm.setFields([{ name: 'slug', errors: [msg] }])
        return
      }
      message.error(msg)
    } finally {
      setCreatingFromTemplate(false)
    }
  }

  const columns = [
    {
      title: t('tenants.name'),
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space direction="vertical" size={0} style={{ maxWidth: 320 }}>
          <Text strong>{name}</Text>
          <Paragraph
            type="secondary"
            style={{ fontSize: 12, marginBottom: 0 }}
            ellipsis={{ rows: 2, tooltip: record.description }}
          >
            {record.description}
          </Paragraph>
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
      title: t('tenantCredentials.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? t('tenants.activeStatus') : t('tenants.inactiveStatus')}</Tag>
      ),
    },
    {
      title: t('projects.language'),
      dataIndex: 'language',
      key: 'language',
      align: 'center',
      render: (lang) => {
        const flags = { it: '🇮🇹', en: '🇬🇧', es: '🇪🇸', fr: '🇫🇷', de: '🇩🇪' }
        return <span>{flags[lang] || '🌐'} {(lang || 'en').toUpperCase()}</span>
      },
    },
    {
      title: 'Engine',
      key: 'voice_engine',
      align: 'center',
      render: (_, record) => {
        const engine = record.voice_engine || 'xai_sip_direct'
        const direction = record.call_direction || 'inbound'
        const ENGINE_LABELS = {
          openai_realtime: 'OpenAI RT',
          vapi: 'Vapi',
          livekit_xai: 'LiveKit + xAI',
          livekit_openai: 'LiveKit + OpenAI',
          xai_sip_direct: t('projects.directSipXai'),
          openai_sip_direct: t('projects.directSipOpenai'),
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
              {direction === 'outbound' ? t('projects.outbound') : direction === 'both' ? t('projects.inOut') : t('projects.inbound')}
            </Tag>
          </Space>
        )
      },
    },
    {
      title: t('dashboard.calls'),
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
          {record.prompt_a ? `v${record.prompt_a_version || 1}` : t('projects.notConfigured')}
        </Tag>
      ),
    },
    {
      title: 'Prompt B',
      key: 'prompt_b',
      align: 'center',
      render: (_, record) => (
        <Tag color={record.prompt_b ? 'purple' : 'default'}>
          {record.prompt_b ? `v${record.prompt_b_version || 1}` : t('projects.notConfigured')}
        </Tag>
      ),
    },
    {
      title: t('tenants.createdColumn'),
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => new Date(date).toLocaleDateString(i18n.language),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          {record.is_active && (
            <Tooltip title={t('projects.editPrompt')}>
              <Button
                icon={<EditOutlined />}
                size="small"
                type="primary"
                onClick={() => navigate(`/projects/${record.id}/edit`)}
              />
            </Tooltip>
          )}
          <Tooltip title={t('projects.promptHistory')}>
            <Button
              icon={<HistoryOutlined />}
              size="small"
              onClick={() => navigate(`/projects/${record.id}/history`)}
            />
          </Tooltip>
          <Tooltip title={record.is_active ? t('projects.settings') : t('projects.detailsReactivate')}>
            <Button
              icon={<SettingOutlined />}
              size="small"
              onClick={() => openModal(record)}
            />
          </Tooltip>
          {record.is_active && (
            <Tooltip title={t('projects.configureTooltip')}>
              <Button
                icon={<ApiOutlined />}
                size="small"
                onClick={() => navigate(`/projects/${record.id}/config`)}
              />
            </Tooltip>
          )}
          {isSuperAdmin && NEW_VOICE_ENGINES.includes(record.voice_engine) && (
            // maintainer, 20/08: "non si riuscirebbe a evitare 'Genera
            // servizio runtime'? mi sembra una cosa che va al di la'
            // delle funzionalita' tipiche di un admin di tenant" -
            // azione infrastrutturale, stesso require_roles(["super_
            // admin"]) del backend (era ["admin","super_admin"]).
            <Tooltip title={t('projects.generateRuntimeTooltip')}>
              <Button
                icon={<ThunderboltOutlined />}
                size="small"
                loading={provisioningId === record.id}
                onClick={() => handleProvisionRuntime(record)}
              />
            </Tooltip>
          )}
          {record.slug !== 'default' && record.is_active && (
            <Popconfirm
              title={t('projects.confirmDeactivate')}
              description={t('projects.confirmDeactivateDescription')}
              onConfirm={() => handleDelete(record.id)}
              okText={t('promptHistory.yes')}
              cancelText={t('promptHistory.no')}
            >
              <Tooltip title={t('tenants.deactivate')}>
                <Button icon={<PauseCircleOutlined />} size="small" danger />
              </Tooltip>
            </Popconfirm>
          )}
          {record.slug !== 'default' && !record.is_active && (
            <Popconfirm
              title={t('projects.confirmReactivate')}
              description={t('projects.confirmReactivateDescription')}
              onConfirm={() => handleReactivate(record)}
              okText={t('promptHistory.yes')}
              cancelText={t('promptHistory.no')}
            >
              <Tooltip title={t('projects.reactivate')}>
                <Button icon={<PlayCircleOutlined />} size="small" />
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
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{t('nav.projects')}</Title>
        <Space>
          <Button type="default" onClick={openFromTemplateModal}>
            {t('projects.createFromTemplate')}
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
            {t('projects.newProject')}
          </Button>
        </Space>
      </div>

      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input
          placeholder={t('projects.searchPlaceholder')}
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 250 }}
          allowClear
        />
        <Select
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 180 }}
          options={[
            { value: 'active', label: t('projects.onlyActive') },
            { value: 'inactive', label: t('projects.onlyInactive') },
            { value: 'all', label: t('projects.all') },
          ]}
        />
      </Space>

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
          showTotal: (total_) => t('projects.totalCount', { count: total_ }),
        }}
      />

      <Modal
        title={editingProject ? t('projects.editProject') : t('projects.newProject')}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false)
          setEditingProject(null)
          form.resetFields()
        }}
        footer={null}
        width={800}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label={t('tenants.name')}
            rules={[{ required: true, message: t('tenants.enterName') }]}
          >
            <Input placeholder={t('projects.namePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="slug"
            label="Slug"
            rules={[
              { required: true, message: t('tenants.enterSlug') },
              { pattern: /^[a-z0-9-]+$/, message: t('tenants.slugPattern') },
            ]}
          >
            <Input disabled={!!editingProject} placeholder="es: screening-dev" />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('templates.description')}
          >
            <TextArea rows={3} placeholder={t('projects.descriptionPlaceholder')} />
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="language" label={t('projects.callLanguage')}>
                <Select
                  options={[
                    { value: 'en', label: '🇬🇧 English' },
                    { value: 'it', label: '🇮🇹 Italiano' },
                    { value: 'es', label: '🇪🇸 Español' },
                    { value: 'fr', label: '🇫🇷 Français' },
                    { value: 'de', label: '🇩🇪 Deutsch' },
                  ]}
                />
              </Form.Item>
            </Col>
            {editingProject && (
              <Col xs={24} sm={12}>
                <Form.Item name="is_active" label={t('tenantCredentials.status')} valuePropName="checked">
                  <Switch checkedChildren={t('tenants.activeStatus')} unCheckedChildren={t('tenants.inactiveStatus')} />
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
                    { value: 'openai_realtime', label: `OpenAI Realtime (${t('projects.inbound')})` },
                    { value: 'vapi', label: `Vapi + ElevenLabs (${t('projects.outbound')})` },
                    { value: 'livekit_xai', label: `LiveKit + xAI (${t('projects.inbound')})` },
                    { value: 'livekit_openai', label: `LiveKit + OpenAI (${t('projects.inbound')})` },
                    { value: 'xai_sip_direct', label: `${t('projects.directSipXai')} voice-to-voice (${t('projects.inbound')})` },
                    { value: 'openai_sip_direct', label: `${t('projects.directSipOpenai')} (${t('projects.inbound')})` },
                    { value: 'elevenlabs_agent', label: `ElevenLabs Agent (${t('projects.inbound')})` },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item noStyle shouldUpdate={(prev, curr) => prev.voice_engine !== curr.voice_engine}>
                {({ getFieldValue }) => {
                  const isNewProvider = NEW_VOICE_ENGINES.includes(getFieldValue('voice_engine'))
                  return (
                    <Form.Item name="call_direction" label={t('projects.callDirection')}>
                      <Select
                        options={
                          isNewProvider
                            ? [{ value: 'inbound', label: t('projects.inboundOnly') }]
                            : [
                                { value: 'inbound', label: t('projects.inboundOnly') },
                                { value: 'outbound', label: t('projects.outboundOnly') },
                                { value: 'both', label: t('projects.inboundOutbound') },
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
              getFieldValue('voice_engine') === 'vapi' ? (
                <>
                  <Form.Item name="vapi_assistant_id" label="Vapi Assistant ID">
                    <Input placeholder={t('projects.vapiAssistantIdPlaceholder')} />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col xs={24} sm={12}>
                      <Form.Item name="twilio_phone_number" label={t('projects.twilioNumberFrom')}>
                        <Input placeholder="+4915123456789" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12}>
                      <Form.Item name="vapi_phone_number_id" label="Vapi Phone Number ID">
                        <Input placeholder={t('projects.vapiPhoneNumberIdPlaceholder')} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item name="elevenlabs_voice_id" label="ElevenLabs Voice ID">
                    <Input placeholder={t('projects.elevenVoiceIdPlaceholder')} />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingProject ? t('common.save') : t('tenants.createButton')}
              </Button>
              <Button onClick={() => setModalOpen(false)}>{t('common.cancel')}</Button>
            </Space>
          </Form.Item>
        </Form>

        {editingProject && isAdmin && (
          <>
            <Divider orientation="left">
              <Space>
                <ApiOutlined /> API Credentials (M5.5)
              </Space>
            </Divider>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 16 }}>
              {t('projects.credentialsExceptionNote')}
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
                      title: t('tenantCredentials.status'),
                      dataIndex: 'is_active',
                      key: 'status',
                      render: (active) => (
                        <Tag color={active ? 'green' : 'default'}>
                          {active ? t('tenants.activeStatus') : t('tenants.inactiveStatus')}
                        </Tag>
                      ),
                    },
                    {
                      title: t('tenants.createdColumn'),
                      dataIndex: 'created_at',
                      key: 'created',
                      render: (date) => new Date(date).toLocaleDateString(i18n.language),
                    },
                    {
                      title: t('tenantCredentials.actions'),
                      key: 'actions',
                      render: (_, record) => (
                        <Space size="small">
                          <Tooltip title={t('tenantCredentials.testConnection')}>
                            <Button
                              icon={<CheckOutlined />}
                              size="small"
                              loading={testingCredential === record.id}
                              onClick={() => handleTestCredential(record)}
                            />
                          </Tooltip>
                          <Popconfirm
                            title={t('projects.confirmDeleteCredentials')}
                            onConfirm={() => handleDeleteCredential(record.id)}
                            okText={t('promptHistory.yes')}
                            cancelText={t('promptHistory.no')}
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
                  {t('projects.addCredentials')}
                </Button>
              </>
            )}
          </>
        )}
      </Modal>

      {/* Credential Modal */}
      <Modal
        title={t('projects.addApiCredentials')}
        open={credModalOpen}
        onCancel={() => setCredModalOpen(false)}
        footer={null}
        width={500}
        destroyOnClose
      >
        <Form form={credForm} layout="vertical" onFinish={handleCredentialSubmit} autoComplete="off">
          <Form.Item
            name="service_type"
            label="Service Type"
            rules={[{ required: true, message: t('projects.selectServiceType') }]}
          >
            <Select
              placeholder={t('projects.selectServiceType')}
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
              rules={[{ required: true, message: t('tenantCredentials.selectProvider') }]}
            >
              <Select
                placeholder={t('tenantCredentials.selectProviderPlaceholder')}
                onChange={setSelectedProvider}
                options={providersByServiceType[selectedServiceType] || []}
              />
            </Form.Item>
          )}

          <Form.Item
            name="credential_key"
            label={t('projects.referenceKeyOptional')}
            tooltip={t('tenantCredentials.referenceKeyTooltip')}
          >
            <Input placeholder="default" />
          </Form.Item>

          {renderCredentialFields()}

          {selectedProvider && (
            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit">
                  {t('common.save')}
                </Button>
                <Button onClick={() => setCredModalOpen(false)}>{t('common.cancel')}</Button>
              </Space>
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title={t('projects.runtimeServiceGenerated')}
        open={provisionModalOpen}
        onCancel={() => setProvisionModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setProvisionModalOpen(false)}>
            {t('promptHistory.close')}
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
              message={t('projects.provisionSummary', {
                slug: provisionResult.project_slug,
                engine: provisionResult.engine_type,
                port: provisionResult.port,
              })}
              description={t('projects.provisionDescription')}
            />
            <Paragraph>
              <Text strong>{t('projects.generatedFiles')}:</Text>
              <br />
              <Text code>{provisionResult.config_path}</Text>
              <br />
              <Text code>{provisionResult.env_path}</Text>
              <br />
              <Text code>{provisionResult.start_script_path}</Text>
            </Paragraph>
            <Paragraph>
              <Text strong>{t('projects.commandsToRun')}:</Text>
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflowX: 'auto' }}>
                {provisionResult.install_commands.join('\n')}
              </pre>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={() => {
                  navigator.clipboard.writeText(provisionResult.install_commands.join('\n'))
                  message.success(t('projects.copiedToClipboard'))
                }}
              >
                {t('projects.copyCommands')}
              </Button>
            </Paragraph>
          </>
        )}
      </Modal>

      <Modal
        title={t('projects.createFromTemplate')}
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
            message={t('projects.noTemplateAssigned')}
            description={t('projects.noTemplateAssignedDescription')}
          />
        ) : (
          <Form form={fromTemplateForm} layout="vertical" onFinish={handleCreateFromTemplate}>
            <Form.Item
              name="template_id"
              label="Template"
              rules={[{ required: true, message: t('projects.selectTemplate') }]}
            >
              <Select
                placeholder={t('projects.chooseTemplate')}
                onChange={handleTemplateSelect}
                options={assignedTemplates.map((tpl) => ({
                  value: tpl.id,
                  label: tpl.template_category ? `${tpl.name} (${tpl.template_category})` : tpl.name,
                }))}
              />
            </Form.Item>
            {selectedTemplate?.custom_variables_schema?.length > 0 && (
              <>
                <Divider style={{ margin: '8px 0 16px' }} orientationMargin={0} orientation="left" plain>
                  {t('projects.templateVariables')}
                </Divider>
                {selectedTemplate.custom_variables_schema.map((field) => (
                  <Form.Item
                    key={field.key}
                    name={`var__${field.key}`}
                    label={field.label || field.key}
                    tooltip={field.description}
                    rules={[{ required: true, message: t('projects.enterValueFor', { field: field.label || field.key }) }]}
                  >
                    <Input placeholder={field.default || `{{${field.key}}}`} />
                  </Form.Item>
                ))}
                <Divider style={{ margin: '8px 0 16px' }} />
              </>
            )}
            <Form.Item
              name="name"
              label={t('projects.newProjectName')}
              rules={[{ required: true, message: t('tenants.enterName') }]}
            >
              <Input placeholder="es: Comune di Sampletown - URP" />
            </Form.Item>
            <Form.Item
              name="slug"
              label="Slug"
              rules={[
                { required: true, message: t('tenants.enterSlug') },
                { pattern: /^[a-z0-9-]+$/, message: t('tenants.slugPattern') },
              ]}
            >
              <Input placeholder="es: comune-sampletown-urp" />
            </Form.Item>
            <Form.Item name="description" label={t('projects.descriptionOptional')}>
              <TextArea rows={2} />
            </Form.Item>
            <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
              {t('projects.templateCopyNote')}
            </Text>
            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={creatingFromTemplate}>
                  {t('projects.createProject')}
                </Button>
                <Button onClick={() => setFromTemplateModalOpen(false)}>{t('common.cancel')}</Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  )
}

export default Projects
