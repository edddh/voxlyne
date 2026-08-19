import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, Typography, Descriptions, Tag, Spin, message, Row, Col, Tabs, Timeline, Divider
} from 'antd'
import {
  ArrowLeftOutlined, PhoneOutlined, FilePdfOutlined, FileTextOutlined, DownloadOutlined,
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, UserOutlined
} from '@ant-design/icons'
import * as callsApi from '../api/calls'
import { BRAND } from '../main'

const { Title, Text, Paragraph } = Typography

function CallDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [call, setCall] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadCall()
  }, [id])

  const loadCall = async () => {
    setLoading(true)
    try {
      // GET /api/v2/calls/{id} (app/routers/calls.py::get_call_detail)
      // restituisce un involucro {call, transcript, record, crm_sync,
      // calendar_event} - non un oggetto piatto. Il resto della pagina
      // legge sempre `call.xxx` come se fosse la chiamata stessa, quindi
      // ogni campo in "Informazioni Generali" era undefined (mostrava
      // sempre "-"/vuoto), mentre la trascrizione risultava visibile per
      // puro caso: `data.transcript` esiste anche a livello root.
      const data = await callsApi.getCall(id)
      setCall({ ...data.call, transcript: data.transcript, record: data.record })
    } catch (error) {
      message.error('Errore caricamento chiamata')
      navigate('/calls')
    } finally {
      setLoading(false)
    }
  }

  const downloadPdf = async () => {
    try {
      const blob = await callsApi.downloadCallPdf(id)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `call_${call.phone_number}_${new Date(call.created_at).toISOString().split('T')[0]}.pdf`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      message.error('Errore download PDF')
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
      escalated: { color: 'purple', icon: <UserOutlined />, label: 'Inoltrata a operatore' },
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

  const renderTranscript = (transcript) => {
    if (!transcript || transcript.length === 0) {
      return <Text type="secondary">Nessuna trascrizione disponibile</Text>
    }

    return (
      <Timeline
        mode="left"
        items={transcript.map((msg, idx) => {
          const isAssistant = msg.role === 'assistant'
          return {
            key: idx,
            color: isAssistant ? 'blue' : 'green',
            label: (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString('it-IT') : `#${idx + 1}`}
              </Text>
            ),
            children: (
              // Prima erano sfondi chiari fissi (#e6f7ff/#f6ffed) pensati
              // per il tema chiaro di default di AntD - questa app usa
              // pero' SEMPRE darkAlgorithm (main.jsx), quindi il testo
              // ereditava il colore chiaro del tema scuro su uno sfondo
              // chiaro: bianco su bianco, illeggibile (maintainer: "ci sono
              // scritte in bianco su sfondo chiaro"). BRAND.bgElevated/
              // bgContainer sono gia' gli sfondi scuri usati nel resto
              // dell'app.
              <Card size="small" style={{
                backgroundColor: isAssistant ? BRAND.bgElevated : BRAND.bgContainer,
                borderColor: BRAND.border,
              }}>
                <Space direction="vertical" size={0} style={{ width: '100%' }}>
                  <Text strong style={{ color: isAssistant ? '#1890ff' : '#52c41a' }}>
                    {isAssistant ? '🤖 AI Assistant' : '👤 Chiamante'}
                  </Text>
                  <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
                    {msg.content}
                  </Paragraph>
                </Space>
              </Card>
            ),
          }
        })}
      />
    )
  }

  const renderRecord = (record) => {
    if (!record || Object.keys(record).length === 0) {
      return <Text type="secondary">Nessun record disponibile</Text>
    }

    return (
      <pre style={{
        backgroundColor: BRAND.bgContainer,
        color: BRAND.white,
        border: `1px solid ${BRAND.border}`,
        padding: 16,
        borderRadius: 8,
        overflow: 'auto',
        maxHeight: 600,
        fontFamily: 'monospace',
        fontSize: 12,
      }}>
        {JSON.stringify(record, null, 2)}
      </pre>
    )
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!call) return null

  const statusConfig = getStatusConfig(call.status)

  const tabItems = [
    {
      key: 'transcript',
      label: (
        <span>
          <FileTextOutlined /> Trascrizione
        </span>
      ),
      children: renderTranscript(call.transcript),
    },
    {
      key: 'record',
      label: (
        <span>
          <FileTextOutlined /> Record JSON
        </span>
      ),
      children: renderRecord(call.record?.json_data),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/calls')}>
            Indietro
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            Dettaglio Chiamata
          </Title>
        </Space>
        <Space>
          {call.has_pdf && (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={downloadPdf}
            >
              Scarica PDF
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card title="Informazioni Generali">
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Telefono">
                <Space>
                  <PhoneOutlined />
                  <Text copyable={{ text: call.phone_number }}>{call.phone_number}</Text>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Stato">
                <Tag color={statusConfig.color} icon={statusConfig.icon}>
                  {statusConfig.label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Chiamante">
                {call.candidate_name || <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="Email">
                {call.candidate_email ? (
                  <Text copyable={{ text: call.candidate_email }}>{call.candidate_email}</Text>
                ) : (
                  <Text type="secondary">-</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Progetto">
                {call.project_name ? (
                  <Tag>{call.project_name}</Tag>
                ) : (
                  <Text type="secondary">-</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Durata">
                {formatDuration(call.duration_seconds)}
              </Descriptions.Item>
              <Descriptions.Item label="Data Creazione">
                {new Date(call.created_at).toLocaleString('it-IT')}
              </Descriptions.Item>
              <Descriptions.Item label="Ultima Modifica">
                {new Date(call.updated_at).toLocaleString('it-IT')}
              </Descriptions.Item>
              {call.consent_timestamp && (
                <Descriptions.Item label="Consenso Dato">
                  {new Date(call.consent_timestamp).toLocaleString('it-IT')}
                </Descriptions.Item>
              )}
              {call.started_at && (
                <Descriptions.Item label="Chiamata Iniziata">
                  {new Date(call.started_at).toLocaleString('it-IT')}
                </Descriptions.Item>
              )}
              {call.ended_at && (
                <Descriptions.Item label="Chiamata Terminata">
                  {new Date(call.ended_at).toLocaleString('it-IT')}
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>
        </Col>

        {call.metadata && Object.keys(call.metadata).length > 0 && (
          <Col span={24}>
            <Card title="Metadata">
              <pre style={{
                backgroundColor: BRAND.bgContainer,
                color: BRAND.white,
                border: `1px solid ${BRAND.border}`,
                padding: 16,
                borderRadius: 8,
                overflow: 'auto',
                maxHeight: 200,
                fontFamily: 'monospace',
                fontSize: 12,
              }}>
                {JSON.stringify(call.metadata, null, 2)}
              </pre>
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card>
            <Tabs items={tabItems} defaultActiveKey="transcript" />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default CallDetail
