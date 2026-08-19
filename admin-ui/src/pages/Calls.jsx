import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Select, DatePicker, Typography, Tag, Card, Row, Col, Statistic, Modal, Form, message
} from 'antd'
import {
  SearchOutlined, PhoneOutlined, FileTextOutlined, FilePdfOutlined, EyeOutlined,
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, PhoneFilled
} from '@ant-design/icons'
import * as callsApi from '../api/calls'
import * as projectsApi from '../api/projects'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

function Calls() {
  const navigate = useNavigate()
  const [calls, setCalls] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [projects, setProjects] = useState([])

  // Filters
  const [phoneSearch, setPhoneSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(null)
  const [projectFilter, setProjectFilter] = useState(null)
  const [dateRange, setDateRange] = useState(null)

  // Stats
  const [stats, setStats] = useState({ today: 0, completed: 0, processing: 0 })

  // Outbound call modal
  const [outboundModalOpen, setOutboundModalOpen] = useState(false)
  const [outboundLoading, setOutboundLoading] = useState(false)
  const [outboundForm] = Form.useForm()

  useEffect(() => {
    loadProjects()
  }, [])

  useEffect(() => {
    loadCalls()
  }, [page, pageSize, phoneSearch, statusFilter, projectFilter, dateRange])

  const loadProjects = async () => {
    try {
      const data = await projectsApi.getProjects({ page_size: 100 })
      setProjects(data.projects || data)
    } catch (error) {
      console.error('Error loading projects:', error)
    }
  }

  const loadCalls = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (phoneSearch) params.phone_search = phoneSearch
      if (statusFilter) params.status = statusFilter
      if (projectFilter) params.project_id = projectFilter
      if (dateRange && dateRange[0]) params.date_from = dateRange[0].toISOString()
      if (dateRange && dateRange[1]) params.date_to = dateRange[1].toISOString()

      const data = await callsApi.getCalls(params)
      setCalls(data.calls)
      setTotal(data.total)

      // Calculate simple stats
      const today = data.calls.filter(c =>
        new Date(c.created_at).toDateString() === new Date().toDateString()
      ).length
      const completed = data.calls.filter(c =>
        c.status === 'completed' || c.status === 'processed'
      ).length
      const processing = data.calls.filter(c =>
        c.status === 'processing' || c.status === 'in_progress'
      ).length

      setStats({ today, completed, processing })
    } catch (error) {
      console.error('Error loading calls:', error)
    } finally {
      setLoading(false)
    }
  }

  // M5: Outbound call
  const outboundProjects = projects.filter(p =>
    (p.call_direction === 'outbound' || p.call_direction === 'both') && p.voice_engine === 'vapi'
  )

  const handleOutboundCall = async (values) => {
    setOutboundLoading(true)
    try {
      const result = await callsApi.createOutboundCall({
        phone_number: values.phone_number,
        project_id: values.project_id,
      })
      message.success(`Chiamata avviata: ${result.call_id}`)
      setOutboundModalOpen(false)
      outboundForm.resetFields()
      loadCalls()
    } catch (error) {
      const msg = error.response?.data?.detail || 'Errore avvio chiamata'
      message.error(msg)
    } finally {
      setOutboundLoading(false)
    }
  }

  const handleDownloadPDF = async (callId) => {
    try {
      const blob = await callsApi.downloadCallPdf(callId)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `call_${callId}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      message.error('Errore download PDF')
    }
  }

  const handleDownloadJSON = async (callId) => {
    try {
      const data = await callsApi.getCallJson(callId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `call_${callId}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      message.error('Errore download JSON')
    }
  }

  const getStatusConfig = (status) => {
    const configs = {
      pending_consent: { color: 'default', icon: <ClockCircleOutlined />, label: 'In attesa consenso' },
      consented: { color: 'blue', icon: <CheckCircleOutlined />, label: 'Consenso dato' },
      in_progress: { color: 'processing', icon: <PhoneOutlined />, label: 'In corso' },
      completed: { color: 'green', icon: <CheckCircleOutlined />, label: 'Completata' },
      processing: { color: 'orange', icon: <ClockCircleOutlined />, label: 'In elaborazione' },
      processed: { color: 'success', icon: <CheckCircleOutlined />, label: 'Elaborata' },
      declined: { color: 'red', icon: <CloseCircleOutlined />, label: 'Rifiutata' },
      cancelled: { color: 'default', icon: <CloseCircleOutlined />, label: 'Annullata' },
    }
    return configs[status] || { color: 'default', label: status }
  }

  const formatDuration = (seconds) => {
    if (!seconds) return '-'
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const columns = [
    {
      title: 'Telefono',
      dataIndex: 'phone_number',
      key: 'phone',
      render: (phone) => (
        <Space>
          <PhoneOutlined />
          <Text copyable={{ text: phone }}>{phone}</Text>
        </Space>
      ),
    },
    {
      title: 'Dir.',
      key: 'direction',
      align: 'center',
      width: 60,
      render: (_, record) => {
        const dir = record.direction || 'inbound'
        return (
          <Tag color={dir === 'outbound' ? 'orange' : 'default'} style={{ fontSize: 10 }}>
            {dir === 'outbound' ? 'OUT' : 'IN'}
          </Tag>
        )
      },
    },
    {
      title: 'Candidato',
      dataIndex: 'candidate_name',
      key: 'candidate',
      render: (name) => name || <Text type="secondary">-</Text>,
    },
    {
      title: 'Progetto',
      key: 'project',
      render: (_, record) => (
        record.project_name ? (
          <Tag>{record.project_name}</Tag>
        ) : (
          <Text type="secondary">-</Text>
        )
      ),
    },
    {
      title: 'Stato',
      dataIndex: 'status',
      key: 'status',
      render: (status) => {
        const config = getStatusConfig(status)
        return (
          <Tag color={config.color} icon={config.icon}>
            {config.label}
          </Tag>
        )
      },
    },
    {
      title: 'Durata',
      dataIndex: 'duration_seconds',
      key: 'duration',
      align: 'center',
      render: formatDuration,
    },
    {
      title: 'Record',
      key: 'record',
      align: 'center',
      render: (_, record) => (
        <Space>
          {record.has_record && (
            <Button
              type="link"
              size="small"
              icon={<FileTextOutlined />}
              onClick={() => handleDownloadJSON(record.id)}
            >
              JSON
            </Button>
          )}
          {record.has_pdf && (
            <Button
              type="link"
              size="small"
              icon={<FilePdfOutlined />}
              onClick={() => handleDownloadPDF(record.id)}
            >
              PDF
            </Button>
          )}
          {!record.has_record && !record.has_pdf && (
            <Text type="secondary">-</Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Data',
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => (
        <Space direction="vertical" size={0}>
          <Text>{new Date(date).toLocaleDateString('it-IT')}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {new Date(date).toLocaleTimeString('it-IT')}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            icon={<EyeOutlined />}
            size="small"
            type="primary"
            onClick={() => navigate(`/calls/${record.id}`)}
          >
            Dettagli
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>Chiamate</Title>
        <Button
          type="primary"
          icon={<PhoneFilled />}
          onClick={() => setOutboundModalOpen(true)}
          disabled={outboundProjects.length === 0}
          title={outboundProjects.length === 0 ? 'Nessun progetto configurato per outbound (Vapi)' : ''}
        >
          Nuova Chiamata Outbound
        </Button>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="Chiamate Oggi"
              value={stats.today}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Completate (in lista)"
              value={stats.completed}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="In Elaborazione"
              value={stats.processing}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Input
              placeholder="Cerca telefono..."
              prefix={<SearchOutlined />}
              value={phoneSearch}
              onChange={(e) => setPhoneSearch(e.target.value)}
              allowClear
            />
          </Col>
          <Col span={5}>
            <Select
              placeholder="Stato"
              style={{ width: '100%' }}
              allowClear
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: 'pending_consent', label: 'In attesa consenso' },
                { value: 'consented', label: 'Consenso dato' },
                { value: 'in_progress', label: 'In corso' },
                { value: 'completed', label: 'Completata' },
                { value: 'processing', label: 'In elaborazione' },
                { value: 'processed', label: 'Elaborata' },
                { value: 'declined', label: 'Rifiutata' },
                { value: 'cancelled', label: 'Annullata' },
              ]}
            />
          </Col>
          <Col span={5}>
            <Select
              placeholder="Progetto"
              style={{ width: '100%' }}
              allowClear
              value={projectFilter}
              onChange={setProjectFilter}
              options={projects.map(p => ({ value: p.id, label: p.name }))}
            />
          </Col>
          <Col span={8}>
            <RangePicker
              style={{ width: '100%' }}
              value={dateRange}
              onChange={setDateRange}
              format="DD/MM/YYYY"
              placeholder={['Data inizio', 'Data fine']}
            />
          </Col>
        </Row>
      </Card>

      <Table
        scroll={{ x: 'max-content' }}
        dataSource={calls}
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
          showTotal: (t) => `Totale: ${t} chiamate`,
        }}
      />

      {/* M5: Outbound Call Modal */}
      <Modal
        title="Nuova Chiamata Outbound"
        open={outboundModalOpen}
        onCancel={() => { setOutboundModalOpen(false); outboundForm.resetFields() }}
        footer={null}
        width={500}
      >
        <Form form={outboundForm} layout="vertical" onFinish={handleOutboundCall}>
          <Form.Item
            name="phone_number"
            label="Numero di Telefono"
            rules={[
              { required: true, message: 'Inserisci numero di telefono' },
              { pattern: /^\+?[0-9\s\-()]+$/, message: 'Formato numero non valido' },
            ]}
          >
            <Input placeholder="+49 151 23456789" prefix={<PhoneOutlined />} />
          </Form.Item>
          <Form.Item
            name="project_id"
            label="Progetto"
            rules={[{ required: true, message: 'Seleziona un progetto' }]}
          >
            <Select
              placeholder="Seleziona progetto outbound..."
              options={outboundProjects.map(p => ({
                value: p.id,
                label: `${p.name} (${p.language || 'it'})`,
              }))}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={outboundLoading} icon={<PhoneFilled />}>
                Avvia Chiamata
              </Button>
              <Button onClick={() => { setOutboundModalOpen(false); outboundForm.resetFields() }}>
                Annulla
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Calls
