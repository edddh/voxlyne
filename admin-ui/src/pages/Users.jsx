import { useState, useEffect } from 'react'
import {
  Table, Button, Space, Input, Select, Modal, Form, message, Tag, Popconfirm, Typography, Avatar, Tooltip
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, KeyOutlined, SearchOutlined
} from '@ant-design/icons'
import * as usersApi from '../api/users'
import { getTenants } from '../api/tenants'
import { useAuth } from '../hooks/useAuth'

const { Title } = Typography
const { Option } = Select

const roleColors = {
  super_admin: 'red',
  admin: 'purple',
  creator: 'blue',
  power_user: 'green',
  user: 'default',
}

const roleLabels = {
  super_admin: 'Super Admin',
  admin: 'Admin',
  creator: 'Creator',
  power_user: 'Power User',
  user: 'User',
}

function Users() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState(null)
  const [form] = Form.useForm()
  const [passwordForm] = Form.useForm()
  const [tenants, setTenants] = useState([])
  const { isSuperAdmin } = useAuth()

  useEffect(() => {
    loadUsers()
  }, [page, pageSize, search, roleFilter])

  useEffect(() => {
    // Il campo tenant nel modale serve solo al super_admin - un admin di
    // tenant crea sempre utenti nel proprio, il backend lo assegna da solo.
    if (isSuperAdmin) {
      getTenants({ page_size: 200 })
        .then((data) => setTenants(data.tenants || []))
        .catch(() => setTenants([]))
    }
  }, [isSuperAdmin])

  const loadUsers = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (search) params.search = search
      if (roleFilter) params.role = roleFilter
      const data = await usersApi.getUsers(params)
      setUsers(data.users)
      setTotal(data.total)
    } catch (error) {
      message.error('Errore caricamento utenti')
    } finally {
      setLoading(false)
    }
  }

  const openModal = (user = null) => {
    setEditingUser(user)
    form.resetFields()
    if (user) {
      form.setFieldsValue({
        email: user.email,
        full_name: user.full_name,
        role: user.role,
        is_active: user.is_active,
      })
    }
    setModalOpen(true)
  }

  const handleSubmit = async (values) => {
    try {
      if (editingUser) {
        await usersApi.updateUser(editingUser.id, values)
        message.success('Utente aggiornato')
      } else {
        await usersApi.createUser(values)
        message.success('Utente creato')
      }
      setModalOpen(false)
      loadUsers()
    } catch (error) {
      const msg = error.response?.data?.detail || 'Errore'
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await usersApi.deleteUser(id)
      message.success('Utente disattivato')
      loadUsers()
    } catch (error) {
      message.error('Errore disattivazione')
    }
  }

  const handleResetPassword = async (values) => {
    try {
      await usersApi.resetUserPassword(selectedUserId, values.new_password)
      message.success('Password reimpostata')
      setPasswordModalOpen(false)
      passwordForm.resetFields()
    } catch (error) {
      message.error('Errore reset password')
    }
  }

  const columns = [
    {
      title: 'Utente',
      key: 'user',
      render: (_, record) => (
        <Space>
          <Avatar style={{ backgroundColor: '#1890ff' }}>
            {record.full_name?.charAt(0) || record.email.charAt(0).toUpperCase()}
          </Avatar>
          <div>
            <div style={{ fontWeight: 500 }}>{record.full_name || record.email}</div>
            <div style={{ fontSize: 12, color: '#888' }}>{record.email}</div>
          </div>
        </Space>
      ),
    },
    {
      title: 'Ruolo',
      dataIndex: 'role',
      key: 'role',
      render: (role) => <Tag color={roleColors[role]}>{roleLabels[role]}</Tag>,
    },
    {
      title: 'Stato',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? 'Attivo' : 'Inattivo'}</Tag>
      ),
    },
    isSuperAdmin && {
      title: 'Tenant',
      dataIndex: 'tenant_name',
      key: 'tenant',
      render: (name) => name || '-',
    },
    {
      title: 'Ultimo Accesso',
      dataIndex: 'last_login_at',
      key: 'last_login',
      render: (date) => date ? new Date(date).toLocaleString('it-IT') : 'Mai',
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title="Modifica">
            <Button icon={<EditOutlined />} size="small" onClick={() => openModal(record)} />
          </Tooltip>
          <Tooltip title="Reset Password">
            <Button
              icon={<KeyOutlined />}
              size="small"
              onClick={() => {
                setSelectedUserId(record.id)
                setPasswordModalOpen(true)
              }}
            />
          </Tooltip>
          <Popconfirm
            title="Disattivare questo utente?"
            onConfirm={() => handleDelete(record.id)}
            okText="Sì"
            cancelText="No"
          >
            <Tooltip title="Disattiva">
              <Button icon={<DeleteOutlined />} size="small" danger />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ].filter(Boolean)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>Utenti</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
          Nuovo Utente
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Input
          placeholder="Cerca email o nome..."
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 250 }}
          allowClear
        />
        <Select
          placeholder="Filtra ruolo"
          value={roleFilter}
          onChange={setRoleFilter}
          style={{ width: 150 }}
          allowClear
        >
          {Object.entries(roleLabels).map(([key, label]) => (
            <Option key={key} value={key}>{label}</Option>
          ))}
        </Select>
      </Space>

      <Table
        scroll={{ x: 'max-content' }}
        dataSource={users}
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
          showTotal: (t) => `Totale: ${t} utenti`,
        }}
      />

      <Modal
        title={editingUser ? 'Modifica Utente' : 'Nuovo Utente'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="email"
            label="Email"
            rules={[
              { required: true, message: 'Inserisci email' },
              { type: 'email', message: 'Email non valida' },
            ]}
          >
            <Input disabled={!!editingUser} />
          </Form.Item>
          <Form.Item name="full_name" label="Nome Completo">
            <Input />
          </Form.Item>
          {!editingUser && (
            <Form.Item
              name="password"
              label="Password"
              rules={[
                { required: true, message: 'Inserisci password' },
                { min: 8, message: 'Minimo 8 caratteri' },
              ]}
            >
              <Input.Password />
            </Form.Item>
          )}
          {isSuperAdmin && !editingUser && (
            <Form.Item
              name="tenant_id"
              label="Tenant"
              rules={[{ required: true, message: 'Seleziona il tenant di questo utente' }]}
              tooltip="Senza tenant l'utente non appartiene a nessun cliente: non potrà vedere progetti, chiamate o altri utenti."
            >
              <Select
                placeholder="Seleziona tenant"
                showSearch
                optionFilterProp="children"
              >
                {tenants.map((t) => (
                  <Option key={t.id} value={t.id}>{t.name}</Option>
                ))}
              </Select>
            </Form.Item>
          )}
          <Form.Item
            name="role"
            label="Ruolo"
            rules={[{ required: true }]}
            initialValue="user"
          >
            <Select>
              {Object.entries(roleLabels).map(([key, label]) => (
                <Option key={key} value={key} disabled={key === 'super_admin' && !isSuperAdmin}>
                  {label}
                </Option>
              ))}
            </Select>
          </Form.Item>
          {editingUser && (
            <Form.Item name="is_active" label="Stato" valuePropName="checked">
              <Select>
                <Option value={true}>Attivo</Option>
                <Option value={false}>Inattivo</Option>
              </Select>
            </Form.Item>
          )}
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingUser ? 'Salva' : 'Crea'}
              </Button>
              <Button onClick={() => setModalOpen(false)}>Annulla</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Reset Password"
        open={passwordModalOpen}
        onCancel={() => {
          setPasswordModalOpen(false)
          passwordForm.resetFields()
        }}
        footer={null}
      >
        <Form form={passwordForm} layout="vertical" onFinish={handleResetPassword}>
          <Form.Item
            name="new_password"
            label="Nuova Password"
            rules={[
              { required: true, message: 'Inserisci password' },
              { min: 8, message: 'Minimo 8 caratteri' },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">Conferma</Button>
              <Button onClick={() => setPasswordModalOpen(false)}>Annulla</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Users
