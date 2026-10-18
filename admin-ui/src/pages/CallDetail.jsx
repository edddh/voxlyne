import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, Typography, Descriptions, Tag, Spin, message, Row, Col, Tabs, Timeline, Divider
} from 'antd'
import {
  ArrowLeftOutlined, PhoneOutlined, FilePdfOutlined, FileTextOutlined, DownloadOutlined,
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, UserOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as callsApi from '../api/calls'
import { BRAND } from '../main'
import { useAuth } from '../hooks/useAuth'

const { Title, Text, Paragraph } = Typography

function CallDetail() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const isDemo = user?.tenant_slug === 'demo-showcase'
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
      message.error(t('callDetail.loadError'))
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
      message.error(t('callDetail.pdfDownloadError'))
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
      declined: { color: 'red', icon: <CloseCircleOutlined />, label: t(isDemo ? 'demo.noAnswer' : 'analytics.statusDeclined') },
      escalated: { color: 'purple', icon: <UserOutlined />, label: t('analytics.statusEscalated') },
      cancelled: { color: 'default', icon: <CloseCircleOutlined />, label: t(isDemo ? 'demo.failed' : 'analytics.statusCancelled') },
    }
    return configs[status] || { color: 'default', label: status }
  }

  const formatDuration = (seconds) => {
    if (!seconds) return '-'
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const collapseProgressiveTranscript = (transcript) => {
    const collapsed = []
    for (const msg of transcript || []) {
      const previous = collapsed[collapsed.length - 1]
      const currentContent = (msg?.content || '').trim()
      const previousContent = (previous?.content || '').trim()
      if (
        previous &&
        previous.role === msg.role &&
        currentContent &&
        previousContent &&
        (currentContent === previousContent || currentContent.startsWith(previousContent))
      ) {
        collapsed[collapsed.length - 1] = msg
        continue
      }
      collapsed.push(msg)
    }
    return collapsed
  }

  const renderTranscript = (transcript) => {
    if (!transcript || transcript.length === 0) {
      return <Text type="secondary">{t('callDetail.noTranscript')}</Text>
    }

    const cleanedTranscript = collapseProgressiveTranscript(transcript)

    return (
      <Timeline
        mode="left"
        items={cleanedTranscript.map((msg, idx) => {
          const isAssistant = msg.role === 'assistant'
          return {
            key: idx,
            color: isAssistant ? 'blue' : 'green',
            label: (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString(i18n.language) : `#${idx + 1}`}
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
                    {isAssistant ? `🤖 ${t('callDetail.aiAssistant')}` : `👤 ${t('callDetail.caller')}`}
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
      return <Text type="secondary">{t('callDetail.noRecord')}</Text>
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
          <FileTextOutlined /> {t('callDetail.transcript')}
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
            {t('callDetail.back')}
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            {t('callDetail.title')}
          </Title>
        </Space>
        <Space>
          {call.has_pdf && (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={downloadPdf}
            >
              {t('callDetail.downloadPdf')}
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card title={t('callDetail.generalInfo')}>
            <Descriptions column={2} bordered>
              <Descriptions.Item label={t('callDetail.phone')}>
                <Space>
                  <PhoneOutlined />
                  <Text copyable={{ text: call.phone_number }}>{call.phone_number}</Text>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label={t('tenantCredentials.status')}>
                <Tag color={statusConfig.color} icon={statusConfig.icon}>
                  {statusConfig.label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('callDetail.caller')}>
                {call.candidate_name || <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="Email">
                {call.candidate_email ? (
                  <Text copyable={{ text: call.candidate_email }}>{call.candidate_email}</Text>
                ) : (
                  <Text type="secondary">-</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label={t('dashboard.project')}>
                {call.project_name ? (
                  <Tag>{call.project_name}</Tag>
                ) : (
                  <Text type="secondary">-</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label={t('callDetail.duration')}>
                {formatDuration(call.duration_seconds)}
              </Descriptions.Item>
              {call.can_view_costs && (
                <Descriptions.Item label={t('callDetail.estimatedCost')}>
                  {call.cost_usd != null ? `$${call.cost_usd.toFixed(4)}` : <Text type="secondary">{t('callDetail.notAvailable')}</Text>}
                </Descriptions.Item>
              )}
              <Descriptions.Item label={t('callDetail.createdDate')}>
                {new Date(call.created_at).toLocaleString(i18n.language)}
              </Descriptions.Item>
              <Descriptions.Item label={t('callDetail.lastModified')}>
                {new Date(call.updated_at).toLocaleString(i18n.language)}
              </Descriptions.Item>
              {call.consent_timestamp && (
                <Descriptions.Item label={t('callDetail.consentGiven')}>
                  {new Date(call.consent_timestamp).toLocaleString(i18n.language)}
                </Descriptions.Item>
              )}
              {call.started_at && (
                <Descriptions.Item label={t('callDetail.callStarted')}>
                  {new Date(call.started_at).toLocaleString(i18n.language)}
                </Descriptions.Item>
              )}
              {call.ended_at && (
                <Descriptions.Item label={t('callDetail.callEnded')}>
                  {new Date(call.ended_at).toLocaleString(i18n.language)}
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
