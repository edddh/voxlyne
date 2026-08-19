import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, Input, message, Typography, Tabs, Row, Col, Spin, Alert, Tag, Divider, Switch, List, Popconfirm,
} from 'antd'
import { SaveOutlined, ArrowLeftOutlined, RocketOutlined, MessageOutlined, PhoneOutlined, UndoOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import * as projectsApi from '../api/projects'
import * as agentVersionsApi from '../api/agentVersions'
import PromptDiff, { normalizeNewlines } from '../components/PromptDiff'
import SimulateChat from '../components/SimulateChat'
import SimulateVoiceCall from '../components/SimulateVoiceCall'
import { substituteCustomVariables, extractCustomTags } from '../utils/promptVariables'
import { BRAND } from '../main'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

/**
 * Editor del prompt del progetto.
 *
 * Fino al 19/08 leggeva/scriveva solo su un sistema di versioning piu'
 * vecchio (prompt_versions, app/api/prompts.js) completamente scollegato
 * da cosa risponde davvero l'agente in chiamata - maintainer: "quando entro
 * in progetto exampleville non vedo il prompt attuale per la chiamata".
 * Quel sistema non aveva nulla per Exampleville (creato direttamente a DB in
 * questa sessione), quindi il campo appariva vuoto anche se il prompt
 * vero esisteva sia su projects.prompt_a sia sulla versione pubblicata.
 *
 * Ora: il testo mostrato/modificato e' projects.prompt_a/prompt_b (la
 * bozza reale del progetto - stesso campo che PATCH /api/projects/{id}
 * aggiorna). "Salva" scrive la bozza. "Pubblica" congela la bozza in una
 * nuova agent_version (app/services/agent_versions.py, il motore che
 * resolve_inbound() legge davvero per rispondere alle chiamate reali) -
 * senza questo passaggio esplicito, salvare la bozza da solo non
 * cambierebbe nulla per una chiamata gia' in corso di risoluzione.
 */
function ProjectEdit() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [reverting, setReverting] = useState(false)
  const [promptA, setPromptA] = useState('')
  const [promptB, setPromptB] = useState('')
  const [savedPromptA, setSavedPromptA] = useState('')
  const [savedPromptB, setSavedPromptB] = useState('')
  const [consentMessage, setConsentMessage] = useState('')
  const [savedConsentMessage, setSavedConsentMessage] = useState('')
  const [savingConsent, setSavingConsent] = useState(false)
  const [versions, setVersions] = useState([])
  const [hasChangesA, setHasChangesA] = useState(false)
  const [hasChangesB, setHasChangesB] = useState(false)
  const [simulateOpen, setSimulateOpen] = useState(false)
  const [simulateVoiceOpen, setSimulateVoiceOpen] = useState(false)
  // {{key}} custom variables - il prompt tiene i tag per sempre, questi
  // sono i valori sostituiti solo alla pubblicazione (app/services/
  // agent_versions.py::publish_version). maintainer, 20/08: "il template
  // dovrebbe avere dei campi custom... che possono poi essere modificati
  // successivamente".
  const [customVariablesSchema, setCustomVariablesSchema] = useState([])
  const [savedCustomVariablesSchema, setSavedCustomVariablesSchema] = useState([])
  const [customVariables, setCustomVariables] = useState({})
  const [savedCustomVariables, setSavedCustomVariables] = useState({})
  const [savingVariables, setSavingVariables] = useState(false)
  const promptARef = useRef(null)
  const promptBRef = useRef(null)

  useEffect(() => {
    loadProject()
  }, [id])

  const publishedVersion = versions.find((v) => v.status === 'published')
  // Bug corretto 19/08 (maintainer: "non capisco cosa devo fare per
  // pubblicare"): confrontava la bozza salvata con se stessa
  // (project.prompt_a, aggiornato subito dopo ogni salvataggio) invece
  // che con la versione davvero pubblicata - dopo "Salva bozza" il
  // banner poteva sembrare gia' a posto anche quando non lo era, e il
  // pulsante Pubblica restava disabilitato senza una spiegazione chiara
  // del perche'. Il confronto giusto e' bozza salvata vs. contenuto
  // dell'ultima versione pubblicata.
  const draftDiffersFromPublished = !publishedVersion ||
    (project?.prompt_a || '') !== (publishedVersion?.prompt_a || '') ||
    (project?.prompt_b || '') !== (publishedVersion?.prompt_b || '') ||
    (project?.consent_message || '') !== (publishedVersion?.consent_message || '')
  const hasChangesConsent = consentMessage !== savedConsentMessage
  const hasUnsavedEdits = hasChangesA || hasChangesB || hasChangesConsent
  // A differenza di draftDiffersFromPublished (bozza SALVATA vs
  // pubblicata), questo guarda cosa c'e' davvero nell'editor adesso -
  // incluse modifiche non ancora salvate - per decidere se mostrare il
  // pulsante "Ripristina pubblicata". maintainer, 20/08: "manca un revert
  // quando ho salvato una bozza anziche' pubblicarla".
  const editorDiffersFromPublished = !!publishedVersion && (
    normalizeNewlines(promptA) !== normalizeNewlines(publishedVersion.prompt_a || '') ||
    normalizeNewlines(promptB) !== normalizeNewlines(publishedVersion.prompt_b || '') ||
    consentMessage !== (publishedVersion.consent_message || '')
  )

  const loadProject = async () => {
    setLoading(true)
    try {
      const data = await projectsApi.getProject(id)
      setProject(data)
      setPromptA(data.prompt_a || '')
      setPromptB(data.prompt_b || '')
      setSavedPromptA(data.prompt_a || '')
      setSavedPromptB(data.prompt_b || '')
      setConsentMessage(data.consent_message || '')
      setSavedConsentMessage(data.consent_message || '')
      setCustomVariablesSchema(data.custom_variables_schema || [])
      setSavedCustomVariablesSchema(data.custom_variables_schema || [])
      setCustomVariables(data.custom_variables || {})
      setSavedCustomVariables(data.custom_variables || {})

      try {
        const versionsList = await agentVersionsApi.listAgentVersions(id)
        setVersions(versionsList)
      } catch (e) {
        // Nessuna versione pubblicata ancora - normale per un progetto nuovo.
      }
    } catch (error) {
      message.error('Errore caricamento progetto')
      navigate('/projects')
    } finally {
      setLoading(false)
    }
  }

  // maintainer, 20/08: "quando si fa l'editing del prompt nel progetto non
  // c'e' modo di inserire anche il contenuto dei tag configurabili?" -
  // inserisce {{key}} nella posizione del cursore, non solo in coda.
  // Input.TextArea di antd inoltra il ref al textarea nativo (versioni
  // recenti) o a .resizableTextArea.textArea (versioni piu' vecchie) -
  // gestiti entrambi.
  const insertAtCursor = (type, text) => {
    const ref = type === 'A' ? promptARef : promptBRef
    const el = ref.current?.resizableTextArea?.textArea || ref.current
    const current = type === 'A' ? promptA : promptB
    if (!el || typeof el.selectionStart !== 'number') {
      // Fallback senza cursore noto: in coda.
      handlePromptChange(type, current + text)
      return
    }
    const start = el.selectionStart
    const end = el.selectionEnd
    const next = current.slice(0, start) + text + current.slice(end)
    handlePromptChange(type, next)
    // Il cursore dopo il testo appena inserito, dopo che React ha
    // ri-renderizzato con il nuovo value.
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + text.length, start + text.length)
    })
  }

  const insertTag = (type, tagKey) => insertAtCursor(type, `{{${tagKey}}}`)

  const handlePromptChange = (type, value) => {
    if (type === 'A') {
      setPromptA(value)
      setHasChangesA(value !== savedPromptA)
    } else {
      setPromptB(value)
      setHasChangesB(value !== savedPromptB)
    }
  }

  const savePrompt = async (type) => {
    setSaving(true)
    try {
      const content = type === 'A' ? promptA : promptB
      if (!content.trim()) {
        message.warning('Il prompt non può essere vuoto')
        return
      }

      const field = type === 'A' ? 'prompt_a' : 'prompt_b'
      await projectsApi.updateProject(id, { [field]: content })

      message.success('Bozza salvata - pubblica per renderla attiva nelle chiamate')

      if (type === 'A') {
        setSavedPromptA(content)
        setHasChangesA(false)
      } else {
        setSavedPromptB(content)
        setHasChangesB(false)
      }
      setProject((prev) => ({ ...prev, [field]: content }))
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSaving(false)
    }
  }

  const saveConsentMessage = async () => {
    setSavingConsent(true)
    try {
      await projectsApi.updateProject(id, { consent_message: consentMessage })
      message.success('Frase di apertura salvata - pubblica per renderla attiva nelle chiamate')
      setSavedConsentMessage(consentMessage)
      setProject((prev) => ({ ...prev, consent_message: consentMessage }))
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSavingConsent(false)
    }
  }

  const hasChangesVariables =
    JSON.stringify(customVariables) !== JSON.stringify(savedCustomVariables) ||
    JSON.stringify(customVariablesSchema) !== JSON.stringify(savedCustomVariablesSchema)
  const schemaKeys = customVariablesSchema.map((f) => f.key)
  // {{tag}} presenti nel prompt ma senza una voce nella tabella
  // "Variabili del progetto" sopra - a pubblicazione resterebbero
  // {{cosi'}} nel testo, letteralmente visibili a chi chiama.
  const undefinedTagsIn = (text) => extractCustomTags(text).filter((key) => !schemaKeys.includes(key))

  // maintainer, 20/08: "come ne definisco di nuovi quando edito il
  // prompt... il meglio sarebbe poter mettere direttamente {{key}} e
  // poi tutto il resto va di conseguenza" - niente di automatico senza
  // conferma (scelto apposta, per non registrare per sbaglio un
  // {{...}} che non era un vero tag): un click sull'avviso lo aggiunge
  // come variabile del progetto, poi si edita qui sotto come le altre.
  const addTagAsVariable = (tagKey) => {
    setCustomVariablesSchema((prev) => [...prev, { key: tagKey, label: tagKey, description: '', default: '' }])
    setCustomVariables((prev) => ({ ...prev, [tagKey]: '' }))
  }

  const removeVariable = (tagKey) => {
    setCustomVariablesSchema((prev) => prev.filter((f) => f.key !== tagKey))
    setCustomVariables((prev) => {
      const next = { ...prev }
      delete next[tagKey]
      return next
    })
  }

  const updateVariableField = (tagKey, field, value) => {
    setCustomVariablesSchema((prev) => prev.map((f) => (f.key === tagKey ? { ...f, [field]: value } : f)))
  }

  const saveCustomVariables = async () => {
    setSavingVariables(true)
    try {
      await projectsApi.updateProject(id, {
        custom_variables: customVariables,
        custom_variables_schema: customVariablesSchema,
      })
      message.success('Variabili salvate - pubblica per renderle attive nelle chiamate')
      setSavedCustomVariables(customVariables)
      setSavedCustomVariablesSchema(customVariablesSchema)
      setProject((prev) => ({ ...prev, custom_variables: customVariables, custom_variables_schema: customVariablesSchema }))
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore salvataggio')
    } finally {
      setSavingVariables(false)
    }
  }

  const handleRevert = async () => {
    if (!publishedVersion) return
    setReverting(true)
    try {
      const payload = {
        prompt_a: publishedVersion.prompt_a || '',
        prompt_b: publishedVersion.prompt_b || '',
        consent_message: publishedVersion.consent_message || '',
      }
      // Scrive la bozza (projects.prompt_a/b/consent_message) uguale
      // alla versione pubblicata - stessa PATCH usata da "Salva bozza",
      // cosi' anche una bozza gia' salvata (non solo modifiche non
      // ancora salvate nell'editor) torna in linea con cio' che sente
      // davvero chi chiama.
      await projectsApi.updateProject(id, payload)
      setPromptA(payload.prompt_a)
      setPromptB(payload.prompt_b)
      setConsentMessage(payload.consent_message)
      setSavedPromptA(payload.prompt_a)
      setSavedPromptB(payload.prompt_b)
      setSavedConsentMessage(payload.consent_message)
      setHasChangesA(false)
      setHasChangesB(false)
      setProject((prev) => ({ ...prev, ...payload }))
      message.success(`Bozza ripristinata alla versione pubblicata (v${publishedVersion.version_number})`)
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nel ripristino')
    } finally {
      setReverting(false)
    }
  }

  const handlePublish = async () => {
    setPublishing(true)
    try {
      await agentVersionsApi.publishVersion(id)
      message.success('Pubblicato - attivo per le prossime chiamate')
      const versionsList = await agentVersionsApi.listAgentVersions(id)
      setVersions(versionsList)
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore pubblicazione')
    } finally {
      setPublishing(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    )
  }

  const promptItems = [
    {
      key: 'A',
      label: (
        <Space>
          <span>Prompt A (Conversazione)</span>
          {hasChangesA && <Tag color="orange">Non salvato</Tag>}
        </Space>
      ),
      children: (
        <div>
          <Alert
            message="Prompt di Conversazione"
            description="Questo prompt guida l'AI durante la chiamata telefonica. Include istruzioni su come condurre la conversazione, le domande o informazioni da fornire e come gestire le risposte di chi chiama."
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>Inserisci variabile:</Text>
            {customVariablesSchema.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12, fontStyle: 'italic' }}>
                nessuna ancora - scrivi {'{{nome}}'} nel prompt e sotto compare "Aggiungi come variabile"
              </Text>
            ) : (
              <Space wrap size={4}>
                {customVariablesSchema.map((field) => (
                  <Tag
                    key={field.key}
                    style={{ cursor: 'pointer', fontFamily: 'monospace' }}
                    onClick={() => insertTag('A', field.key)}
                    title={field.label}
                  >
                    {`{{${field.key}}}`}
                  </Tag>
                ))}
              </Space>
            )}

            {/* maintainer, 20/08: "l'altro tag che contiene data e ora...
                dovrebbero essere quelli predefiniti ma l'utente non sa a
                cosa servono, servirebbe una descrizione minima sotto
                quelli custom" - due meccanismi diversi, non solo un altro
                {{tag}}: current_datetime e' uno STRUMENTO che il modello
                chiama da solo (basta nominarlo nel prompt, non va tra
                parentesi graffe - inserirlo come {{current_datetime}}
                sarebbe scorretto, Ascolta non lo sostituisce), mentre
                system__caller_id resta un vero tag {{...}}, risolto dal
                provider voce. Spiegati qui invece di lasciarli intuire. */}
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Gia' disponibili, non serve configurarli:
              </Text>
              <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <Space size={6} align="start">
                  <Tag
                    color="blue"
                    style={{ cursor: 'pointer', fontFamily: 'monospace', margin: 0 }}
                    onClick={() => insertTag('A', 'system__caller_id')}
                  >
                    {'{{system__caller_id}}'}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    il numero di chi sta chiamando - lo passa il provider vocale, Ascolta non lo tocca
                  </Text>
                </Space>
                <Space size={6} align="start">
                  <Tag
                    color="blue"
                    style={{ cursor: 'pointer', margin: 0 }}
                    // Non e' un {{tag}} - inseriamo la frase pronta
                    // all'uso cosi' com'e' nel prompt Comune/URP gia'
                    // verificato con una simulazione di test, non solo la
                    // parola nuda.
                    onClick={() =>
                      insertAtCursor(
                        'A',
                        "Usa current_datetime come unica fonte di verita' per data, ora e giorno della settimana correnti a Roma."
                      )
                    }
                  >
                    current_datetime
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    strumento che il modello chiama da solo per sapere data/ora correnti - basta nominarlo nel prompt in una frase, non va scritto tra {'{{ }}'}
                  </Text>
                </Space>
              </div>
            </div>
          </div>
          <TextArea
            ref={promptARef}
            value={promptA}
            onChange={(e) => handlePromptChange('A', e.target.value)}
            rows={20}
            placeholder="Inserisci il prompt di conversazione..."
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
          {undefinedTagsIn(promptA).length > 0 && (
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              message="Tag senza un valore"
              description={
                <Space direction="vertical" size={8}>
                  <Text>
                    Questi {'{{tag}}'} compaiono nel prompt ma non hanno una variabile definita - restano cosi',
                    visibili letteralmente a chi chiama, finche' non li aggiungi (o li togli dal prompt).
                  </Text>
                  <Space wrap size={4}>
                    {undefinedTagsIn(promptA).map((t) => (
                      <Button key={t} size="small" icon={<PlusOutlined />} onClick={() => addTagAsVariable(t)}>
                        {`Aggiungi {{${t}}} come variabile`}
                      </Button>
                    ))}
                  </Space>
                </Space>
              }
            />
          )}
          {publishedVersion && normalizeNewlines(promptA) !== normalizeNewlines(publishedVersion.prompt_a) && (
            <div style={{ marginTop: 16 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 6 }}>
                Differenze rispetto alla versione pubblicata (v{publishedVersion.version_number}):
              </Text>
              <PromptDiff published={publishedVersion.prompt_a || ''} draft={promptA} />
            </div>
          )}
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <Text type="secondary">
              {promptA.length} caratteri • ~{Math.ceil(promptA.length / 4)} token
            </Text>
            <Space wrap>
              <Button icon={<PhoneOutlined />} onClick={() => setSimulateVoiceOpen(true)}>
                Prova chiamata vocale
              </Button>
              <Button icon={<MessageOutlined />} onClick={() => setSimulateOpen(true)}>
                Prova conversazione testuale
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={() => savePrompt('A')}
                loading={saving}
                disabled={!hasChangesA}
              >
                Salva bozza
              </Button>
            </Space>
          </div>
        </div>
      ),
    },
    {
      key: 'B',
      label: (
        <Space>
          <span>Prompt B (Estrazione)</span>
          {hasChangesB && <Tag color="orange">Non salvato</Tag>}
        </Space>
      ),
      children: (
        <div>
          <Alert
            message="Prompt di Estrazione"
            description="Questo prompt viene usato per estrarre informazioni strutturate dalla trascrizione della chiamata. Definisce il formato JSON di output e i campi da estrarre."
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
          {customVariablesSchema.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>Inserisci variabile:</Text>
              <Space wrap size={4}>
                {customVariablesSchema.map((field) => (
                  <Tag
                    key={field.key}
                    style={{ cursor: 'pointer', fontFamily: 'monospace' }}
                    onClick={() => insertTag('B', field.key)}
                  >
                    {`{{${field.key}}}`}
                  </Tag>
                ))}
              </Space>
            </div>
          )}
          <TextArea
            ref={promptBRef}
            value={promptB}
            onChange={(e) => handlePromptChange('B', e.target.value)}
            rows={20}
            placeholder="Inserisci il prompt di estrazione..."
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
          {undefinedTagsIn(promptB).length > 0 && (
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              message="Tag senza un valore"
              description={
                <Space direction="vertical" size={8}>
                  <Text>Questi {'{{tag}}'} compaiono nel prompt ma non hanno una variabile definita.</Text>
                  <Space wrap size={4}>
                    {undefinedTagsIn(promptB).map((t) => (
                      <Button key={t} size="small" icon={<PlusOutlined />} onClick={() => addTagAsVariable(t)}>
                        {`Aggiungi {{${t}}} come variabile`}
                      </Button>
                    ))}
                  </Space>
                </Space>
              }
            />
          )}
          {publishedVersion && normalizeNewlines(promptB) !== normalizeNewlines(publishedVersion.prompt_b) && (
            <div style={{ marginTop: 16 }}>
              <Text type="secondary" style={{ display: 'block', marginBottom: 6 }}>
                Differenze rispetto alla versione pubblicata (v{publishedVersion.version_number}):
              </Text>
              <PromptDiff published={publishedVersion.prompt_b || ''} draft={promptB} />
            </div>
          )}
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <Text type="secondary">
              {promptB.length} caratteri • ~{Math.ceil(promptB.length / 4)} token
            </Text>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={() => savePrompt('B')}
              loading={saving}
              disabled={!hasChangesB}
            >
              Salva bozza
            </Button>
          </div>
        </div>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 8 }}>
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
            Indietro
          </Button>
          <Title level={3} style={{ margin: 0, flexShrink: 0 }}>{project?.name}</Title>
          <Tag color={project?.is_active ? 'green' : 'red'}>
            {project?.is_active ? 'Attivo' : 'Inattivo'}
          </Tag>
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        <Col span={24}>
          <Alert
            type={hasUnsavedEdits ? 'info' : draftDiffersFromPublished ? 'warning' : 'success'}
            showIcon
            message={
              publishedVersion
                ? `Versione pubblicata: v${publishedVersion.version_number}${publishedVersion.published_at ? ' · ' + new Date(publishedVersion.published_at).toLocaleString('it-IT') : ''}`
                : 'Nessuna versione ancora pubblicata - questo progetto non risponde ancora a nessuna simulazione di test'
            }
            // I bottoni erano nello slot "action" di Alert (di fianco al
            // testo) - su schermo stretto quello spazio si comprimeva
            // quasi a zero e il testo andava a capo lettera per lettera
            // (maintainer: "il testo... è strettissimo... scritto tutto in
            // verticale", stesso bug gia' visto altrove in sessione).
            // Spostati sotto al testo, dentro "description", cosi' non
            // competono mai per la larghezza.
            description={
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Text>
                  {hasUnsavedEdits
                    ? 'Passo 1 di 2: hai modifiche non ancora salvate nelle schede qui sotto. Premi "Salva bozza" nella scheda che hai modificato, poi torna qui per pubblicarle.'
                    : draftDiffersFromPublished
                    ? 'Passo 2 di 2: la bozza salvata e\' pronta ma non ancora attiva. Le chiamate reali continuano a usare la versione pubblicata sopra finche\' non premi "Pubblica".'
                    : 'La bozza corrisponde esattamente alla versione pubblicata - quello che vedi qui e\' quello che sente chi chiama, nessuna azione necessaria.'}
                </Text>
                <Space wrap>
                <Popconfirm
                  title="Ripristinare la versione pubblicata?"
                  description="La bozza (salvata o no) torna uguale a quello che sente davvero chi chiama adesso - le modifiche fatte qui vanno perse."
                  onConfirm={handleRevert}
                  okText="Ripristina"
                  cancelText="Annulla"
                  disabled={!editorDiffersFromPublished}
                >
                  <Button
                    icon={<UndoOutlined />}
                    loading={reverting}
                    disabled={!editorDiffersFromPublished}
                  >
                    Ripristina pubblicata
                  </Button>
                </Popconfirm>
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  onClick={handlePublish}
                  loading={publishing}
                  disabled={!draftDiffersFromPublished || hasUnsavedEdits}
                >
                  Pubblica
                </Button>
                </Space>
              </Space>
            }
          />
        </Col>

        <Col span={24}>
          <Card>
            <Paragraph type="secondary">
              <strong>Slug:</strong> <code>{project?.slug}</code>
            </Paragraph>
            {project?.description && (
              <Paragraph type="secondary">
                <strong>Descrizione:</strong> {project.description}
              </Paragraph>
            )}
          </Card>
        </Col>

        <Col span={24}>
          <Card
            title={
              <Space>
                <span>Frase di apertura</span>
                {hasChangesConsent && <Tag color="orange">Non salvato</Tag>}
              </Space>
            }
          >
            <Alert
              message="Cosa sente chi chiama per primo"
              description="La prima frase pronunciata dall'agente all'inizio della chiamata, prima che chi chiama dica qualsiasi cosa. Fa parte della stessa bozza/pubblicazione dei prompt qui sotto."
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
            <TextArea
              value={consentMessage}
              onChange={(e) => setConsentMessage(e.target.value)}
              rows={2}
              placeholder="Es. Salve, come posso aiutarla?"
            />
            <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                onClick={saveConsentMessage}
                loading={savingConsent}
                disabled={!hasChangesConsent}
              >
                Salva bozza
              </Button>
            </div>
          </Card>
        </Col>

        {customVariablesSchema.length > 0 && (
          <Col span={24}>
            <Card
              title={
                <Space>
                  <span>Variabili del progetto</span>
                  {hasChangesVariables && <Tag color="orange">Non salvato</Tag>}
                </Space>
              }
            >
              <Alert
                message="Valori per i tag {{...}} usati nel prompt"
                description="Alcuni arrivano dal template da cui e' nato questo progetto, altri li aggiungi tu (avviso sotto l'editor quando scrivi un {{tag}} nuovo). Cambiare un valore qui non modifica il testo del prompt - conta al momento della pubblicazione."
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
              />
              {customVariablesSchema.map((field) => (
                <Card
                  key={field.key}
                  size="small"
                  style={{ marginBottom: 12, background: BRAND.bgElevated, borderColor: BRAND.border }}
                  title={
                    <Text style={{ fontFamily: 'monospace', color: BRAND.orange, fontWeight: 'bold' }}>
                      {`{{${field.key}}}`}
                    </Text>
                  }
                  extra={
                    <DeleteOutlined onClick={() => removeVariable(field.key)} style={{ color: '#ff4d4f' }} />
                  }
                >
                  <Row gutter={[16, 8]}>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>Etichetta</Text>
                      <Input
                        value={field.label || ''}
                        onChange={(e) => updateVariableField(field.key, 'label', e.target.value)}
                        placeholder="es. Nome del Comune"
                      />
                    </Col>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ display: 'block', marginBottom: 4, fontSize: 12 }}>Valore</Text>
                      <Input
                        value={customVariables[field.key] || ''}
                        onChange={(e) => setCustomVariables((prev) => ({ ...prev, [field.key]: e.target.value }))}
                        placeholder={field.default || `{{${field.key}}}`}
                      />
                    </Col>
                  </Row>
                  {field.description && (
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>{field.description}</Text>
                  )}
                </Card>
              ))}
              <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={saveCustomVariables}
                  loading={savingVariables}
                  disabled={!hasChangesVariables}
                >
                  Salva variabili
                </Button>
              </div>
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card title="Editor Prompt">
            <Tabs items={promptItems} />
          </Card>
        </Col>

        {versions.length > 0 && (
          <Col span={24}>
            <Card
              title="Versioni pubblicate"
              extra={<Button size="small" onClick={() => navigate(`/projects/${id}/history`)}>Storico completo</Button>}
            >
              <List
                size="small"
                dataSource={versions}
                renderItem={(v) => (
                  <List.Item>
                    <Space>
                      <Tag color={v.status === 'published' ? 'green' : 'default'}>v{v.version_number}</Tag>
                      <Text>{v.status}</Text>
                      {v.published_at && (
                        <Text type="secondary">{new Date(v.published_at).toLocaleString('it-IT')}</Text>
                      )}
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card title="Configurazione Output">
            <Row gutter={[16, 16]}>
              <Col xs={12} sm={6}>
                <Card size="small" title="Email PDF">
                  <Switch
                    checked={project?.config?.send_email || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Invia PDF via email dopo la chiamata
                  </Text>
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" title="Sync CRM">
                  <Switch
                    checked={project?.config?.sync_crm || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Sincronizza con HubSpot
                  </Text>
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" title="Calendario">
                  <Switch
                    checked={project?.config?.create_event || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Crea evento calendario
                  </Text>
                </Card>
              </Col>
              <Col xs={12} sm={6}>
                <Card size="small" title="Webhook">
                  <Switch
                    checked={project?.config?.webhook_enabled || false}
                    disabled
                  />
                  <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                    Notifica webhook
                  </Text>
                </Card>
              </Col>
            </Row>
            <Divider />
            <Text type="secondary">
              Le configurazioni di output si gestiscono dalla scheda Impostazioni del progetto.
            </Text>
          </Card>
        </Col>
      </Row>

      {/* {{key}} sostituiti prima di arrivare alle simulazioni - provare
          con {{comune}} letterale invece di "Sampletown" sarebbe fuorviante,
          non riflette cosa sente davvero chi chiama. */}
      <SimulateChat
        open={simulateOpen}
        onClose={() => setSimulateOpen(false)}
        projectId={id}
        promptA={substituteCustomVariables(promptA, customVariables)}
        openingMessage={substituteCustomVariables(consentMessage, customVariables)}
      />
      <SimulateVoiceCall
        open={simulateVoiceOpen}
        onClose={() => setSimulateVoiceOpen(false)}
        projectId={id}
        promptA={substituteCustomVariables(promptA, customVariables)}
        consentMessage={substituteCustomVariables(consentMessage, customVariables)}
      />
    </div>
  )
}

export default ProjectEdit
