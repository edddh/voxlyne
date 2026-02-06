import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, Input, message, Typography, Tabs, Row, Col, Spin, Alert, Tag, Divider, Switch, Form
} from 'antd'
import { SaveOutlined, ArrowLeftOutlined, HistoryOutlined, RocketOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as promptsApi from '../api/prompts'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

function ProjectEdit() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [promptA, setPromptA] = useState('')
  const [promptB, setPromptB] = useState('')
  const [activeVersionA, setActiveVersionA] = useState(null)
  const [activeVersionB, setActiveVersionB] = useState(null)
  const [hasChangesA, setHasChangesA] = useState(false)
  const [hasChangesB, setHasChangesB] = useState(false)

  useEffect(() => {
    loadProject()
  }, [id])

  const loadProject = async () => {
    setLoading(true)
    try {
      const data = await projectsApi.getProject(id)
      setProject(data)

      // Load active prompt versions
      try {
        const versionsA = await promptsApi.getPromptVersions(id, 'A')
        const activeA = versionsA.find(v => v.is_active)
        if (activeA) {
          setPromptA(activeA.content)
          setActiveVersionA(activeA)
        }
      } catch (e) {
        // No versions yet
      }

      try {
        const versionsB = await promptsApi.getPromptVersions(id, 'B')
        const activeB = versionsB.find(v => v.is_active)
        if (activeB) {
          setPromptB(activeB.content)
          setActiveVersionB(activeB)
        }
      } catch (e) {
        // No versions yet
      }
    } catch (error) {
      message.error('Errore caricamento progetto')
      navigate('/projects')
    } finally {
      setLoading(false)
    }
  }

  const handlePromptChange = (type, value) => {
    if (type === 'A') {
      setPromptA(value)
      setHasChangesA(value !== (activeVersionA?.content || ''))
    } else {
      setPromptB(value)
      setHasChangesB(value !== (activeVersionB?.content || ''))
    }
  }

  const savePrompt = async (type) => {
    setSaving(true)
    try {
      const content = type === 'A' ? promptA : promptB
      if (!content.trim()) {
        message.warning('Il prompt non può essere vuoto')
        return
      }

      const newVersion = await promptsApi.createPromptVersion(id, type, content)
      await promptsApi.activatePromptVersion(newVersion.id)

      message.success(`Prompt ${type} salvato e attivato (v${newVersion.version})`)

      if (type === 'A') {
        setActiveVersionA(newVersion)
        setHasChangesA(false)
      } else {
        setActiveVersionB(newVersion)
        setHasChangesB(false)
      }
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }

  const promptItems = [
    {
      key: 'A',
      label: (
        <Space>
          <span>Prompt A (Intervista)</span>
          {activeVersionA && <Tag color="blue">v{activeVersionA.version}</Tag>}
          {hasChangesA && <Tag color="orange">Modificato</Tag>}
        </Space>
      ),
      children: (
        <div>
          <Alert
            message="Prompt di Intervista"
            description="Questo prompt guida l'AI durante il colloquio telefonico. Include istruzioni su come condurre l'intervista, le domande da porre e come gestire le risposte del candidato."
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
          <TextArea
            value={promptA}
            onChange={(e) => handlePromptChange('A', e.target.value)}
            rows={20}
            placeholder="Inserisci il prompt di intervista..."
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">
              {promptA.length} caratteri • ~{Math.ceil(promptA.length / 4)} token
            </Text>
            <Space>
              <Button
                icon={<HistoryOutlined />}
                onClick={() => navigate(`/projects/${id}/history?type=A`)}
              >
                Storico
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={() => savePrompt('A')}
                loading={saving}
                disabled={!hasChangesA}
              >
                Salva come nuova versione
              </Button>
            </Space>
          </div>
        </div>
      ),
    },
    {
      key: 'B',
      label: (
        <Space>
          <span>Prompt B (Estrazione)</span>
          {activeVersionB && <Tag color="purple">v{activeVersionB.version}</Tag>}
          {hasChangesB && <Tag color="orange">Modificato</Tag>}
        </Space>
      ),
      children: (
        <div>
          <Alert
            message="Prompt di Estrazione"
            description="Questo prompt viene usato per estrarre informazioni strutturate dalla trascrizione del colloquio. Definisce il formato JSON di output e i campi da estrarre."
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
          <TextArea
            value={promptB}
            onChange={(e) => handlePromptChange('B', e.target.value)}
            rows={20}
            placeholder="Inserisci il prompt di estrazione..."
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">
              {promptB.length} caratteri • ~{Math.ceil(promptB.length / 4)} token
            </Text>
            <Space>
              <Button
                icon={<HistoryOutlined />}
                onClick={() => navigate(`/projects/${id}/history?type=B`)}
              >
                Storico
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={() => savePrompt('B')}
                loading={saving}
                disabled={!hasChangesB}
              >
                Salva come nuova versione
              </Button>
            </Space>
          </div>
        </div>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
            Indietro
          </Button>
          <Title level={3} style={{ margin: 0 }}>{project?.name}</Title>
          <Tag color={project?.is_active ? 'green' : 'red'}>
            {project?.is_active ? 'Attivo' : 'Inattivo'}
          </Tag>
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        <Col span={24}>
          <Card>
            <Paragraph type="secondary">
              <strong>Slug:</strong> <code>{project?.slug}</code>
            </Paragraph>
            {project?.description && (
              <Paragraph type="secondary">
                <strong>Descrizione:</strong> {project.description}
              </Paragraph>
            )}
          </Card>
        </Col>

        <Col span={24}>
          <Card title="Editor Prompt">
            <Tabs items={promptItems} />
          </Card>
        </Col>

        <Col span={24}>
          <Card title="Configurazione Output">
            <Row gutter={[16, 16]}>
              <Col span={6}>
                <Card size="small" title="Email PDF">
                  <Switch
                    checked={project?.config?.send_email || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Invia PDF via email dopo la chiamata
                  </Text>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" title="Sync CRM">
                  <Switch
                    checked={project?.config?.sync_crm || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Sincronizza con HubSpot
                  </Text>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" title="Calendario">
                  <Switch
                    checked={project?.config?.create_event || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Crea evento calendario
                  </Text>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" title="Webhook">
                  <Switch
                    checked={project?.config?.webhook_enabled || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Notifica webhook
                  </Text>
                </Card>
              </Col>
            </Row>
            <Divider />
            <Text type="secondary">
              Le configurazioni di output si gestiscono dalla scheda Impostazioni del progetto.
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default ProjectEdit
