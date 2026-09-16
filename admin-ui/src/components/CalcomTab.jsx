import { useState, useEffect } from 'react'
import { Form, Input, Button, Alert, Space, message, Spin } from 'antd'
import { useTranslation } from 'react-i18next'
import * as projectsApi from '../api/projects'

/**
 * Configurazione Cal.com per-progetto (event type id di default, e i due
 * usati dal tool calendar_type "standard/sportivo" del template Studio
 * Appointment - vedi runtime_workers/realtime_service.py::resolve_event_type_id,
 * che li legge gia' da qui tramite la config generata da "Genera servizio
 * runtime").
 *
 * maintainer, 20/08: "ma l'integrazione di appointment-demo con cal.com e'
 * recuperabile da earlier-prototype? ... naturalmente dovrai generalizzarla e
 * renderla ottenibile tramite configurazioni come tutto il resto" - la
 * parte che sembrava "da recuperare" era gia' li' (tool calcom_*,
 * risoluzione della API key per-tenant via CredentialsManager in
 * app/services/runtime_provisioning.py, non un fallback globale - solo
 * l'API key CALCOM_API_KEY che si legge nel processo runtime standalone
 * viene DA quella risoluzione per-tenant, generata nel .env dell'istanza,
 * non letta da un env var condiviso). Il vero buco: mancava sia la UI
 * per impostare gli event_type_id per progetto, sia il passaggio dei due
 * event_type_id standard/sportivo nella config generata (solo quello di
 * default veniva passato) - corretti insieme a questo componente.
 *
 * L'API key vera e propria si configura a livello di credenziali tenant
 * (servizio "calendar", provider "calcom"), non qui - qui solo cosa e'
 * specifico di QUESTO progetto (quali event type Cal.com usare).
 */
function CalcomTab({ projectId }) {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [project, setProject] = useState(null)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await projectsApi.getProject(projectId)
        setProject(data)
        const calcomCfg = data.output_config?.calendar || {}
        form.setFieldsValue({
          username: calcomCfg.username || '',
          event_type_id: calcomCfg.event_type_id || '',
          standard_event_type_id: calcomCfg.standard_event_type_id || '',
          sport_event_type_id: calcomCfg.sport_event_type_id || '',
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
      const output_config = {
        ...(project.output_config || {}),
        calendar: {
          ...(project.output_config?.calendar || {}),
          username: values.username || undefined,
          event_type_id: values.event_type_id || undefined,
          standard_event_type_id: values.standard_event_type_id || undefined,
          sport_event_type_id: values.sport_event_type_id || undefined,
        },
      }
      await projectsApi.updateProject(projectId, { output_config })
      setProject((prev) => ({ ...prev, output_config }))
      message.success(t('calcomTab.saved'))
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
        message={t('calcomTab.title')}
        description={t('calcomTab.description')}
      />

      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Form.Item
          name="event_type_id"
          label={t('calcomTab.defaultEventTypeId')}
          tooltip={t('calcomTab.defaultEventTypeIdTooltip')}
        >
          <Input placeholder="es. 809" />
        </Form.Item>
        <Form.Item
          name="standard_event_type_id"
          label={t('calcomTab.standardEventTypeId')}
          tooltip={t('calcomTab.standardEventTypeIdTooltip')}
        >
          <Input placeholder="es. 810" />
        </Form.Item>
        <Form.Item
          name="sport_event_type_id"
          label={t('calcomTab.sportEventTypeId')}
          tooltip={t('calcomTab.sportEventTypeIdTooltip')}
        >
          <Input placeholder="es. 811" />
        </Form.Item>
        <Form.Item name="username" label={t('calcomTab.calcomUsername')}>
          <Input placeholder="es. studio-demo" />
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={saving}>
          {t('common.save')}
        </Button>
      </Form>
    </Space>
  )
}

export default CalcomTab
