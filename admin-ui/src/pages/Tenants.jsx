import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, InputNumber, Modal, Form, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, KeyOutlined } from '@ant-design/icons'
import * as tenantsApi from '../api/tenants'

const { Title } = Typography

function Tenants() {
  const navigate = useNavigate()
  const [tenants, setTenants] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingTenant, setEditingTenant] = useState(null)
  const [form] = Form.useForm()
  const [voicePricing, setVoicePricing] = useState({
    'grok-voice-latest': 0.08,
    'grok-voice-think-fast-2.0': 0.08,
    'grok-voice-think-fast-1.0': 0.05,
  })
  const [savingVoicePricing, setSavingVoicePricing] = useState(false)

  useEffect(() => {
    loadTenants()
  }, [page, pageSize, search])

  useEffect(() => {
    loadVoicePricing()
  }, [])

  const loadTenants = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (search) params.search = search
      const data = await tenantsApi.getTenants(params)
      setTenants(data.tenants)
      setTotal(data.total)
    } catch (error) {
      message.error('Errore caricamento tenant')
    } finally {
      setLoading(false)
    }
  }

  const loadVoicePricing = async () => {
    try {
      const data = await tenantsApi.getVoicePricingSettings()
      if (data?.pricing_per_minute) {
        setVoicePricing(data.pricing_per_minute)
      }
    } catch (error) {
      message.error('Errore caricamento tariffario voce')
    }
  }

  const handleSaveVoicePricing = async () => {
    setSavingVoicePricing(true)
    try {
      const data = await tenantsApi.updateVoicePricingSettings({
        pricing_per_minute: voicePricing,
      })
      if (data?.pricing_per_minute) {
        setVoicePricing(data.pricing_per_minute)
      }
      message.success('Tariffario voce aggiornato')
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore aggiornamento tariffario voce')
    } finally {
      setSavingVoicePricing(false)
    }
  }

  const openModal = (tenant = null) => {
    setEditingTenant(tenant)
    form.resetFields()
    if (tenant) {
      form.setFieldsValue({
        name: tenant.name,
        slug: tenant.slug,
        is_active: tenant.is_active,
        included_minutes: tenant.settings?.included_minutes ?? null,
        show_costs_to_tenant_admin: tenant.settings?.show_costs_to_tenant_admin ?? false,
      })
    }
    setModalOpen(true)
  }

  const handleSubmit = async (values) => {
    try {
      // maintainer, 20/08: "gli utenti del tenant devono vedere quanto del
      // pacchetto hanno utilizzato" - il pacchetto (minuti inclusi) si
      // configura qui. tenants.settings e' un JSONB sostituito per
      // intero dal backend (non un merge, vedi app/routers/tenants.py::
      // update_tenant), quindi bisogna rimandare indietro TUTTO
      // l'oggetto esistente con solo included_minutes cambiato, non solo
      // il campo nuovo - altrimenti si perdono max_users/max_projects
      // gia' salvati.
      const { included_minutes, show_costs_to_tenant_admin, ...rest } = values
      const settings = {
        ...(editingTenant?.settings || {}),
        included_minutes: included_minutes ?? null,
        show_costs_to_tenant_admin: !!show_costs_to_tenant_admin,
      }
      const payload = { ...rest, settings }

      if (editingTenant) {
        await tenantsApi.updateTenant(editingTenant.id, payload)
        message.success('Tenant aggiornato')
      } else {
        await tenantsApi.createTenant(payload)
        message.success('Tenant creato')
      }
      setModalOpen(false)
      loadTenants()
    } catch (error) {
      const msg = error.response?.data?.detail || 'Errore'
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await tenantsApi.deleteTenant(id)
      message.success('Tenant disattivato')
      loadTenants()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore')
    }
  }

  const columns = [
    {
      title: 'Nome',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: 'Slug',
      dataIndex: 'slug',
      key: 'slug',
      render: (slug) => <code>{slug}</code>,
    },
    {
      title: 'Stato',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? 'Attivo' : 'Inattivo'}</Tag>
      ),
    },
    {
      title: 'Utenti',
      dataIndex: 'user_count',
      key: 'users',
      align: 'center',
    },
    {
      title: 'Progetti',
      dataIndex: 'project_count',
      key: 'projects',
      align: 'center',
    },
    {
      title: 'Pacchetto',
      key: 'included_minutes',
      align: 'center',
      render: (_, record) => (
        record.settings?.included_minutes
          ? `${record.settings.included_minutes} min`
          : <Tag>Non configurato</Tag>
      ),
    },
    {
      title: 'Costi LLM agli admin',
      key: 'show_costs_to_tenant_admin',
      align: 'center',
      render: (_, record) => (
        record.settings?.show_costs_to_tenant_admin
          ? <Tag color="gold">Abilitati</Tag>
          : <Tag>Disabilitati</Tag>
      ),
    },
    {
      title: 'Creato',
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => new Date(date).toLocaleDateString('it-IT'),
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title="Modifica">
            <Button icon={<EditOutlined />} size="small" onClick={() => openModal(record)} />
          </Tooltip>
          <Tooltip title="Credenziali (API key LLM/voce/telefonia per questo tenant)">
            <Button
              icon={<KeyOutlined />}
              size="small"
              onClick={() => navigate(`/tenants/${record.id}/credentials`)}
            />
          </Tooltip>
          {record.slug !== 'default' && (
            <Popconfirm
              title="Disattivare questo tenant?"
              description="Tutti gli utenti e progetti verranno disattivati."
              onConfirm={() => handleDelete(record.id)}
              okText="Sì"
              cancelText="No"
            >
              <Tooltip title="Disattiva">
                <Button icon={<DeleteOutlined />} size="small" danger />
              </Tooltip>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>Tenant</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
          Nuovo Tenant
        </Button>
      </div>

      <Input
        placeholder="Cerca tenant..."
        prefix={<SearchOutlined />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ width: 250, marginBottom: 16 }}
        allowClear
      />

      <Card title="Tariffario voce xAI" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap>
            <span>grok-voice-latest</span>
            <InputNumber
              min={0}
              step={0.01}
              precision={4}
              value={voicePricing['grok-voice-latest']}
              onChange={(value) => setVoicePricing((prev) => ({ ...prev, 'grok-voice-latest': value ?? 0 }))}
            />
            <span>USD/min</span>
          </Space>
          <Space wrap>
            <span>grok-voice-think-fast-2.0</span>
            <InputNumber
              min={0}
              step={0.01}
              precision={4}
              value={voicePricing['grok-voice-think-fast-2.0']}
              onChange={(value) => setVoicePricing((prev) => ({ ...prev, 'grok-voice-think-fast-2.0': value ?? 0 }))}
            />
            <span>USD/min</span>
          </Space>
          <Space wrap>
            <span>grok-voice-think-fast-1.0</span>
            <InputNumber
              min={0}
              step={0.01}
              precision={4}
              value={voicePricing['grok-voice-think-fast-1.0']}
              onChange={(value) => setVoicePricing((prev) => ({ ...prev, 'grok-voice-think-fast-1.0': value ?? 0 }))}
            />
            <span>USD/min</span>
          </Space>
          <Button type="primary" onClick={handleSaveVoicePricing} loading={savingVoicePricing}>
            Salva tariffario e ricalcola costi
          </Button>
        </Space>
      </Card>

      <Table
        scroll={{ x: 'max-content' }}
        dataSource={tenants}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
          showSizeChanger: true,
          showTotal: (t) => `Totale: ${t} tenant`,
        }}
      />

      <Modal
        title={editingTenant ? 'Modifica Tenant' : 'Nuovo Tenant'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label="Nome"
            rules={[{ required: true, message: 'Inserisci nome' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="slug"
            label="Slug"
            rules={[
              { required: true, message: 'Inserisci slug' },
              { pattern: /^[a-z0-9-]+$/, message: 'Solo lettere minuscole, numeri e trattini' },
            ]}
          >
            <Input disabled={!!editingTenant} placeholder="es: acme-corp" />
          </Form.Item>
          {editingTenant && (
            <Form.Item name="is_active" label="Stato">
              <select className="ant-select" style={{ width: '100%', padding: 8 }}>
                <option value={true}>Attivo</option>
                <option value={false}>Inattivo</option>
              </select>
            </Form.Item>
          )}
          <Form.Item
            name="included_minutes"
            label="Minuti inclusi nel pacchetto"
            tooltip="Quanti minuti di chiamata sono inclusi per questo tenant - gli utenti del tenant vedono quanto ne hanno usato in percentuale (pagina Chiamate). Lascia vuoto per nessun limite configurato."
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="Es. 500 (vuoto = nessun limite configurato)" />
          </Form.Item>
          <Form.Item
            name="show_costs_to_tenant_admin"
            label="Mostra costi LLM agli admin del tenant"
            valuePropName="checked"
            tooltip="Se attivo, gli utenti con ruolo admin di questo tenant vedono i costi reali delle chiamate nella pagina Chiamate. Creators e power users non li vedono."
          >
            <Switch />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingTenant ? 'Salva' : 'Crea'}
              </Button>
              <Button onClick={() => setModalOpen(false)}>Annulla</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Tenants
