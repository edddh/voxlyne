import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Tag, Space, Modal, Form, Input, InputNumber, Upload, message,
  Popconfirm, Alert, Typography, List,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, DeleteOutlined, SyncOutlined, SearchOutlined, LinkOutlined, FileOutlined,
} from '@ant-design/icons'
import * as kb from '../api/knowledgeBase'

const { Text } = Typography

const STATUS_COLORS = { pending: 'default', processing: 'processing', indexed: 'success', failed: 'error' }

/**
 * Per-project knowledge base: URL crawl sources and uploaded documents,
 * chunked/embedded into pgvector, searchable by the voice agent's
 * search_knowledge_base tool during a live call (see
 * app/services/rag/, runtime_workers/realtime_service.py). Generalized
 * per maintainer's instruction (18/08): "se ti chiedo la RAG del comune di
 * Exampleville significa che devi generalizzare la mia richiesta... tramite
 * configurazione del pannello admin" - any project can populate its own
 * knowledge base here, Exampleville is just the first one that does.
 */
function KnowledgeBaseTab({ projectId }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [urlModalOpen, setUrlModalOpen] = useState(false)
  const [urlForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await kb.listSources(projectId)
      setSources(data)
    } catch (error) {
      message.error('Errore nel caricamento delle fonti')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    load()
    // Poll while any source is still pending/processing - status changes
    // happen in a background asyncio task server-side, no push channel.
    const interval = setInterval(() => {
      setSources((current) => {
        if (current.some((s) => s.status === 'pending' || s.status === 'processing')) {
          load()
        }
        return current
      })
    }, 4000)
    return () => clearInterval(interval)
  }, [load])

  const handleAddUrl = async (values) => {
    setSubmitting(true)
    try {
      await kb.addUrlSource(projectId, values)
      message.success('Crawl avviato')
      setUrlModalOpen(false)
      urlForm.resetFields()
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || "Errore nell'avvio del crawl")
    } finally {
      setSubmitting(false)
    }
  }

  const handleUpload = async (file) => {
    try {
      await kb.addUploadSource(projectId, file)
      message.success('File caricato, indicizzazione avviata')
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nel caricamento del file')
    }
    return false // prevent antd's default auto-upload
  }

  const handleDelete = async (sourceId) => {
    await kb.deleteSource(projectId, sourceId)
    message.success('Fonte eliminata')
    load()
  }

  const handleReindex = async (sourceId) => {
    try {
      await kb.reindexSource(projectId, sourceId)
      message.success('Reindicizzazione avviata')
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || 'Errore nella reindicizzazione')
    }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    try {
      const data = await kb.searchKnowledgeBase(projectId, searchQuery)
      setSearchResults(data.results)
    } catch (error) {
      message.error(error.response?.data?.detail || 'Ricerca non disponibile (credenziale llm/openai mancante per il tenant?)')
    } finally {
      setSearching(false)
    }
  }

  const columns = [
    {
      title: 'Fonte',
      key: 'source',
      render: (_, r) => (
        <Space>
          {r.source_type === 'url' ? <LinkOutlined /> : <FileOutlined />}
          <Text>{r.source_type === 'url' ? r.url : r.filename}</Text>
        </Space>
      ),
    },
    {
      title: 'Stato',
      key: 'status',
      render: (_, r) => (
        <Space>
          <Tag color={STATUS_COLORS[r.status]}>{r.status}</Tag>
          {r.status === 'processing' && (
            <Text type="secondary">{r.pages_crawled} pagine analizzate finora</Text>
          )}
        </Space>
      ),
    },
    { title: 'Pagine indicizzate', dataIndex: 'pages_crawled' },
    { title: 'Chunk indicizzati', dataIndex: 'chunk_count' },
    {
      title: 'Ricrawl automatico',
      dataIndex: 'recrawl_interval_hours',
      render: (v) => (v ? `ogni ${v}h` : v === 0 ? '—' : (v === null ? 'manuale' : `ogni ${v}h`)),
    },
    {
      title: 'Azioni',
      key: 'actions',
      render: (_, r) => (
        <Space>
          {r.source_type === 'url' && (
            <Button size="small" icon={<SyncOutlined />} onClick={() => handleReindex(r.id)}>
              Reindicizza
            </Button>
          )}
          <Popconfirm title="Eliminare questa fonte e i suoi chunk?" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="Knowledge base del progetto"
        description="L'agente vocale consulta queste fonti durante la chiamata (tool search_knowledge_base) per rispondere a domande specifiche - orari, procedure, notizie, regolamenti. Aggiungi un URL da crawlare (rileva automaticamente i siti costruiti sul template kPortal/AGID, con API di contenuto dedicata) oppure carica un documento."
      />

      <Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setUrlModalOpen(true)}>
          Aggiungi URL da crawlare
        </Button>
        <Upload beforeUpload={handleUpload} showUploadList={false} accept=".pdf,.docx,.txt,.md,.html">
          <Button icon={<UploadOutlined />}>Carica documento</Button>
        </Upload>
        <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>
          Prova la ricerca
        </Button>
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={sources}
        loading={loading}
        pagination={false}
        locale={{ emptyText: 'Nessuna fonte configurata' }}
      />

      <Modal
        title="Aggiungi URL da crawlare"
        open={urlModalOpen}
        onCancel={() => setUrlModalOpen(false)}
        onOk={() => urlForm.submit()}
        confirmLoading={submitting}
      >
        <Form form={urlForm} layout="vertical" onFinish={handleAddUrl} initialValues={{ max_pages: 20 }}>
          <Form.Item name="url" label="URL di partenza" rules={[{ required: true, type: 'url' }]}>
            <Input placeholder="https://www.comune.exampleville.it" />
          </Form.Item>
          <Form.Item name="max_pages" label="Numero massimo di pagine per crawl" tooltip="Quante pagine indicizzare al massimo ad ogni esecuzione">
            <InputNumber min={1} max={200} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="recrawl_interval_hours"
            label="Ricrawl automatico ogni (ore)"
            tooltip="Lascia vuoto per un'indicizzazione una tantum - potrai comunque rilanciarla a mano con 'Reindicizza'"
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder="es. 24 = una volta al giorno" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Prova la ricerca nella knowledge base"
        open={searchOpen}
        onCancel={() => setSearchOpen(false)}
        footer={null}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Input
            placeholder="Es. orari apertura uffici anagrafe"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onPressEnter={handleSearch}
          />
          <Button type="primary" loading={searching} onClick={handleSearch}>Cerca</Button>
        </Space.Compact>
        {searchResults && (
          <List
            dataSource={searchResults}
            locale={{ emptyText: 'Nessun risultato' }}
            renderItem={(item) => (
              <List.Item>
                <div style={{ width: '100%' }}>
                  <Text type="secondary">similarità {item.similarity.toFixed(3)}{item.origin_url ? ` · ${item.origin_url}` : ''}</Text>
                  <div>{item.content.slice(0, 300)}{item.content.length > 300 ? '…' : ''}</div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </Space>
  )
}

export default KnowledgeBaseTab
