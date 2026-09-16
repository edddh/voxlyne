import { useState, useEffect } from 'react'
import {
  Table, Button, Space, Modal, Form, Input, Select, message, Tag, Popconfirm, Typography, Card, Divider, Checkbox
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, TeamOutlined, CheckOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import * as templatesApi from '../api/templates'
import * as tenantsApi from '../api/tenants'
import { BRAND } from '../main'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * Templates Page - Super Admin Only
 * Manage global templates and assign them to tenants
 */
function Templates() {
  const { t, i18n } = useTranslation()
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [assignModalOpen, setAssignModalOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState(null)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [tenants, setTenants] = useState([])
  const [selectedTenants, setSelectedTenants] = useState([])
  const [form] = Form.useForm()

  useEffect(() => {
    loadTemplates()
    loadTenants()
  }, [])

  const loadTemplates = async () => {
    setLoading(true)
    try {
      const data = await templatesApi.listTemplates()
      setTemplates(data.templates || [])
    } catch (error) {
      message.error(t('templates.loadError') + ': ' + error.message)
    } finally {
      setLoading(false)
    }
  }

  const loadTenants = async () => {
    try {
      const data = await tenantsApi.getTenants()
      setTenants(data.tenants || data || [])
    } catch (error) {
      console.error('Failed to load tenants:', error)
    }
  }

  const handleCreate = () => {
    setEditingTemplate(null)
    form.resetFields()
    setModalOpen(true)
  }

  const handleEdit = (template) => {
    setEditingTemplate(template)
    form.setFieldsValue({
      name: template.name,
      slug: template.slug,
      type: template.type,
      template_category: template.template_category,
      description: template.description,
      prompt_a: template.prompt_a,
      prompt_b: template.prompt_b,
      consent_message: template.consent_message,
      voice_name: template.voice_name,
      language: template.language,
      // {{key}} custom variables - maintainer, 20/08: "il template dovrebbe
      // avere dei campi custom che chiede di riempire quando si
      // effettua l'importazione". custom_variables_schema defines the
      // fields, "default" here doubles as the template's own example
      // value (custom_variables on the template row).
      custom_variables_schema: (template.custom_variables_schema || []).map((f) => ({
        ...f,
        default: template.custom_variables?.[f.key] ?? f.default ?? '',
      })),
    })
    setModalOpen(true)
  }

  const handleDelete = async (templateId) => {
    message.warning(t('templates.deleteComingSoon'))
    // TODO: Implement delete when needed
    // await templatesApi.deleteTemplate(templateId)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()

      // Il form tiene "default" come singolo campo modificabile per
      // ogni variabile (raddoppia da "valore di default per i nuovi
      // progetti" a "valore di esempio del template stesso") - il
      // backend li vuole separati: custom_variables_schema (la
      // definizione dei campi) e custom_variables (i valori di QUESTO
      // template, projects.custom_variables).
      const schema = values.custom_variables_schema || []
      values.custom_variables = Object.fromEntries(
        schema.filter((f) => f?.key).map((f) => [f.key, f.default || ''])
      )
      values.custom_variables_schema = schema.filter((f) => f?.key)

      if (editingTemplate) {
        await templatesApi.updateTemplate(editingTemplate.id, values)
        message.success(t('templates.updated'))
      } else {
        await templatesApi.createTemplate(values)
        message.success(t('templates.created'))
      }

      setModalOpen(false)
      loadTemplates()
    } catch (error) {
      if (error.errorFields) return // Validation error
      message.error(t('templates.saveError') + ': ' + error.message)
    }
  }

  const handleAssign = async (template) => {
    setSelectedTemplate(template)
    try {
      const { assignments } = await templatesApi.getAssignments(template.id)
      setSelectedTenants(assignments.map(a => a.tenant_id))
    } catch (error) {
      console.error('Failed to load assignments:', error)
      setSelectedTenants([])
    }
    setAssignModalOpen(true)
  }

  const handleAssignSubmit = async () => {
    try {
      await templatesApi.assignToTenants(selectedTemplate.id, selectedTenants)
      message.success(t('templates.assignedTo', { count: selectedTenants.length }))
      setAssignModalOpen(false)
    } catch (error) {
      message.error(t('templates.assignError') + ': ' + error.message)
    }
  }

  const columns = [
    {
      title: t('templates.name'),
      dataIndex: 'name',
      key: 'name',
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{text}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{record.slug}</Text>
        </Space>
      ),
    },
    {
      title: t('templates.category'),
      dataIndex: 'template_category',
      key: 'template_category',
      render: (category) => {
        const colorMap = {
          recruiting: 'blue',
          sales: 'green',
          support: 'orange',
          survey: 'purple',
          other: 'default',
        }
        return <Tag color={colorMap[category] || 'default'}>{category}</Tag>
      },
    },
    {
      title: t('templates.type'),
      dataIndex: 'type',
      key: 'type',
      render: (type) => <Tag>{type}</Tag>,
    },
    {
      title: t('templates.language'),
      dataIndex: 'language',
      key: 'language',
      render: (lang) => {
        const langMap = { it: '🇮🇹 Italian', en: '🇬🇧 English', de: '🇩🇪 German' }
        return langMap[lang] || lang
      },
    },
    {
      title: t('templates.active'),
      dataIndex: 'is_active',
      key: 'is_active',
      render: (isActive) => (
        isActive ? <Tag color="success" icon={<CheckOutlined />}>{t('templates.activeTag')}</Tag> : <Tag>{t('templates.inactiveTag')}</Tag>
      ),
    },
    {
      title: t('tenants.createdColumn'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => new Date(date).toLocaleDateString(i18n.language),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            icon={<TeamOutlined />}
            onClick={() => handleAssign(record)}
          >
            {t('templates.assign')}
          </Button>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          />
          <Popconfirm
            title={t('templates.confirmDelete')}
            description={t('templates.confirmDeleteDescription')}
            onConfirm={() => handleDelete(record.id)}
            okText={t('common.delete')}
            okType="danger"
          >
            <Button type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <Title level={2} style={{ margin: 0, flexShrink: 0 }}>{t('nav.templates')}</Title>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
          >
            {t('templates.newTemplate')}
          </Button>
        </div>

        <Text type="secondary">
          {t('templates.pageDescription')}
        </Text>

        <Divider />

        <Table
          scroll={{ x: 'max-content' }}
          columns={columns}
          dataSource={templates}
          rowKey="id"
          loading={loading}
          pagination={false}
        />
      </Card>

      {/* Create/Edit Modal */}
      <Modal
        title={editingTemplate ? t('templates.editTemplate') : t('templates.newTemplate')}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={800}
        okText={t('common.save')}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={t('templates.templateName')}
            rules={[{ required: true, message: t('templates.enterTemplateName') }]}
          >
            <Input placeholder={t('templates.templateNamePlaceholder')} />
          </Form.Item>

          <Form.Item
            name="slug"
            label="Slug"
            rules={[{ required: true, message: t('tenants.enterSlug') }]}
            tooltip={t('templates.slugTooltip')}
          >
            <Input placeholder="e.g., customer-support" />
          </Form.Item>

          <Space style={{ width: '100%' }} size="large">
            <Form.Item
              name="type"
              label={t('templates.type')}
              rules={[{ required: true }]}
              style={{ width: 200 }}
            >
              {/* Deve rispecchiare esattamente ProjectType (app/models/
                  schemas.py) - il backend valida "type" contro
                  quell'enum. "interview" non ne fa parte: prima di
                  questa correzione, creare un template con questo valore
                  avrebbe fallito con un 422 alla submit. */}
              <Select>
                <Select.Option value="recruiting">Recruiting</Select.Option>
                <Select.Option value="lead_gen">Lead Gen</Select.Option>
                <Select.Option value="support">Support</Select.Option>
                <Select.Option value="survey">Survey</Select.Option>
                <Select.Option value="other">{t('templates.other')}</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="template_category"
              label={t('templates.category')}
              rules={[{ required: true }]}
              style={{ width: 200 }}
            >
              <Select>
                <Select.Option value="recruiting">Recruiting</Select.Option>
                <Select.Option value="sales">Sales</Select.Option>
                <Select.Option value="support">Support</Select.Option>
                <Select.Option value="survey">Survey</Select.Option>
                <Select.Option value="other">{t('templates.other')}</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="language"
              label={t('templates.language')}
              rules={[{ required: true }]}
              style={{ width: 150 }}
            >
              <Select>
                <Select.Option value="it">🇮🇹 Italian</Select.Option>
                <Select.Option value="en">🇬🇧 English</Select.Option>
                <Select.Option value="de">🇩🇪 German</Select.Option>
              </Select>
            </Form.Item>
          </Space>

          <Form.Item name="description" label={t('templates.description')}>
            <TextArea rows={2} placeholder={t('templates.descriptionPlaceholder')} />
          </Form.Item>

          <Form.Item
            name="prompt_a"
            label={t('templates.mainPrompt')}
            rules={[{ required: true }]}
            tooltip={t('templates.mainPromptTooltip', { interpolation: { prefix: '{%', suffix: '%}' } })}
          >
            <TextArea rows={6} placeholder={t('templates.mainPromptPlaceholder')} />
          </Form.Item>

          <Form.Item
            name="prompt_b"
            label={t('templates.extractionPrompt')}
            tooltip={t('templates.extractionPromptTooltip')}
          >
            <TextArea rows={4} placeholder={t('templates.extractionPromptPlaceholder')} />
          </Form.Item>

          <Form.Item name="consent_message" label={t('templates.consentMessage')}>
            <TextArea rows={2} placeholder={t('templates.consentMessagePlaceholder')} />
          </Form.Item>

          <Form.Item name="voice_name" label={t('templates.voiceName')}>
            <Select placeholder={t('templates.selectVoice')}>
              <Select.Option value="alloy">Alloy</Select.Option>
              <Select.Option value="echo">Echo</Select.Option>
              <Select.Option value="shimmer">Shimmer</Select.Option>
            </Select>
          </Form.Item>

          <Divider orientation="left" orientationMargin={0}>
            {t('templates.customVariables')} ({'{{key}}'} tags)
          </Divider>
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            {t('templates.customVariablesDescription', { interpolation: { prefix: '{%', suffix: '%}' } })}
          </Text>
          <Form.List name="custom_variables_schema">
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Card
                    key={key}
                    size="small"
                    // Era #fafafa (chiaro) su un'app sempre in tema scuro
                    // (main.jsx::BRAND, darkAlgorithm) - testo bianco del
                    // tema su sfondo chiaro, illeggibile. maintainer: "togli
                    // sfondo bianco e metti uno sfondo grigio scuro, usa
                    // scritte bianche e arancioni" - stessi token del
                    // resto dell'app, non un colore a caso.
                    style={{ marginBottom: 12, background: BRAND.bgElevated, borderColor: BRAND.border }}
                    // title = identita' (il tag {{key}}, scorribile a
                    // colpo d'occhio riga per riga), extra = azione (solo
                    // il cestino) - stessa convenzione gia' usata nel
                    // resto dell'app, invece di stipare la descrizione
                    // nell'header in competizione con l'icona.
                    title={
                      <Space size={4} align="center">
                        <Text style={{ fontFamily: 'monospace', fontSize: 15, color: BRAND.orange, fontWeight: 'bold' }}>{'{{'}</Text>
                        <Form.Item
                          {...restField}
                          name={[name, 'key']}
                          rules={[
                            { required: true, message: t('templates.required') },
                            { pattern: /^[a-zA-Z0-9_-]+$/, message: t('templates.keyPattern') },
                          ]}
                          style={{ marginBottom: 0 }}
                        >
                          <Input
                            placeholder="comune"
                            style={{ width: 160, fontFamily: 'monospace', color: BRAND.white }}
                          />
                        </Form.Item>
                        <Text style={{ fontFamily: 'monospace', fontSize: 15, color: BRAND.orange, fontWeight: 'bold' }}>{'}}'}</Text>
                      </Space>
                    }
                    extra={
                      <DeleteOutlined onClick={() => remove(name)} style={{ color: '#ff4d4f' }} />
                    }
                  >
                    <Space style={{ width: '100%', display: 'flex' }} wrap>
                      <Form.Item
                        {...restField}
                        name={[name, 'label']}
                        label={t('templates.label')}
                        rules={[{ required: true, message: t('templates.requiredFem') }]}
                        style={{ flex: 1, minWidth: 220, marginBottom: 8 }}
                      >
                        <Input placeholder={t('templates.labelPlaceholder')} />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'default']}
                        label={t('templates.defaultValue')}
                        style={{ flex: 1, minWidth: 220, marginBottom: 8 }}
                      >
                        <Input placeholder={t('templates.defaultValuePlaceholder')} />
                      </Form.Item>
                    </Space>

                    <Form.Item
                      {...restField}
                      name={[name, 'description']}
                      label={t('templates.description')}
                      style={{ marginBottom: 0 }}
                    >
                      <TextArea
                        rows={2}
                        placeholder={t('templates.variableDescriptionPlaceholder')}
                      />
                    </Form.Item>
                  </Card>
                ))}
                <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} block>
                  {t('templates.addVariable')}
                </Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>

      {/* Assign to Tenants Modal */}
      <Modal
        title={`${t('templates.assignTemplate')}: ${selectedTemplate?.name}`}
        open={assignModalOpen}
        onOk={handleAssignSubmit}
        onCancel={() => setAssignModalOpen(false)}
        okText={t('templates.assign')}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {t('templates.selectTenantsDescription')}
        </Text>
        <Checkbox.Group
          value={selectedTenants}
          onChange={setSelectedTenants}
          style={{ width: '100%' }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {tenants.map(tenant => (
              <Checkbox key={tenant.id} value={tenant.id}>
                <Space>
                  <Text strong>{tenant.name}</Text>
                  <Text type="secondary">({tenant.company_name})</Text>
                </Space>
              </Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
      </Modal>
    </div>
  )
}

export default Templates
