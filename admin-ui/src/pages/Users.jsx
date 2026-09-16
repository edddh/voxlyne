import { useState, useEffect } from 'react'
import {
  Table, Button, Space, Input, Select, Modal, Form, message, Tag, Popconfirm, Typography, Avatar, Tooltip
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, KeyOutlined, SearchOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
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

function Users() {
  const { t, i18n } = useTranslation()
  const roleLabels = {
    super_admin: t('roles.super_admin'),
    admin: t('roles.admin'),
    creator: t('roles.creator'),
    power_user: t('roles.power_user'),
    user: t('roles.user'),
  }
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
      // Il backend limita la paginazione dei tenant a 100 elementi.
      getTenants({ page_size: 100 })
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
      message.error(t('users.loadError'))
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
        message.success(t('users.updated'))
      } else {
        await usersApi.createUser(values)
        message.success(t('users.created'))
      }
      setModalOpen(false)
      loadUsers()
    } catch (error) {
      const msg = error.response?.data?.detail || t('common.error')
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await usersApi.deleteUser(id)
      message.success(t('users.deactivated'))
      loadUsers()
    } catch (error) {
      message.error(t('users.deactivateError'))
    }
  }

  const handleResetPassword = async (values) => {
    try {
      await usersApi.resetUserPassword(selectedUserId, values.new_password)
      message.success(t('users.passwordReset'))
      setPasswordModalOpen(false)
      passwordForm.resetFields()
    } catch (error) {
      message.error(t('users.passwordResetError'))
    }
  }

  const columns = [
    {
      title: t('users.userColumn'),
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
      title: t('users.role'),
      dataIndex: 'role',
      key: 'role',
      render: (role) => <Tag color={roleColors[role]}>{roleLabels[role]}</Tag>,
    },
    {
      title: t('tenantCredentials.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? t('tenants.activeStatus') : t('tenants.inactiveStatus')}</Tag>
      ),
    },
    isSuperAdmin && {
      title: 'Tenant',
      dataIndex: 'tenant_name',
      key: 'tenant',
      render: (name) => name || '-',
    },
    {
      title: t('users.lastLogin'),
      dataIndex: 'last_login_at',
      key: 'last_login',
      render: (date) => date ? new Date(date).toLocaleString(i18n.language) : t('crm.never'),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title={t('common.edit')}>
            <Button icon={<EditOutlined />} size="small" onClick={() => openModal(record)} />
          </Tooltip>
          <Tooltip title={t('users.resetPassword')}>
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
            title={t('users.confirmDeactivate')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('promptHistory.yes')}
            cancelText={t('promptHistory.no')}
          >
            <Tooltip title={t('tenants.deactivate')}>
              <Button icon={<DeleteOutlined />} size="small" danger />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ].filter(Boolean)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{t('nav.users')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
          {t('users.newUser')}
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Input
          placeholder={t('users.searchPlaceholder')}
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 250 }}
          allowClear
        />
        <Select
          placeholder={t('users.filterRole')}
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
          showTotal: (total_) => t('users.totalCount', { count: total_ }),
        }}
      />

      <Modal
        title={editingUser ? t('users.editUser') : t('users.newUser')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="email"
            label="Email"
            rules={[
              { required: true, message: t('login.enterEmail') },
              { type: 'email', message: t('login.invalidEmail') },
            ]}
          >
            <Input disabled={!!editingUser} />
          </Form.Item>
          <Form.Item name="full_name" label={t('users.fullName')}>
            <Input />
          </Form.Item>
          {!editingUser && (
            <Form.Item
              name="password"
              label="Password"
              rules={[
                { required: true, message: t('login.enterPassword') },
                { min: 8, message: t('users.min8chars') },
              ]}
            >
              <Input.Password />
            </Form.Item>
          )}
          {isSuperAdmin && !editingUser && (
            <Form.Item
              name="tenant_id"
              label="Tenant"
              rules={[{ required: true, message: t('users.selectTenant') }]}
              tooltip={t('users.tenantTooltip')}
            >
              <Select
                placeholder={t('users.selectTenantPlaceholder')}
                showSearch
                optionFilterProp="children"
              >
                {tenants.map((tn) => (
                  <Option key={tn.id} value={tn.id}>{tn.name}</Option>
                ))}
              </Select>
            </Form.Item>
          )}
          <Form.Item
            name="role"
            label={t('users.role')}
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
            <Form.Item name="is_active" label={t('tenantCredentials.status')} valuePropName="checked">
              <Select>
                <Option value={true}>{t('tenants.activeStatus')}</Option>
                <Option value={false}>{t('tenants.inactiveStatus')}</Option>
              </Select>
            </Form.Item>
          )}
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingUser ? t('common.save') : t('tenants.createButton')}
              </Button>
              <Button onClick={() => setModalOpen(false)}>{t('common.cancel')}</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('users.resetPassword')}
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
            label={t('users.newPassword')}
            rules={[
              { required: true, message: t('login.enterPassword') },
              { min: 8, message: t('users.min8chars') },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">{t('users.confirm')}</Button>
              <Button onClick={() => setPasswordModalOpen(false)}>{t('common.cancel')}</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Users
