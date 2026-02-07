import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Modal, Form, Select, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card, Row, Col, Divider
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, HistoryOutlined, EyeOutlined, ApiOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'

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

  const openModal = (project = null) => {
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
    } else {
      form.setFieldsValue({
        is_active: true,
        voice_engine: 'openai_realtime',
        call_direction: 'inbound',
      })
    }
    setModalOpen(true)
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
        width={600}
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
      </Modal>
    </div>
  )
}

export default Projects
