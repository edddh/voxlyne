import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table, Button, Space, Input, InputNumber, Modal, Form, message, Tag, Popconfirm, Typography, Tooltip, Switch, Card
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined, KeyOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as tenantsApi from '../api/tenants'

const { Title } = Typography

function Tenants() {
  const { t, i18n } = useTranslation()
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
      message.error(t('tenants.loadError'))
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
      message.error(t('tenants.loadPricingError'))
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
      message.success(t('tenants.pricingUpdated'))
    } catch (error) {
      message.error(error.response?.data?.detail || t('tenants.pricingUpdateError'))
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
        message.success(t('tenants.updated'))
      } else {
        await tenantsApi.createTenant(payload)
        message.success(t('tenants.created'))
      }
      setModalOpen(false)
      loadTenants()
    } catch (error) {
      const msg = error.response?.data?.detail || t('common.error')
      message.error(msg)
    }
  }

  const handleDelete = async (id) => {
    try {
      await tenantsApi.deleteTenant(id)
      message.success(t('tenants.deactivated'))
      loadTenants()
    } catch (error) {
      message.error(error.response?.data?.detail || t('common.error'))
    }
  }

  const columns = [
    {
      title: t('tenants.name'),
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
      title: t('tenantCredentials.status'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active) => (
        <Tag color={active ? 'green' : 'red'}>{active ? t('tenants.activeStatus') : t('tenants.inactiveStatus')}</Tag>
      ),
    },
    {
      title: t('nav.users'),
      dataIndex: 'user_count',
      key: 'users',
      align: 'center',
    },
    {
      title: t('nav.projects'),
      dataIndex: 'project_count',
      key: 'projects',
      align: 'center',
    },
    {
      title: t('tenants.package'),
      key: 'included_minutes',
      align: 'center',
      render: (_, record) => (
        record.settings?.included_minutes
          ? `${record.settings.included_minutes} min`
          : <Tag>{t('tenants.notConfigured')}</Tag>
      ),
    },
    {
      title: t('tenants.llmCostsToAdmins'),
      key: 'show_costs_to_tenant_admin',
      align: 'center',
      render: (_, record) => (
        record.settings?.show_costs_to_tenant_admin
          ? <Tag color="gold">{t('tenants.enabled')}</Tag>
          : <Tag>{t('tenants.disabled')}</Tag>
      ),
    },
    {
      title: t('tenants.createdColumn'),
      dataIndex: 'created_at',
      key: 'created',
      render: (date) => new Date(date).toLocaleDateString(i18n.language),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Tooltip title={t('common.edit')}>
            <Button icon={<EditOutlined />} size="small" onClick={() => openModal(record)} />
          </Tooltip>
          <Tooltip title={t('tenants.credentialsTooltip')}>
            <Button
              icon={<KeyOutlined />}
              size="small"
              onClick={() => navigate(`/tenants/${record.id}/credentials`)}
            />
          </Tooltip>
          {record.slug !== 'default' && (
            <Popconfirm
              title={t('tenants.confirmDeactivate')}
              description={t('tenants.confirmDeactivateDescription')}
              onConfirm={() => handleDelete(record.id)}
              okText={t('promptHistory.yes')}
              cancelText={t('promptHistory.no')}
            >
              <Tooltip title={t('tenants.deactivate')}>
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
        <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{t('nav.tenants')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
          {t('tenants.newTenant')}
        </Button>
      </div>

      <Input
        placeholder={t('tenants.searchPlaceholder')}
        prefix={<SearchOutlined />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ width: 250, marginBottom: 16 }}
        allowClear
      />

      <Card title={t('tenants.voicePricing')} style={{ marginBottom: 16 }}>
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
            {t('tenants.savePricing')}
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
          showTotal: (total_) => t('tenants.totalCount', { count: total_ }),
        }}
      />

      <Modal
        title={editingTenant ? t('tenants.editTenant') : t('tenants.newTenant')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label={t('tenants.name')}
            rules={[{ required: true, message: t('tenants.enterName') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="slug"
            label="Slug"
            rules={[
              { required: true, message: t('tenants.enterSlug') },
              { pattern: /^[a-z0-9-]+$/, message: t('tenants.slugPattern') },
            ]}
          >
            <Input disabled={!!editingTenant} placeholder="es: acme-corp" />
          </Form.Item>
          {editingTenant && (
            <Form.Item name="is_active" label={t('tenantCredentials.status')}>
              <select className="ant-select" style={{ width: '100%', padding: 8 }}>
                <option value={true}>{t('tenants.activeStatus')}</option>
                <option value={false}>{t('tenants.inactiveStatus')}</option>
              </select>
            </Form.Item>
          )}
          <Form.Item
            name="included_minutes"
            label={t('tenants.includedMinutes')}
            tooltip={t('tenants.includedMinutesTooltip')}
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder={t('tenants.includedMinutesPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="show_costs_to_tenant_admin"
            label={t('tenants.showLlmCosts')}
            valuePropName="checked"
            tooltip={t('tenants.showLlmCostsTooltip')}
          >
            <Switch />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {editingTenant ? t('common.save') : t('tenants.createButton')}
              </Button>
              <Button onClick={() => setModalOpen(false)}>{t('common.cancel')}</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Tenants
