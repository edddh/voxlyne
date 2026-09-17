import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, Select, DatePicker, Typography, Tag, Card, Row, Col, Statistic, Modal, Form, message, Progress, Tabs
} from 'antd'
import {
  SearchOutlined, PhoneOutlined, FileTextOutlined, FilePdfOutlined, EyeOutlined,
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, PhoneFilled, UserOutlined,
  PieChartOutlined, DollarCircleOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as callsApi from '../api/calls'
import * as projectsApi from '../api/projects'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

function Calls() {
  const { t, i18n } = useTranslation()
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
  const [callOrigin, setCallOrigin] = useState('production')

  // Stats - conteggi reali sul tenant intero (GET /api/v2/calls/stats),
  // non piu' calcolati sulla sola pagina caricata (maintainer, 20/08: "che
  // cagata e', io voglio sapere piuttosto quante effettuate oggi, quante
  // in totale" - prima "Completate" contava solo tra le righe visibili
  // in quel momento, cambiava a seconda della pagina).
  // maintainer, 20/08: "i costi reali delle chiamate devono essere visibili
  // solo dal superadmin... gli utenti del tenant devono vedere quanto
  // del pacchetto hanno utilizzato" - il backend gia' manda payload
  // diversi per ruolo (total_cost_usd/by_tenant solo per super_admin,
  // minutes_used/minutes_included/percent_used per tutti gli altri), qui
  // e' solo un unico state che li ospita entrambi.
  const [stats, setStats] = useState({
    total: 0, today: 0, completed: 0, in_progress: 0,
    total_cost_usd: 0, today_cost_usd: 0, by_tenant: [],
    minutes_used: 0, minutes_used_current_month: 0, minutes_used_current_year: 0,
    minutes_included: null, percent_used: null,
    can_view_costs: false,
  })

  // Outbound call modal
  const [outboundModalOpen, setOutboundModalOpen] = useState(false)
  const [outboundLoading, setOutboundLoading] = useState(false)
  const [outboundForm] = Form.useForm()

  useEffect(() => {
    loadProjects()
  }, [])

  useEffect(() => {
    loadCalls()
    loadStats()
  }, [page, pageSize, phoneSearch, statusFilter, projectFilter, dateRange, callOrigin])

  const loadProjects = async () => {
    try {
      const data = await projectsApi.getProjects({ page_size: 100 })
      setProjects(data.projects || data)
    } catch (error) {
      console.error('Error loading projects:', error)
    }
  }

  // Indipendente dai filtri/paginazione della tabella sotto - e' sempre
  // il quadro reale di tutte le chiamate del tenant, non di quelle
  // filtrate/visibili in questo momento.
  const loadStats = async () => {
    try {
      const params = {}
      if (phoneSearch) params.phone_search = phoneSearch
      if (statusFilter) params.status = statusFilter
      if (projectFilter) params.project_id = projectFilter
      if (dateRange && dateRange[0]) params.date_from = dateRange[0].toISOString()
      if (dateRange && dateRange[1]) params.date_to = dateRange[1].toISOString()
      params.origin = callOrigin

      const data = await callsApi.getCallsStats(params)
      setStats(data)
    } catch (error) {
      console.error('Error loading call stats:', error)
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
      params.origin = callOrigin

      const data = await callsApi.getCalls(params)
      setCalls(data.calls)
      setTotal(data.total)
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
      message.success(t('calls.callStarted', { callId: result.call_id }))
      setOutboundModalOpen(false)
      outboundForm.resetFields()
      loadCalls()
      loadStats()
    } catch (error) {
      const msg = error.response?.data?.detail || t('calls.startCallError')
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
      message.error(t('callDetail.pdfDownloadError'))
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
      message.error(t('calls.jsonDownloadError'))
    }
  }

  const getStatusConfig = (status) => {
    const configs = {
      pending_consent: { color: 'default', icon: <ClockCircleOutlined />, label: t('analytics.statusPendingConsent') },
      consented: { color: 'blue', icon: <CheckCircleOutlined />, label: t('analytics.statusConsented') },
      in_progress: { color: 'processing', icon: <PhoneOutlined />, label: t('analytics.statusInProgress') },
      completed: { color: 'green', icon: <CheckCircleOutlined />, label: t('analytics.statusCompleted') },
      processing: { color: 'orange', icon: <ClockCircleOutlined />, label: t('analytics.statusProcessing') },
      processed: { color: 'success', icon: <CheckCircleOutlined />, label: t('analytics.statusProcessed') },
      declined: { color: 'red', icon: <CloseCircleOutlined />, label: t('analytics.statusDeclined') },
      escalated: { color: 'purple', icon: <UserOutlined />, label: t('analytics.statusEscalated') },
      cancelled: { color: 'default', icon: <CloseCircleOutlined />, label: t('analytics.statusCancelled') },
    }
    return configs[status] || { color: 'default', label: status }
  }

  const formatDuration = (seconds) => {
    if (!seconds) return '-'
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const formatBillableMinutes = (minutes) => {
    if (minutes == null) return '-'
    const wholeMinutes = Math.floor(minutes)
    const seconds = Math.round((minutes - wholeMinutes) * 60)
    if (seconds === 60) return `${wholeMinutes + 1}m`
    if (seconds === 0) return `${wholeMinutes}m`
    return `${wholeMinutes}m${seconds.toString().padStart(2, '0')}s`
  }

  const formatIncludedMinutes = (minutes) => {
    if (minutes == null) return null
    return formatBillableMinutes(minutes)
  }

  const columns = [
    {
      title: t('calls.dir'),
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
      title: t('callDetail.caller'),
      dataIndex: 'phone_number',
      key: 'caller',
      render: (phone) => (
        <Space>
          <PhoneOutlined />
          <Text copyable={{ text: phone }}>{phone}</Text>
        </Space>
      ),
    },
    {
      title: 'Tipo',
      key: 'origin',
      align: 'center',
      render: (_, record) => record.origin === 'voice_simulation'
        ? <Tag color="blue">SIMULAZIONE</Tag>
        : <Tag>PRODUZIONE</Tag>,
    },
    {
      title: t('dashboard.project'),
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
      title: t('tenantCredentials.status'),
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
      title: t('callDetail.duration'),
      dataIndex: 'duration_seconds',
      key: 'duration',
      align: 'center',
      render: formatDuration,
    },
    // Il backend non manda affatto cost_usd a chi non e' super_admin
    // (maintainer, 20/08: "i costi reali... devono essere visibili solo dal
    // superadmin") - una colonna sempre vuota per tutti gli altri
    // sarebbe solo rumore, meglio non mostrarla proprio.
    ...(stats.can_view_costs ? [{
      title: t('calls.cost'),
      dataIndex: 'cost_usd',
      key: 'cost',
      align: 'center',
      render: (cost) => cost != null ? `$${cost.toFixed(4)}` : <Text type="secondary">-</Text>,
    }] : []),
    {
      title: t('calls.record'),
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
      title: t('calls.date'),
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => (
        <Space direction="vertical" size={0}>
          <Text>{new Date(date).toLocaleDateString(i18n.language)}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {new Date(date).toLocaleTimeString(i18n.language)}
          </Text>
        </Space>
      ),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            icon={<EyeOutlined />}
            size="small"
            type="primary"
            onClick={() => navigate(`/calls/${record.id}`)}
          >
            {t('calls.details')}
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 8 }}>
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{t('nav.calls')}</Title>
        <Button
          type="primary"
          icon={<PhoneFilled />}
          onClick={() => setOutboundModalOpen(true)}
          disabled={outboundProjects.length === 0}
          title={outboundProjects.length === 0 ? t('calls.noOutboundProjects') : ''}
        >
          {t('calls.newOutboundCall')}
        </Button>
      </div>

      <Tabs
        activeKey={callOrigin}
        onChange={(value) => { setCallOrigin(value); setPage(1) }}
        items={[
          { key: 'production', label: 'Produzione' },
          { key: 'voice_simulation', label: <span>Simulazioni <Tag color="blue">TEST</Tag></span> },
          { key: 'all', label: 'Tutte' },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('dashboard.callsToday')}
              value={stats.today}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('calls.totalCalls')}
              value={stats.total}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('dashboard.completed')}
              value={stats.completed}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('calls.inProgress')}
              value={stats.in_progress}
              prefix={<PhoneOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('calls.packageMinutesUsed')}
              value={formatBillableMinutes(stats.minutes_used_current_month ?? stats.minutes_used)}
              suffix={stats.minutes_included ? `/ ${formatIncludedMinutes(stats.minutes_included)}` : ''}
              prefix={<PieChartOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
            {stats.percent_used != null ? (
              <Progress percent={stats.percent_used} size="small" style={{ marginTop: 8 }} />
            ) : (
              <Text type="secondary" style={{ fontSize: 11 }}>{t('calls.noPackageConfigured')}</Text>
            )}
          </Card>
        </Col>
        {stats.can_view_costs && (
          <Col xs={12} sm={6}>
            <Card>
              <Statistic
                title={t('calls.externalServicesCost')}
                value={stats.total_cost_usd}
                precision={2}
                prefix={<DollarCircleOutlined />}
                valueStyle={{ color: '#1890ff' }}
              />
            </Card>
          </Col>
        )}
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title={t('calls.currentYearMinutes')}
              value={formatBillableMinutes(stats.minutes_used_current_year)}
              prefix={<PieChartOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      {stats.by_tenant?.length > 0 && (
        <Card title={t('calls.costsByTenant')} size="small" style={{ marginBottom: 24 }}>
          <Table
            size="small"
            pagination={false}
            dataSource={stats.by_tenant}
            rowKey="tenant_id"
            columns={[
              { title: 'Tenant', dataIndex: 'tenant_name', key: 'tenant_name' },
              { title: t('dashboard.calls'), dataIndex: 'calls_count', key: 'calls_count', align: 'center' },
              { title: t('calls.billableMinutes'), dataIndex: 'minutes_used', key: 'minutes_used', align: 'center' },
              {
                title: t('calls.recordedCost'),
                dataIndex: 'cost_usd',
                key: 'cost_usd',
                align: 'center',
                render: (v) => `$${v.toFixed(2)}`,
              },
            ]}
          />
        </Card>
      )}

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Input
              placeholder={t('calls.searchPhone')}
              prefix={<SearchOutlined />}
              value={phoneSearch}
              onChange={(e) => setPhoneSearch(e.target.value)}
              allowClear
            />
          </Col>
          <Col xs={12} sm={12} md={5}>
            <Select
              placeholder={t('tenantCredentials.status')}
              style={{ width: '100%' }}
              allowClear
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: 'pending_consent', label: t('analytics.statusPendingConsent') },
                { value: 'consented', label: t('analytics.statusConsented') },
                { value: 'in_progress', label: t('analytics.statusInProgress') },
                { value: 'completed', label: t('analytics.statusCompleted') },
                { value: 'processing', label: t('analytics.statusProcessing') },
                { value: 'processed', label: t('analytics.statusProcessed') },
                { value: 'declined', label: t('analytics.statusDeclined') },
                { value: 'escalated', label: t('analytics.statusEscalated') },
                { value: 'cancelled', label: t('analytics.statusCancelled') },
              ]}
            />
          </Col>
          <Col xs={12} sm={12} md={5}>
            <Select
              placeholder={t('dashboard.project')}
              style={{ width: '100%' }}
              allowClear
              value={projectFilter}
              onChange={setProjectFilter}
              options={projects.map(p => ({ value: p.id, label: p.name }))}
            />
          </Col>
          <Col xs={24} sm={24} md={8}>
            <RangePicker
              style={{ width: '100%' }}
              value={dateRange}
              onChange={setDateRange}
              format="DD/MM/YYYY"
              placeholder={[t('calls.startDate'), t('calls.endDate')]}
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
          showTotal: (total_) => t('calls.totalCount', { count: total_ }),
        }}
      />

      {/* M5: Outbound Call Modal */}
      <Modal
        title={t('calls.newOutboundCall')}
        open={outboundModalOpen}
        onCancel={() => { setOutboundModalOpen(false); outboundForm.resetFields() }}
        footer={null}
        width={500}
      >
        <Form form={outboundForm} layout="vertical" onFinish={handleOutboundCall}>
          <Form.Item
            name="phone_number"
            label={t('calls.phoneNumber')}
            rules={[
              { required: true, message: t('calls.enterPhoneNumber') },
              { pattern: /^\+?[0-9\s\-()]+$/, message: t('calls.invalidNumberFormat') },
            ]}
          >
            <Input placeholder="+49 151 23456789" prefix={<PhoneOutlined />} />
          </Form.Item>
          <Form.Item
            name="project_id"
            label={t('dashboard.project')}
            rules={[{ required: true, message: t('calls.selectProject') }]}
          >
            <Select
              placeholder={t('calls.selectOutboundProject')}
              options={outboundProjects.map(p => ({
                value: p.id,
                label: `${p.name} (${p.language || 'it'})`,
              }))}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={outboundLoading} icon={<PhoneFilled />}>
                {t('calls.startCall')}
              </Button>
              <Button onClick={() => { setOutboundModalOpen(false); outboundForm.resetFields() }}>
                {t('common.cancel')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Calls
