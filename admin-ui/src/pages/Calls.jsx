import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Select, DatePicker, Typography, Tag, Card, Row, Col, Statistic
} from 'antd'
import {
  SearchOutlined, PhoneOutlined, FileTextOutlined, FilePdfOutlined, EyeOutlined,
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined
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
            <Tag color="blue" icon={<FileTextOutlined />}>JSON</Tag>
          )}
          {record.has_pdf && (
            <Tag color="green" icon={<FilePdfOutlined />}>PDF</Tag>
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
      <Title level={3} style={{ marginBottom: 24 }}>Chiamate</Title>

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
    </div>
  )
}

export default Calls
