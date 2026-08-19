import { useState, useEffect } from 'react'
import {
  Table, Button, Space, Modal, Form, Input, Select, message, Tag, Popconfirm, Typography, Card, Divider, Checkbox
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, TeamOutlined, CheckOutlined } from '@ant-design/icons'
import * as templatesApi from '../api/templates'
import * as tenantsApi from '../api/tenants'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * Templates Page - Super Admin Only
 * Manage global templates and assign them to tenants
 */
function Templates() {
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
      message.error('Failed to load templates: ' + error.message)
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
    })
    setModalOpen(true)
  }

  const handleDelete = async (templateId) => {
    message.warning('Delete template feature coming soon')
    // TODO: Implement delete when needed
    // await templatesApi.deleteTemplate(templateId)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()

      if (editingTemplate) {
        await templatesApi.updateTemplate(editingTemplate.id, values)
        message.success('Template updated successfully')
      } else {
        await templatesApi.createTemplate(values)
        message.success('Template created successfully')
      }

      setModalOpen(false)
      loadTemplates()
    } catch (error) {
      if (error.errorFields) return // Validation error
      message.error('Failed to save template: ' + error.message)
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
      message.success(`Template assigned to ${selectedTenants.length} tenant(s)`)
      setAssignModalOpen(false)
    } catch (error) {
      message.error('Failed to assign template: ' + error.message)
    }
  }

  const columns = [
    {
      title: 'Name',
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
      title: 'Category',
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
      title: 'Type',
      dataIndex: 'type',
      key: 'type',
      render: (type) => <Tag>{type}</Tag>,
    },
    {
      title: 'Language',
      dataIndex: 'language',
      key: 'language',
      render: (lang) => {
        const langMap = { it: '🇮🇹 Italian', en: '🇬🇧 English', de: '🇩🇪 German' }
        return langMap[lang] || lang
      },
    },
    {
      title: 'Active',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (isActive) => (
        isActive ? <Tag color="success" icon={<CheckOutlined />}>Active</Tag> : <Tag>Inactive</Tag>
      ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date) => new Date(date).toLocaleDateString(),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            icon={<TeamOutlined />}
            onClick={() => handleAssign(record)}
          >
            Assign
          </Button>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          />
          <Popconfirm
            title="Delete this template?"
            description="This will also remove all tenant assignments."
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
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
          <Title level={2} style={{ margin: 0, flexShrink: 0 }}>Templates</Title>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
          >
            New Template
          </Button>
        </div>

        <Text type="secondary">
          Global templates that can be assigned to tenants. Tenants create live projects from assigned templates.
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
        title={editingTemplate ? 'Edit Template' : 'New Template'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        width={800}
        okText="Save"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="Template Name"
            rules={[{ required: true, message: 'Please enter template name' }]}
          >
            <Input placeholder="e.g., Demo Organization Recruiting Template" />
          </Form.Item>

          <Form.Item
            name="slug"
            label="Slug"
            rules={[{ required: true, message: 'Please enter slug' }]}
            tooltip="URL-friendly identifier (lowercase, no spaces)"
          >
            <Input placeholder="e.g., demo-organization-recruiting" />
          </Form.Item>

          <Space style={{ width: '100%' }} size="large">
            <Form.Item
              name="type"
              label="Type"
              rules={[{ required: true }]}
              style={{ width: 200 }}
            >
              <Select>
                <Select.Option value="interview">Interview</Select.Option>
                <Select.Option value="survey">Survey</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="template_category"
              label="Category"
              rules={[{ required: true }]}
              style={{ width: 200 }}
            >
              <Select>
                <Select.Option value="recruiting">Recruiting</Select.Option>
                <Select.Option value="sales">Sales</Select.Option>
                <Select.Option value="support">Support</Select.Option>
                <Select.Option value="survey">Survey</Select.Option>
                <Select.Option value="other">Other</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="language"
              label="Language"
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

          <Form.Item name="description" label="Description">
            <TextArea rows={2} placeholder="Brief description of this template" />
          </Form.Item>

          <Form.Item
            name="prompt_a"
            label="Main Prompt (Instructions)"
            rules={[{ required: true }]}
            tooltip="Use placeholders: {{cancel_phrase}}, {{goodbye_phrase}}"
          >
            <TextArea rows={6} placeholder="AI instructions for conversation flow..." />
          </Form.Item>

          <Form.Item
            name="prompt_b"
            label="Extraction Prompt"
            tooltip="Instructions for extracting structured data from conversation"
          >
            <TextArea rows={4} placeholder="Extract the following fields..." />
          </Form.Item>

          <Form.Item name="consent_message" label="Consent Message">
            <TextArea rows={2} placeholder="GDPR consent message (optional)" />
          </Form.Item>

          <Form.Item name="voice_name" label="Voice Name (OpenAI)">
            <Select placeholder="Select voice">
              <Select.Option value="alloy">Alloy</Select.Option>
              <Select.Option value="echo">Echo</Select.Option>
              <Select.Option value="shimmer">Shimmer</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* Assign to Tenants Modal */}
      <Modal
        title={`Assign Template: ${selectedTemplate?.name}`}
        open={assignModalOpen}
        onOk={handleAssignSubmit}
        onCancel={() => setAssignModalOpen(false)}
        okText="Assign"
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          Select tenants that should have access to this template
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
