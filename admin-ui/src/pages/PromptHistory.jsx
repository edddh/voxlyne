import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Space, message, Typography, Table, Tag, Modal, Spin, Popconfirm, Tabs } from 'antd'
import { ArrowLeftOutlined, RollbackOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as projectsApi from '../api/projects'
import * as agentVersionsApi from '../api/agentVersions'
import { BRAND } from '../main'

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
  const { t, i18n } = useTranslation()
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
      message.error(t('promptHistory.loadError'))
      navigate('/projects')
    } finally {
      setLoading(false)
    }
  }

  const handleRollback = async (versionId) => {
    setRollingBack(versionId)
    try {
      await agentVersionsApi.rollbackToVersion(id, versionId)
      message.success(t('promptHistory.rollbackSuccess'))
      loadData()
    } catch (error) {
      message.error(error.response?.data?.detail || t('promptHistory.rollbackError'))
    } finally {
      setRollingBack(null)
    }
  }

  const columns = [
    {
      title: t('promptHistory.version'),
      dataIndex: 'version_number',
      key: 'version_number',
      width: 100,
      render: (v, record) => (
        <Space>
          <Text strong>v{v}</Text>
          {record.status === 'published' && <Tag color="green">{t('promptHistory.published')}</Tag>}
          {record.status === 'archived' && <Tag>{t('promptHistory.archived')}</Tag>}
        </Space>
      ),
    },
    {
      title: t('promptHistory.promptPreview'),
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
      title: t('promptHistory.voiceLanguage'),
      key: 'voice',
      width: 140,
      render: (_, record) => <Text type="secondary">{record.voice_name} · {record.language}</Text>,
    },
    {
      title: t('promptHistory.publishedOn'),
      dataIndex: 'published_at',
      key: 'published_at',
      width: 180,
      render: (date) => (date ? new Date(date).toLocaleString(i18n.language) : '—'),
    },
    {
      title: t('promptHistory.actions'),
      key: 'actions',
      width: 220,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => setSelectedVersion(record)}>
            {t('promptHistory.view')}
          </Button>
          {record.status !== 'published' && (
            <Popconfirm
              title={t('promptHistory.confirmRollback')}
              onConfirm={() => handleRollback(record.id)}
              okText={t('promptHistory.yes')}
              cancelText={t('promptHistory.no')}
            >
              <Button size="small" icon={<RollbackOutlined />} loading={rollingBack === record.id}>
                {t('promptHistory.restore')}
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
            {t('promptHistory.backToEditor')}
          </Button>
          <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{t('promptHistory.versionHistory')}: {project?.name}</Title>
        </Space>
      </div>

      <Card>
        {versions.length === 0 ? (
          <Text type="secondary">
            {t('promptHistory.noVersionsYet')}
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
        title={`${t('promptHistory.version')} ${selectedVersion?.version_number}`}
        open={!!selectedVersion}
        onCancel={() => setSelectedVersion(null)}
        footer={[
          <Button key="close" onClick={() => setSelectedVersion(null)}>
            {t('promptHistory.close')}
          </Button>,
        ]}
        width={800}
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            {t('promptHistory.publishedLabel')}: {selectedVersion?.published_at ? new Date(selectedVersion.published_at).toLocaleString(i18n.language) : '—'}
            {' · '}{t('promptHistory.voiceLabel')}: {selectedVersion?.voice_name} · {t('promptHistory.languageLabel')}: {selectedVersion?.language}
          </Text>
        </div>
        <Tabs
          items={[
            {
              key: 'A',
              label: t('promptHistory.promptAConversation'),
              children: (
                <pre style={{
                  fontFamily: 'monospace', fontSize: 12, backgroundColor: BRAND.bgElevated, color: BRAND.white,
                  padding: 16, borderRadius: 8, overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap',
                }}>
                  {selectedVersion?.prompt_a || '—'}
                </pre>
              ),
            },
            {
              key: 'B',
              label: t('promptHistory.promptBExtraction'),
              children: (
                <pre style={{
                  fontFamily: 'monospace', fontSize: 12, backgroundColor: BRAND.bgElevated, color: BRAND.white,
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
