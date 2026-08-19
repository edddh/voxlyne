import { useState, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Card, Button, Space, message, Typography, Tabs, Table, Tag, Modal, Spin, Popconfirm, Row, Col
} from 'antd'
import { ArrowLeftOutlined, RollbackOutlined, CheckCircleOutlined, DiffOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as promptsApi from '../api/prompts'

const { Title, Text, Paragraph } = Typography

function PromptHistory() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [versionsA, setVersionsA] = useState([])
  const [versionsB, setVersionsB] = useState([])
  const [selectedVersion, setSelectedVersion] = useState(null)
  const [diffModalOpen, setDiffModalOpen] = useState(false)
  const [diffData, setDiffData] = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [compareVersions, setCompareVersions] = useState({ v1: null, v2: null })

  const initialTab = searchParams.get('type') || 'A'

  useEffect(() => {
    loadData()
  }, [id])

  const loadData = async () => {
    setLoading(true)
    try {
      const [projectData, versA, versB] = await Promise.all([
        projectsApi.getProject(id),
        promptsApi.getPromptVersions(id, 'A').catch(() => []),
        promptsApi.getPromptVersions(id, 'B').catch(() => []),
      ])
      setProject(projectData)
      setVersionsA(versA)
      setVersionsB(versB)
    } catch (error) {
      message.error('Errore caricamento dati')
      navigate('/projects')
    } finally {
      setLoading(false)
    }
  }

  const handleActivate = async (versionId) => {
    try {
      await promptsApi.activatePromptVersion(versionId)
      message.success('Versione attivata')
      loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore attivazione')
    }
  }

  const handleRollback = async (versionId) => {
    try {
      await promptsApi.rollbackPromptVersion(versionId)
      message.success('Rollback completato')
      loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore rollback')
    }
  }

  const openDiff = async (v1Id, v2Id) => {
    setDiffLoading(true)
    setDiffModalOpen(true)
    try {
      const diff = await promptsApi.getPromptDiff(v1Id, v2Id)
      setDiffData(diff)
    } catch (error) {
      message.error('Errore generazione diff')
      setDiffModalOpen(false)
    } finally {
      setDiffLoading(false)
    }
  }

  const renderDiff = (diffText) => {
    if (!diffText) return null
    const lines = diffText.split('\n')
    return (
      <pre style={{
        fontFamily: 'monospace',
        fontSize: 12,
        backgroundColor: '#1e1e1e',
        color: '#d4d4d4',
        padding: 16,
        borderRadius: 8,
        overflow: 'auto',
        maxHeight: 500,
      }}>
        {lines.map((line, idx) => {
          let color = '#d4d4d4'
          let bgColor = 'transparent'
          if (line.startsWith('+') && !line.startsWith('+++')) {
            color = '#4caf50'
            bgColor = 'rgba(76, 175, 80, 0.1)'
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            color = '#f44336'
            bgColor = 'rgba(244, 67, 54, 0.1)'
          } else if (line.startsWith('@@')) {
            color = '#2196f3'
          }
          return (
            <div key={idx} style={{ color, backgroundColor: bgColor }}>
              {line}
            </div>
          )
        })}
      </pre>
    )
  }

  const columns = [
    {
      title: 'Versione',
      dataIndex: 'version',
      key: 'version',
      width: 100,
      render: (version, record) => (
        <Space>
          <Text strong>v{version}</Text>
          {record.is_active && <Tag color="green">Attiva</Tag>}
        </Space>
      ),
    },
    {
      title: 'Anteprima',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (content) => (
        <Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 11 }}>
          {content?.substring(0, 100)}...
        </Text>
      ),
    },
    {
      title: 'Creato',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date) => new Date(date).toLocaleString('it-IT'),
    },
    {
      title: 'Autore',
      dataIndex: 'created_by_name',
      key: 'created_by',
      width: 150,
    },
    {
      title: 'Azioni',
      key: 'actions',
      width: 250,
      render: (_, record, index, data) => (
        <Space>
          <Button
            size="small"
            onClick={() => setSelectedVersion(record)}
          >
            Visualizza
          </Button>
          {!record.is_active && (
            <Popconfirm
              title="Attivare questa versione?"
              onConfirm={() => handleActivate(record.id)}
              okText="Sì"
              cancelText="No"
            >
              <Button size="small" icon={<CheckCircleOutlined />}>
                Attiva
              </Button>
            </Popconfirm>
          )}
          {index > 0 && (
            <Button
              size="small"
              icon={<DiffOutlined />}
              onClick={() => openDiff(data[index].id, data[index - 1].id)}
            >
              Diff
            </Button>
          )}
        </Space>
      ),
    },
  ]

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }

  const tabItems = [
    {
      key: 'A',
      label: `Prompt A (${versionsA.length} versioni)`,
      children: (
        <Table
          scroll={{ x: 'max-content' }}
          dataSource={versionsA.sort((a, b) => b.version - a.version)}
          columns={columns.map(c => ({
            ...c,
            render: c.key === 'actions'
              ? (_, record, index) => c.render(_, record, index, versionsA.sort((a, b) => b.version - a.version))
              : c.render
          }))}
          rowKey="id"
          pagination={false}
        />
      ),
    },
    {
      key: 'B',
      label: `Prompt B (${versionsB.length} versioni)`,
      children: (
        <Table
          scroll={{ x: 'max-content' }}
          dataSource={versionsB.sort((a, b) => b.version - a.version)}
          columns={columns.map(c => ({
            ...c,
            render: c.key === 'actions'
              ? (_, record, index) => c.render(_, record, index, versionsB.sort((a, b) => b.version - a.version))
              : c.render
          }))}
          rowKey="id"
          pagination={false}
        />
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${id}/edit`)}>
            Torna all'Editor
          </Button>
          <Title level={3} style={{ margin: 0 }}>Storico Prompt: {project?.name}</Title>
        </Space>
      </div>

      <Card>
        <Tabs items={tabItems} defaultActiveKey={initialTab} />
      </Card>

      <Modal
        title={`Versione ${selectedVersion?.version}`}
        open={!!selectedVersion}
        onCancel={() => setSelectedVersion(null)}
        footer={[
          <Button key="close" onClick={() => setSelectedVersion(null)}>
            Chiudi
          </Button>,
          !selectedVersion?.is_active && (
            <Popconfirm
              key="activate"
              title="Attivare questa versione?"
              onConfirm={() => {
                handleActivate(selectedVersion.id)
                setSelectedVersion(null)
              }}
              okText="Sì"
              cancelText="No"
            >
              <Button type="primary" icon={<CheckCircleOutlined />}>
                Attiva
              </Button>
            </Popconfirm>
          ),
        ]}
        width={800}
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            Creato: {selectedVersion && new Date(selectedVersion.created_at).toLocaleString('it-IT')}
          </Text>
        </div>
        <pre style={{
          fontFamily: 'monospace',
          fontSize: 12,
          backgroundColor: '#f5f5f5',
          padding: 16,
          borderRadius: 8,
          overflow: 'auto',
          maxHeight: 400,
          whiteSpace: 'pre-wrap',
        }}>
          {selectedVersion?.content}
        </pre>
      </Modal>

      <Modal
        title="Confronto Versioni"
        open={diffModalOpen}
        onCancel={() => {
          setDiffModalOpen(false)
          setDiffData(null)
        }}
        footer={null}
        width={900}
      >
        {diffLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : diffData && (
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Tag color="red">v{diffData.version_a?.version} (precedente)</Tag>
              </Col>
              <Col span={12}>
                <Tag color="green">v{diffData.version_b?.version} (nuova)</Tag>
              </Col>
            </Row>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              {diffData.additions > 0 && `+${diffData.additions} aggiunte `}
              {diffData.deletions > 0 && `-${diffData.deletions} rimozioni`}
            </Text>
            {renderDiff(diffData.diff)}
          </div>
        )}
      </Modal>
    </div>
  )
}

export default PromptHistory
