import { useState, useEffect } from 'react'
import {
  Table, Button, Space, Input, Modal, Form, message, Tag, Popconfirm, Typography, Tooltip
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined } from '@ant-design/icons'
import * as tenantsApi from '../api/tenants'

const { Title } = Typography

function Tenants() {
  const [tenants, setTenants] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingTenant, setEditingTenant] = useState(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadTenants()
  }, [page, pageSize, search])

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

  const openModal = (tenant = null) => {
    setEditingTenant(tenant)
    form.resetFields()
    if (tenant) {
      form.setFieldsValue({
        name: tenant.name,
        slug: tenant.slug,
        is_active: tenant.is_active,
      })
    }
    setModalOpen(true)
  }

  const handleSubmit = async (values) => {
    try {
      if (editingTenant) {
        await tenantsApi.updateTenant(editingTenant.id, values)
        message.success('Tenant aggiornato')
      } else {
        await tenantsApi.createTenant(values)
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
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>Tenant</Title>
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

      <Table
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
