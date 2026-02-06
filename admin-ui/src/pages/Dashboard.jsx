import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Typography, Spin, Table, Tag } from 'antd'
import {
  PhoneOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  RiseOutlined,
  ApiOutlined,
  CalendarOutlined,
} from '@ant-design/icons'
import * as analyticsApi from '../api/analytics'

const { Title } = Typography

function Dashboard() {
  const [stats, setStats] = useState(null)
  const [projectStats, setProjectStats] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [dashboardData, projectData] = await Promise.all([
        analyticsApi.getDashboardStats(),
        analyticsApi.getProjectStats(),
      ])
      setStats(dashboardData)
      setProjectStats(projectData)
    } catch (error) {
      console.error('Error loading dashboard:', error)
    } finally {
      setLoading(false)
    }
  }

  const formatDuration = (seconds) => {
    if (!seconds) return '0m'
    const minutes = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return `${minutes}m ${secs}s`
  }

  const projectColumns = [
    {
      title: 'Progetto',
      dataIndex: 'project_name',
      key: 'project_name',
    },
    {
      title: 'Chiamate',
      dataIndex: 'total_calls',
      key: 'total_calls',
      align: 'right',
    },
    {
      title: 'Completate',
      dataIndex: 'completed_calls',
      key: 'completed_calls',
      align: 'right',
    },
    {
      title: 'Conversione',
      dataIndex: 'conversion_rate',
      key: 'conversion_rate',
      align: 'right',
      render: (value) => (
        <Tag color={value >= 50 ? 'green' : value >= 25 ? 'orange' : 'red'}>
          {value.toFixed(1)}%
        </Tag>
      ),
    },
    {
      title: 'Durata Media',
      dataIndex: 'avg_duration_seconds',
      key: 'avg_duration',
      align: 'right',
      render: (value) => formatDuration(value),
    },
  ]

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 50 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>Dashboard</Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Chiamate Oggi"
              value={stats?.total_calls_today || 0}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Completate Oggi"
              value={stats?.completed_calls_today || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Tasso Conversione"
              value={stats?.conversion_rate || 0}
              suffix="%"
              prefix={<RiseOutlined />}
              precision={1}
              valueStyle={{ color: stats?.conversion_rate >= 50 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Durata Media"
              value={formatDuration(stats?.avg_duration_seconds)}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Chiamate Settimana"
              value={stats?.total_calls_week || 0}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Chiamate Mese"
              value={stats?.total_calls_month || 0}
              prefix={<PhoneOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Sync CRM"
              value={stats?.crm_synced_count || 0}
              prefix={<ApiOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Appuntamenti"
              value={stats?.appointments_scheduled_count || 0}
              prefix={<CalendarOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginTop: 24 }}>
        <Title level={4}>Statistiche per Progetto</Title>
        <Table
          dataSource={projectStats}
          columns={projectColumns}
          rowKey="project_id"
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  )
}

export default Dashboard
