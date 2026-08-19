import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Space, message, Typography, Table, Tag, Modal, Spin, Popconfirm, Tabs } from 'antd'
import { ArrowLeftOutlined, RollbackOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as agentVersionsApi from '../api/agentVersions'

const { Title, Text } = Typography

/**
 * Storico delle versioni pubblicate di un progetto (agent_versions - il
 * motore reale che resolve_inbound() legge per rispondere alle chiamate,
 * vedi app/services/agent_versions.py). Riscritta il 19/08 per usare
 * questo invece del vecchio sistema prompt_versions/prompts.js (maintainer:
 * "devi sistemare tutto anche la cronologia") - quel sistema versionava
 * prompt_a e prompt_b separatamente e in modo scollegato da cosa risponde
 * davvero l'agente; qui una versione e' l'intero agente (prompt_a +
 * prompt_b + voce/lingua/motore) congelato in un unico scatto, coerente
 * con come "Pubblica" funziona nell'Editor.
 *
 * Diff testuale tra versioni non ricostruita in questa riscrittura (il
 * vecchio sistema la calcolava lato server su un modello dati diverso,
 * non disponibile qui) - "Visualizza" mostra il contenuto completo di
 * una versione, sufficiente per un confronto visivo manuale.
 */
function PromptHistory() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [versions, setVersions] = useState([])
  const [selectedVersion, setSelectedVersion] = useState(null)
  const [rollingBack, setRollingBack] = useState(null)

  useEffect(() => {
    loadData()
  }, [id])

  const loadData = async () => {
    setLoading(true)
    try {
      const [projectData, versionsList] = await Promise.all([
        projectsApi.getProject(id),
        agentVersionsApi.listAgentVersions(id).catch(() => []),
      ])
      setProject(projectData)
      setVersions(versionsList)
    } catch (error) {
      message.error('Errore caricamento dati')
      navigate('/projects')
    } finally {
      setLoading(false)
    }
  }

  const handleRollback = async (versionId) => {
    setRollingBack(versionId)
    try {
      await agentVersionsApi.rollbackToVersion(id, versionId)
      message.success('Ripristino completato - attivo per le prossime chiamate')
      loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore ripristino')
    } finally {
      setRollingBack(null)
    }
  }

  const columns = [
    {
      title: 'Versione',
      dataIndex: 'version_number',
      key: 'version_number',
      width: 100,
      render: (v, record) => (
        <Space>
          <Text strong>v{v}</Text>
          {record.status === 'published' && <Tag color="green">Pubblicata</Tag>}
          {record.status === 'archived' && <Tag>Archiviata</Tag>}
        </Space>
      ),
    },
    {
      title: 'Anteprima prompt (intervista)',
      dataIndex: 'prompt_a',
      key: 'prompt_a',
      ellipsis: true,
      render: (content) => (
        <Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 11 }}>
          {content ? `${content.substring(0, 100)}...` : '—'}
        </Text>
      ),
    },
    {
      title: 'Voce / lingua',
      key: 'voice',
      width: 140,
      render: (_, record) => <Text type="secondary">{record.voice_name} · {record.language}</Text>,
    },
    {
      title: 'Pubblicata il',
      dataIndex: 'published_at',
      key: 'published_at',
      width: 180,
      render: (date) => (date ? new Date(date).toLocaleString('it-IT') : '—'),
    },
    {
      title: 'Azioni',
      key: 'actions',
      width: 220,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => setSelectedVersion(record)}>
            Visualizza
          </Button>
          {record.status !== 'published' && (
            <Popconfirm
              title="Ripristinare questa versione? Diventa subito attiva per le chiamate."
              onConfirm={() => handleRollback(record.id)}
              okText="Sì"
              cancelText="No"
            >
              <Button size="small" icon={<RollbackOutlined />} loading={rollingBack === record.id}>
                Ripristina
              </Button>
            </Popconfirm>
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/projects/${id}/edit`)}>
            Torna all'Editor
          </Button>
          <Title level={3} style={{ margin: 0, flexShrink: 0 }}>Storico versioni: {project?.name}</Title>
        </Space>
      </div>

      <Card>
        {versions.length === 0 ? (
          <Text type="secondary">
            Nessuna versione ancora pubblicata per questo progetto - torna all'Editor e usa "Pubblica"
            per creare la prima.
          </Text>
        ) : (
          <Table
            scroll={{ x: 'max-content' }}
            dataSource={versions}
            columns={columns}
            rowKey="id"
            pagination={false}
          />
        )}
      </Card>

      <Modal
        title={`Versione ${selectedVersion?.version_number}`}
        open={!!selectedVersion}
        onCancel={() => setSelectedVersion(null)}
        footer={[
          <Button key="close" onClick={() => setSelectedVersion(null)}>
            Chiudi
          </Button>,
        ]}
        width={800}
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            Pubblicata: {selectedVersion?.published_at ? new Date(selectedVersion.published_at).toLocaleString('it-IT') : '—'}
            {' · '}Voce: {selectedVersion?.voice_name} · Lingua: {selectedVersion?.language}
          </Text>
        </div>
        <Tabs
          items={[
            {
              key: 'A',
              label: 'Prompt A (Intervista)',
              children: (
                <pre style={{
                  fontFamily: 'monospace', fontSize: 12, backgroundColor: '#f5f5f5',
                  padding: 16, borderRadius: 8, overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap',
                }}>
                  {selectedVersion?.prompt_a || '—'}
                </pre>
              ),
            },
            {
              key: 'B',
              label: 'Prompt B (Estrazione)',
              children: (
                <pre style={{
                  fontFamily: 'monospace', fontSize: 12, backgroundColor: '#f5f5f5',
                  padding: 16, borderRadius: 8, overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap',
                }}>
                  {selectedVersion?.prompt_b || '—'}
                </pre>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  )
}

export default PromptHistory
