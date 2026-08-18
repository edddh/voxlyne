import { useState } from 'react'
import { Form, Input, Button, Alert, Typography, Space, Descriptions, Tag, Divider, message } from 'antd'
import { PhoneOutlined } from '@ant-design/icons'
import { connectNumber } from '../api/telephony'

const { Text, Paragraph } = Typography

/**
 * Connects a real phone number to this project: registers it with xAI's
 * byo_trunk SIP gateway and points the carrier (Zadarma, if API
 * credentials are configured for the tenant - see Credenziali tenant,
 * servizio "telephony", provider "zadarma") at xAI's SIP endpoint. One
 * click, one backend call (POST /api/telephony/connect-number) - the
 * whole reason this exists (maintainer, 18/08): "questa procedura dovra'
 * essere eseguibile tramite interfaccia ascolta, insieme con le istruzioni
 * per reindirizzare da zadarma o equivalente".
 */
function TelephonyTab({ projectId }) {
  const [form] = Form.useForm()
  const [connecting, setConnecting] = useState(false)
  const [result, setResult] = useState(null)

  const handleConnect = async (values) => {
    setConnecting(true)
    setResult(null)
    try {
      const data = await connectNumber(projectId, values)
      setResult(data)
      message.success(`Numero ${values.phone_number} collegato a questo progetto`)
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore durante il collegamento del numero')
    } finally {
      setConnecting(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="Collega un numero reale a questo progetto"
        description="Registra il numero presso xAI (Grok voice) e configura l'instradamento SIP lato Zadarma (se le credenziali API sono configurate per questo tenant), oppure mostra le istruzioni manuali per farlo a mano."
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
          Collega numero
        </Button>
      </Form>

      {result && (
        <>
          <Divider />
          <Descriptions column={1} bordered size="small" title="Risultato">
            <Descriptions.Item label="Numero">{result.phone_number}</Descriptions.Item>
            <Descriptions.Item label="Webhook">{result.webhook_url}</Descriptions.Item>
            <Descriptions.Item label="xAI">
              <Tag color="green">{result.xai.status}</Tag> {result.xai.sip_uri}
            </Descriptions.Item>
            <Descriptions.Item label="Zadarma">
              {result.zadarma.status === 'automated' && <Tag color="green">automatizzato</Tag>}
              {result.zadarma.status === 'manual_required' && <Tag color="orange">istruzioni manuali</Tag>}
              {result.zadarma.status === 'failed' && <Tag color="red">fallito</Tag>}
              {result.zadarma.status === 'not_attempted' && <Tag>non tentato</Tag>}
            </Descriptions.Item>
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
