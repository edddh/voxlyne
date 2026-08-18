import { useState, useEffect } from 'react'
import { Form, Switch, Select, Button, Alert, Space, message, Spin } from 'antd'
import * as projectsApi from '../api/projects'

const TEMPLATE_OPTIONS = [
  { value: 'candidate', label: 'Scheda candidato (colloquio/recruiting)' },
  { value: 'generic', label: 'Generico (qualsiasi progetto)' },
]

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
        message.error('Errore nel caricamento della configurazione')
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
      message.success('Configurazione salvata')
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nel salvataggio')
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
        message="Report PDF ed email dopo la chiamata"
        description="Dopo ogni chiamata completata, Ascolta puo' generare automaticamente un report PDF dai dati estratti (e inviarlo via email, se la posta e' configurata a livello di sistema). Disattivalo per i progetti che non ne hanno bisogno."
      />

      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Form.Item name="pdf_enabled" label="Genera PDF dopo ogni chiamata" valuePropName="checked">
          <Switch onChange={setPdfEnabled} />
        </Form.Item>

        <Form.Item
          name="pdf_template"
          label="Template PDF"
          tooltip="Il template determina come vengono presentati i dati estratti dalla chiamata"
        >
          <Select options={TEMPLATE_OPTIONS} disabled={!pdfEnabled} style={{ maxWidth: 420 }} />
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={saving}>
          Salva
        </Button>
      </Form>
    </Space>
  )
}

export default PdfEmailTab
