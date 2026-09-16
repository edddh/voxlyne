import { useState, useEffect } from 'react'
import { Form, Switch, Select, Button, Alert, Space, message, Spin } from 'antd'
import { useTranslation } from 'react-i18next'
import * as projectsApi from '../api/projects'

/**
 * Controls output_config.pdf on the project (app/services/pdf_generator.py,
 * app/services/call_manager.py) - whether a PDF report is generated after
 * each call, and which template. maintainer (18/08): "assolutamente il
 * template dipende dal progetto e il progetto Exampleville non richiede
 * generazione del pdf. come tutto deve essere attivabile e configurabile".
 *
 * The schema (output_config.pdf = {enabled, template}) already existed in
 * ProjectCreate's default_factory - this is the UI for a config surface
 * that was silently unused until now, not a new field.
 */
function PdfEmailTab({ projectId }) {
  const { t } = useTranslation()
  const TEMPLATE_OPTIONS = [
    { value: 'candidate', label: t('pdfEmailTab.candidateTemplate') },
    { value: 'generic', label: t('pdfEmailTab.genericTemplate') },
  ]
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [pdfEnabled, setPdfEnabled] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const project = await projectsApi.getProject(projectId)
        const pdfCfg = project.output_config?.pdf || {}
        const enabled = pdfCfg.enabled !== false // default true, same as backend
        setPdfEnabled(enabled)
        form.setFieldsValue({
          pdf_enabled: enabled,
          pdf_template: pdfCfg.template || 'candidate',
        })
      } catch (error) {
        message.error(t('pdfEmailTab.loadError'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [projectId, form])

  const handleSave = async (values) => {
    setSaving(true)
    try {
      const project = await projectsApi.getProject(projectId)
      const output_config = {
        ...(project.output_config || {}),
        pdf: { enabled: values.pdf_enabled, template: values.pdf_template },
      }
      await projectsApi.updateProject(projectId, { output_config })
      message.success(t('crm.saved'))
    } catch (error) {
      message.error(error.response?.data?.detail || t('projectConfig.sipSaveError'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spin />

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message={t('pdfEmailTab.title')}
        description={t('pdfEmailTab.description')}
      />

      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Form.Item name="pdf_enabled" label={t('pdfEmailTab.generatePdf')} valuePropName="checked">
          <Switch onChange={setPdfEnabled} />
        </Form.Item>

        <Form.Item
          name="pdf_template"
          label={t('pdfEmailTab.pdfTemplate')}
          tooltip={t('pdfEmailTab.templateTooltip')}
        >
          <Select options={TEMPLATE_OPTIONS} disabled={!pdfEnabled} style={{ maxWidth: 420 }} />
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={saving}>
          {t('common.save')}
        </Button>
      </Form>
    </Space>
  )
}

export default PdfEmailTab
