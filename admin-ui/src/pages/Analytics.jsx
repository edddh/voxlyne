import { useState, useEffect } from 'react'
import { Card, Row, Col, Select, Typography, Spin, Empty } from 'antd'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, Cell, LabelList,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import * as analyticsApi from '../api/analytics'
import { BRAND } from '../main'

const { Title, Text } = Typography

/**
 * Analytics - vista approfondita, separata dalla Dashboard (che resta il
 * riepilogo rapido). maintainer, 20/08: "pagina Analytics separata e piu'
 * completa" - usa due endpoint gia' pronti sul backend
 * (GET /api/analytics/calls, GET /api/analytics/calls/by-status) mai
 * collegati a nessuna pagina finora.
 *
 * Colori scelti seguendo la skill dataviz del progetto: la terna della
 * linea (Totali/Completate/Annullate) e' validata con
 * scripts/validate_palette.js in modalita' dark contro la superficie di
 * questa app (BRAND.bgContainer) - ALL CHECKS PASS, nessun warning CVD.
 * I colori "per stato" invece riusano deliberatamente le stesse
 * associazioni gia' in uso in Calls.jsx/CallDetail.jsx (getStatusConfig)
 * - e' un lavoro di identita' di stato, non una nuova palette categorica,
 * e gli utenti l'hanno gia' imparata da quelle pagine.
 */
const TREND_COLORS = {
  total: '#3987e5',
  completed: '#199e70',
  cancelled: '#d95926',
}

const STATUS_COLORS = {
  pending_consent: '#8c8c8c',
  consented: '#1890ff',
  in_progress: '#faad14',
  completed: '#52c41a',
  processing: '#fa8c16',
  processed: '#52c41a',
  declined: '#ff4d4f',
  escalated: '#722ed1',
  cancelled: '#8c8c8c',
}

function Analytics() {
  const { t, i18n } = useTranslation()
  const [period, setPeriod] = useState('week')
  const [days, setDays] = useState(30)
  const [trends, setTrends] = useState(null)
  const [byStatus, setByStatus] = useState(null)
  const [loadingTrends, setLoadingTrends] = useState(true)
  const [loadingStatus, setLoadingStatus] = useState(true)

  const STATUS_LABELS = {
    pending_consent: t('analytics.statusPendingConsent'),
    consented: t('analytics.statusConsented'),
    in_progress: t('analytics.statusInProgress'),
    completed: t('analytics.statusCompleted'),
    processing: t('analytics.statusProcessing'),
    processed: t('analytics.statusProcessed'),
    declined: t('analytics.statusDeclined'),
    escalated: t('analytics.statusEscalated'),
    cancelled: t('analytics.statusCancelled'),
  }

  useEffect(() => {
    setLoadingTrends(true)
    analyticsApi.getCallTrends(period)
      .then(setTrends)
      .catch(() => setTrends(null))
      .finally(() => setLoadingTrends(false))
  }, [period])

  useEffect(() => {
    setLoadingStatus(true)
    analyticsApi.getCallsByStatus(days)
      .then(setByStatus)
      .catch(() => setByStatus(null))
      .finally(() => setLoadingStatus(false))
  }, [days])

  const formatDate = (iso) => {
    const d = new Date(iso)
    return period === 'day'
      ? d.toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString(i18n.language, { day: '2-digit', month: '2-digit' })
  }

  const trendData = (trends?.points || []).map((p) => ({
    ...p,
    label: formatDate(p.date),
  }))

  const statusData = byStatus
    ? Object.entries(byStatus.by_status)
        .filter(([, count]) => count > 0)
        .map(([status, count]) => ({
          status,
          label: STATUS_LABELS[status] || status,
          count,
          color: STATUS_COLORS[status] || BRAND.textDim,
        }))
        .sort((a, b) => b.count - a.count)
    : []

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>{t('analytics.title')}</Title>

      <Row gutter={[24, 24]}>
        <Col span={24}>
          <Card
            title={t('analytics.callTrends')}
            extra={
              <Select
                value={period}
                onChange={setPeriod}
                options={[
                  { value: 'day', label: t('analytics.last24h') },
                  { value: 'week', label: t('analytics.last7d') },
                  { value: 'month', label: t('analytics.last30d') },
                ]}
                style={{ width: 160 }}
              />
            }
          >
            {loadingTrends ? (
              <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
            ) : trendData.length === 0 ? (
              <Empty description={t('analytics.noCallsInPeriod')} />
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={trendData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={BRAND.border} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" stroke={BRAND.textDim} fontSize={12} />
                  <YAxis stroke={BRAND.textDim} fontSize={12} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: BRAND.bgElevated, border: `1px solid ${BRAND.border}`, borderRadius: 8 }}
                    labelStyle={{ color: BRAND.white }}
                  />
                  <Legend
                    formatter={(value) => ({
                      total: t('analytics.legendTotal'),
                      completed: t('analytics.legendCompleted'),
                      cancelled: t('analytics.legendCancelled'),
                    }[value] || value)}
                  />
                  <Line type="monotone" dataKey="total" name="total" stroke={TREND_COLORS.total} strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="completed" name="completed" stroke={TREND_COLORS.completed} strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="cancelled" name="cancelled" stroke={TREND_COLORS.cancelled} strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>

        <Col span={24}>
          <Card
            title={t('analytics.callsByStatus')}
            extra={
              <Select
                value={days}
                onChange={setDays}
                options={[
                  { value: 7, label: t('analytics.last7d') },
                  { value: 30, label: t('analytics.last30d') },
                  { value: 90, label: t('analytics.last90d') },
                ]}
                style={{ width: 160 }}
              />
            }
          >
            {loadingStatus ? (
              <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
            ) : statusData.length === 0 ? (
              <Empty description={t('analytics.noCallsInPeriod')} />
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(220, statusData.length * 48)}>
                <BarChart data={statusData} layout="vertical" margin={{ top: 8, right: 32, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={BRAND.border} strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" stroke={BRAND.textDim} fontSize={12} allowDecimals={false} />
                  <YAxis type="category" dataKey="label" stroke={BRAND.textDim} fontSize={12} width={160} />
                  <Tooltip
                    contentStyle={{ background: BRAND.bgElevated, border: `1px solid ${BRAND.border}`, borderRadius: 8 }}
                    labelStyle={{ color: BRAND.white }}
                    formatter={(value) => [value, t('analytics.calls')]}
                  />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={28}>
                    {statusData.map((entry) => (
                      <Cell key={entry.status} fill={entry.color} />
                    ))}
                    <LabelList dataKey="count" position="right" style={{ fill: BRAND.white, fontSize: 12 }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              {t('analytics.totalInPeriod', { count: byStatus?.total ?? 0 })}
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Analytics
