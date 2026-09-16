import { useState, useEffect, useCallback } from 'react'
import { Form, Input, Button, Alert, Typography, Space, Descriptions, Tag, Divider, message, Table, Popconfirm } from 'antd'
import { PhoneOutlined, DisconnectOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { connectNumber, disconnectNumber, listConnectedNumbers } from '../api/telephony'

const { Text, Paragraph } = Typography

/**
 * Connects a real phone number to this project: registers it with xAI's
 * byo_trunk SIP gateway and points the carrier (Zadarma, if API
 * credentials are configured for the tenant - see Credenziali tenant,
 * servizio "telephony", provider "zadarma") at xAI's SIP endpoint. One
 * click, one backend call (POST /api/telephony/connect-number) - the
 * whole reason this exists (maintainer, 18/08): "questa procedura dovra'
 * essere eseguibile tramite interfaccia ascolta, insieme alle istruzioni
 * per reindirizzare da zadarma o equivalente".
 */
function TelephonyTab({ projectId, project }) {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const [connecting, setConnecting] = useState(false)
  const [result, setResult] = useState(null)
  const [numbers, setNumbers] = useState([])
  const [loadingNumbers, setLoadingNumbers] = useState(true)

  const loadNumbers = useCallback(async () => {
    try {
      const data = await listConnectedNumbers(projectId)
      setNumbers(data.filter((n) => n.is_active))
    } catch (error) {
      message.error(t('telephonyTab.loadError'))
    } finally {
      setLoadingNumbers(false)
    }
  }, [projectId])

  useEffect(() => { loadNumbers() }, [loadNumbers])

  const handleConnect = async (values) => {
    setConnecting(true)
    setResult(null)
    try {
      const data = await connectNumber(projectId, values)
      setResult(data)
      message.success(t('telephonyTab.numberConnected', { number: values.phone_number }))
      form.resetFields()
      loadNumbers()
    } catch (error) {
      message.error(error.response?.data?.detail || t('telephonyTab.connectError'))
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async (phoneNumber) => {
    try {
      await disconnectNumber(projectId, phoneNumber)
      message.success(t('telephonyTab.numberDisconnected', { number: phoneNumber }))
      loadNumbers()
    } catch (error) {
      message.error(error.response?.data?.detail || t('telephonyTab.disconnectError'))
    }
  }

  const isEleven = project?.voice_engine === 'elevenlabs_agent'
  const providerLabel = isEleven ? 'ElevenLabs Agent' : 'xAI'
  const resultProvider = result?.provider === 'elevenlabs_agent' ? 'elevenlabs' : 'xai'
  const providerResult = result ? result[resultProvider] : null

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Text strong>{t('telephonyTab.connectedNumbers')}</Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          loading={loadingNumbers}
          dataSource={numbers}
          pagination={false}
          locale={{ emptyText: t('telephonyTab.noConnectedNumbers') }}
          columns={[
            { title: t('telephonyTab.number'), dataIndex: 'identifier' },
            { title: t('telephonyTab.type'), dataIndex: 'identifier_type' },
            {
              title: t('tenantCredentials.actions'),
              key: 'actions',
              render: (_, r) => (
                <Popconfirm
                  title={t('telephonyTab.confirmDisconnect', { number: r.identifier })}
                  description={t('telephonyTab.confirmDisconnectDescription')}
                  onConfirm={() => handleDisconnect(r.identifier)}
                >
                  <Button size="small" danger icon={<DisconnectOutlined />}>{t('telephonyTab.disconnect')}</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </div>

      <Divider />

      <Alert
        type="info"
        showIcon
        message={t('telephonyTab.connectNewNumber')}
        description={
          isEleven
            ? t('telephonyTab.elevenDescription')
            : t('telephonyTab.xaiDescription')
        }
      />

      <Form form={form} layout="vertical" onFinish={handleConnect}>
        <Form.Item
          name="phone_number"
          label={t('telephonyTab.phoneNumber')}
          rules={[{ required: true, message: t('telephonyTab.enterE164Number') }]}
          tooltip={t('telephonyTab.e164Tooltip')}
        >
          <Input prefix={<PhoneOutlined />} placeholder="+39 000 000 0000" />
        </Form.Item>
        <Form.Item name="name" label={t('telephonyTab.labelOptional')}>
          <Input placeholder={t('telephonyTab.labelPlaceholder')} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={connecting}>
          {isEleven ? t('telephonyTab.prepareElevenConnection') : t('telephonyTab.connectNumber')}
        </Button>
      </Form>

      {result && (
        <>
          <Divider />
          <Descriptions column={1} bordered size="small" title={t('telephonyTab.result')}>
            <Descriptions.Item label={t('telephonyTab.number')}>{result.phone_number}</Descriptions.Item>
            {!isEleven && result.webhook_url && (
              <Descriptions.Item label="Webhook">{result.webhook_url}</Descriptions.Item>
            )}
            <Descriptions.Item label={providerLabel}>
              <Tag color="green">{providerResult?.status || 'ok'}</Tag> {providerResult?.sip_uri}
            </Descriptions.Item>
            <Descriptions.Item label="Zadarma">
              {result.zadarma.status === 'automated' && <Tag color="green">{t('telephonyTab.automated')}</Tag>}
              {result.zadarma.status === 'manual_required' && <Tag color="orange">{t('telephonyTab.manualInstructions')}</Tag>}
              {result.zadarma.status === 'failed' && <Tag color="red">{t('telephonyTab.failed')}</Tag>}
              {result.zadarma.status === 'not_attempted' && <Tag>{t('telephonyTab.notAttempted')}</Tag>}
            </Descriptions.Item>
            {result.rollback?.previous_target_sip_uri && (
              <Descriptions.Item label={t('telephonyTab.sipRollback')}>{result.rollback.previous_target_sip_uri}</Descriptions.Item>
            )}
          </Descriptions>

          {(result.zadarma.status === 'manual_required' || result.zadarma.status === 'failed') && (
            <Alert
              type="warning"
              showIcon
              message={t('telephonyTab.manualStepsRequired')}
              description={<Paragraph style={{ whiteSpace: 'pre-line', marginBottom: 0 }}>{result.zadarma.steps}</Paragraph>}
            />
          )}
        </>
      )}
    </Space>
  )
}

export default TelephonyTab
