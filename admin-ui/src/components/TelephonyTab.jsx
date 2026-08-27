import { useState, useEffect, useCallback } from 'react'
import { Form, Input, Button, Alert, Typography, Space, Descriptions, Tag, Divider, message, Table, Popconfirm } from 'antd'
import { PhoneOutlined, DisconnectOutlined } from '@ant-design/icons'
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
      message.error('Errore nel caricamento dei numeri collegati')
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
      message.success(`Numero ${values.phone_number} collegato a questo progetto`)
      form.resetFields()
      loadNumbers()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore durante il collegamento del numero')
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async (phoneNumber) => {
    try {
      await disconnectNumber(projectId, phoneNumber)
      message.success(`Numero ${phoneNumber} scollegato (deregistrato da xAI)`)
      loadNumbers()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore durante lo scollegamento')
    }
  }

  const isEleven = project?.voice_engine === 'elevenlabs_agent'
  const providerLabel = isEleven ? 'ElevenLabs Agent' : 'xAI'
  const resultProvider = result?.provider === 'elevenlabs_agent' ? 'elevenlabs' : 'xai'
  const providerResult = result ? result[resultProvider] : null

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Text strong>Numeri collegati a questo progetto</Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          loading={loadingNumbers}
          dataSource={numbers}
          pagination={false}
          locale={{ emptyText: 'Nessun numero collegato' }}
          columns={[
            { title: 'Numero', dataIndex: 'identifier' },
            { title: 'Tipo', dataIndex: 'identifier_type' },
            {
              title: 'Azioni',
              key: 'actions',
              render: (_, r) => (
                <Popconfirm
                  title={`Scollegare ${r.identifier}?`}
                  description="Deregistra il numero da xAI - il numero smettera' di rispondere finche' non lo ricolleghi."
                  onConfirm={() => handleDisconnect(r.identifier)}
                >
                  <Button size="small" danger icon={<DisconnectOutlined />}>Scollega</Button>
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
        message="Collega un nuovo numero reale a questo progetto"
        description={
          isEleven
            ? 'Provisiona o aggiorna l’agente Eleven v3 Conversational di questo progetto e prepara lo switch Zadarma verso il SIP trunk ElevenLabs, con istruzioni di rollback.'
            : 'Registra il numero presso xAI (Grok voice) e configura l’instradamento SIP lato Zadarma (se le credenziali API sono configurate per questo tenant), oppure mostra le istruzioni manuali per farlo a mano.'
        }
      />

      <Form form={form} layout="vertical" onFinish={handleConnect}>
        <Form.Item
          name="phone_number"
          label="Numero di telefono"
          rules={[{ required: true, message: 'Inserisci il numero in formato E.164' }]}
          tooltip="Formato E.164, es. +39 000 000 0000"
        >
          <Input prefix={<PhoneOutlined />} placeholder="+39 000 000 0000" />
        </Form.Item>
        <Form.Item name="name" label="Etichetta (opzionale)">
          <Input placeholder="Usa lo slug del progetto se lasciato vuoto" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={connecting}>
          {isEleven ? 'Prepara collegamento Eleven' : 'Collega numero'}
        </Button>
      </Form>

      {result && (
        <>
          <Divider />
          <Descriptions column={1} bordered size="small" title="Risultato">
            <Descriptions.Item label="Numero">{result.phone_number}</Descriptions.Item>
            {!isEleven && result.webhook_url && (
              <Descriptions.Item label="Webhook">{result.webhook_url}</Descriptions.Item>
            )}
            <Descriptions.Item label={providerLabel}>
              <Tag color="green">{providerResult?.status || 'ok'}</Tag> {providerResult?.sip_uri}
            </Descriptions.Item>
            <Descriptions.Item label="Zadarma">
              {result.zadarma.status === 'automated' && <Tag color="green">automatizzato</Tag>}
              {result.zadarma.status === 'manual_required' && <Tag color="orange">istruzioni manuali</Tag>}
              {result.zadarma.status === 'failed' && <Tag color="red">fallito</Tag>}
              {result.zadarma.status === 'not_attempted' && <Tag>non tentato</Tag>}
            </Descriptions.Item>
            {result.rollback?.previous_target_sip_uri && (
              <Descriptions.Item label="Rollback SIP">{result.rollback.previous_target_sip_uri}</Descriptions.Item>
            )}
          </Descriptions>

          {(result.zadarma.status === 'manual_required' || result.zadarma.status === 'failed') && (
            <Alert
              type="warning"
              showIcon
              message="Passi manuali richiesti lato Zadarma (o provider equivalente)"
              description={<Paragraph style={{ whiteSpace: 'pre-line', marginBottom: 0 }}>{result.zadarma.steps}</Paragraph>}
            />
          )}
        </>
      )}
    </Space>
  )
}

export default TelephonyTab
