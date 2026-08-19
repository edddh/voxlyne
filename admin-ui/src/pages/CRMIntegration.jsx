import { useState, useEffect } from 'react'
import {
  Card, Button, Space, Form, Input, Switch, message, Typography, Descriptions, Tag, Alert, Divider, Row, Col
} from 'antd'
import { ApiOutlined, CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, SyncOutlined } from '@ant-design/icons'
import * as crmApi from '../api/crm'

const { Title, Text, Paragraph } = Typography

function CRMIntegration() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [config, setConfig] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const data = await crmApi.getCRMConfig()
      setConfig(data)
      form.setFieldsValue({
        enabled: data.enabled || false,
        api_key: data.api_key || '',
        portal_id: data.portal_id || '',
        default_pipeline: data.default_pipeline || '',
        default_stage: data.default_stage || '',
        sync_contacts: data.sync_contacts !== false,
        sync_deals: data.sync_deals !== false,
        create_tasks: data.create_tasks || false,
      })
    } catch (error) {
      if (error.response?.status === 404) {
        // No config yet
        form.setFieldsValue({
          enabled: false,
          sync_contacts: true,
          sync_deals: true,
          create_tasks: false,
        })
      } else {
        message.error('Errore caricamento configurazione')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values) => {
    setSaving(true)
    try {
      await crmApi.updateCRMConfig(values)
      message.success('Configurazione salvata')
      loadConfig()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await crmApi.testCRMConnection()
      setTestResult(result)
      if (result.success) {
        message.success('Connessione riuscita!')
      } else {
        message.error('Connessione fallita')
      }
    } catch (error) {
      setTestResult({
        success: false,
        message: error.response?.data?.detail || 'Errore test connessione',
      })
      message.error('Errore test connessione')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 24 }}>
        <ApiOutlined /> Integrazione CRM (HubSpot)
      </Title>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Alert
            message="Integrazione HubSpot"
            description="Configura la connessione con HubSpot per sincronizzare automaticamente contatti, deal e attività dalle interviste telefoniche. L'API key deve avere i permessi per Contacts, Deals e Tasks."
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        </Col>

        {config && config.enabled && (
          <Col span={24}>
            <Card size="small">
              <Space>
                <Text strong>Stato:</Text>
                <Tag color="green" icon={<CheckCircleOutlined />}>
                  Integrazione Attiva
                </Tag>
                <Divider type="vertical" />
                <Text type="secondary">
                  Ultima sincronizzazione: {config.last_sync ? new Date(config.last_sync).toLocaleString('it-IT') : 'Mai'}
                </Text>
              </Space>
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card title="Configurazione" loading={loading}>
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
            >
              <Form.Item
                name="enabled"
                label="Abilita Integrazione"
                valuePropName="checked"
              >
                <Switch checkedChildren="Attivo" unCheckedChildren="Inattivo" />
              </Form.Item>

              <Divider />

              <Form.Item
                name="api_key"
                label="HubSpot API Key"
                rules={[
                  { required: true, message: 'Inserisci API key' },
                ]}
                extra="La tua private app API key da HubSpot (inizia con 'pat-')"
              >
                <Input.Password placeholder="pat-..." />
              </Form.Item>

              <Form.Item
                name="portal_id"
                label="Portal ID (Hub ID)"
                rules={[
                  { required: true, message: 'Inserisci portal ID' },
                ]}
                extra="Il tuo Hub ID, visibile nelle impostazioni HubSpot"
              >
                <Input placeholder="12345678" />
              </Form.Item>

              <Divider orientation="left">Pipeline e Stage</Divider>

              <Form.Item
                name="default_pipeline"
                label="Pipeline Predefinita"
                extra="ID della pipeline da usare per i deal (es: 'default')"
              >
                <Input placeholder="default" />
              </Form.Item>

              <Form.Item
                name="default_stage"
                label="Stage Predefinita"
                extra="ID dello stage iniziale (es: 'appointmentscheduled')"
              >
                <Input placeholder="appointmentscheduled" />
              </Form.Item>

              <Divider orientation="left">Opzioni Sincronizzazione</Divider>

              <Form.Item
                name="sync_contacts"
                label="Sincronizza Contatti"
                valuePropName="checked"
                extra="Crea o aggiorna contatti HubSpot da chi chiama"
              >
                <Switch />
              </Form.Item>

              <Form.Item
                name="sync_deals"
                label="Sincronizza Deal"
                valuePropName="checked"
                extra="Crea deal per ogni chiamata completata"
              >
                <Switch />
              </Form.Item>

              <Form.Item
                name="create_tasks"
                label="Crea Task di Follow-up"
                valuePropName="checked"
                extra="Crea automaticamente task per follow-up post-chiamata"
              >
                <Switch />
              </Form.Item>

              <Form.Item>
                <Space>
                  <Button
                    type="primary"
                    htmlType="submit"
                    icon={<SaveOutlined />}
                    loading={saving}
                  >
                    Salva Configurazione
                  </Button>
                  <Button
                    icon={<SyncOutlined />}
                    onClick={testConnection}
                    loading={testing}
                  >
                    Test Connessione
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        {testResult && (
          <Col span={24}>
            <Alert
              message={testResult.success ? 'Test Riuscito' : 'Test Fallito'}
              description={
                <div>
                  <Paragraph>{testResult.message}</Paragraph>
                  {testResult.portal_id && (
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="Portal ID">{testResult.portal_id}</Descriptions.Item>
                      <Descriptions.Item label="Account Name">{testResult.account_name}</Descriptions.Item>
                    </Descriptions>
                  )}
                </div>
              }
              type={testResult.success ? 'success' : 'error'}
              showIcon
              closable
              onClose={() => setTestResult(null)}
            />
          </Col>
        )}

        <Col span={24}>
          <Card title="Guida Rapida" size="small">
            <Paragraph>
              <Text strong>Come ottenere l'API Key:</Text>
            </Paragraph>
            <ol>
              <li>Accedi al tuo account HubSpot</li>
              <li>Vai in Settings → Integrations → Private Apps</li>
              <li>Crea una nuova Private App o usa una esistente</li>
              <li>Assicurati che abbia i permessi: Contacts (Read/Write), Deals (Read/Write), Tasks (Read/Write)</li>
              <li>Copia l'API key (inizia con "pat-")</li>
            </ol>

            <Divider />

            <Paragraph>
              <Text strong>Come trovare Portal ID e Pipeline:</Text>
            </Paragraph>
            <ol>
              <li>Il Portal ID (Hub ID) si trova in Settings → Account Setup → Account Defaults</li>
              <li>Per trovare Pipeline e Stage IDs: Settings → Objects → Deals → Pipelines</li>
              <li>Gli IDs sono visibili nell'URL o usando l'API di HubSpot</li>
            </ol>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default CRMIntegration
