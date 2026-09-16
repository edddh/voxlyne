import { useState, useEffect, useCallback } from 'react'
import {
  Table, Button, Tag, Space, Modal, Form, Input, InputNumber, Upload, message,
  Popconfirm, Alert, Typography, List,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, DeleteOutlined, SyncOutlined, SearchOutlined, LinkOutlined, FileOutlined, EditOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [urlModalOpen, setUrlModalOpen] = useState(false)
  const [urlForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [scheduleModalSource, setScheduleModalSource] = useState(null)
  const [scheduleForm] = Form.useForm()
  const [savingSchedule, setSavingSchedule] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await kb.listSources(projectId)
      setSources(data)
    } catch (error) {
      message.error(t('knowledgeBase.loadError'))
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
      message.success(t('knowledgeBase.crawlStarted'))
      setUrlModalOpen(false)
      urlForm.resetFields()
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || t('knowledgeBase.crawlStartError'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleUpload = async (file) => {
    try {
      await kb.addUploadSource(projectId, file)
      message.success(t('knowledgeBase.fileUploaded'))
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || t('knowledgeBase.uploadError'))
    }
    return false // prevent antd's default auto-upload
  }

  const handleDelete = async (sourceId) => {
    await kb.deleteSource(projectId, sourceId)
    message.success(t('knowledgeBase.sourceDeleted'))
    load()
  }

  const handleReindex = async (sourceId) => {
    try {
      await kb.reindexSource(projectId, sourceId)
      message.success(t('knowledgeBase.reindexStarted'))
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || t('knowledgeBase.reindexError'))
    }
  }

  const openScheduleModal = (source) => {
    setScheduleModalSource(source)
    scheduleForm.setFieldsValue({
      max_pages: source.crawl_max_pages,
      recrawl_interval_hours: source.recrawl_interval_hours || undefined,
    })
  }

  const handleSaveSchedule = async (values) => {
    setSavingSchedule(true)
    try {
      await kb.updateSchedule(projectId, scheduleModalSource.id, values)
      message.success(t('knowledgeBase.scheduleUpdated'))
      setScheduleModalSource(null)
      load()
    } catch (error) {
      message.error(error.response?.data?.detail || t('knowledgeBase.scheduleSaveError'))
    } finally {
      setSavingSchedule(false)
    }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    try {
      const data = await kb.searchKnowledgeBase(projectId, searchQuery)
      setSearchResults(data.results)
    } catch (error) {
      message.error(error.response?.data?.detail || t('knowledgeBase.searchUnavailable'))
    } finally {
      setSearching(false)
    }
  }

  const columns = [
    {
      title: t('knowledgeBase.source'),
      key: 'source',
      render: (_, r) => (
        <Space>
          {r.source_type === 'url' ? <LinkOutlined /> : <FileOutlined />}
          <Text>{r.source_type === 'url' ? r.url : r.filename}</Text>
        </Space>
      ),
    },
    {
      title: t('tenantCredentials.status'),
      key: 'status',
      render: (_, r) => (
        <Space>
          <Tag color={STATUS_COLORS[r.status]}>{r.status}</Tag>
          {r.status === 'processing' && (
            <Text type="secondary">{t('knowledgeBase.pagesAnalyzedSoFar', { count: r.pages_crawled })}</Text>
          )}
        </Space>
      ),
    },
    { title: t('knowledgeBase.indexedPages'), dataIndex: 'pages_crawled' },
    { title: t('knowledgeBase.indexedChunks'), dataIndex: 'chunk_count' },
    {
      title: t('knowledgeBase.autoRecrawl'),
      dataIndex: 'recrawl_interval_hours',
      render: (v) => (v ? t('knowledgeBase.everyHours', { hours: v }) : v === 0 ? '—' : (v === null ? t('knowledgeBase.manual') : t('knowledgeBase.everyHours', { hours: v }))),
    },
    {
      title: t('tenantCredentials.actions'),
      key: 'actions',
      render: (_, r) => (
        <Space>
          {r.source_type === 'url' && (
            <>
              <Button size="small" icon={<SyncOutlined />} onClick={() => handleReindex(r.id)}>
                {t('knowledgeBase.reindex')}
              </Button>
              <Button size="small" icon={<EditOutlined />} onClick={() => openScheduleModal(r)}>
                {t('knowledgeBase.schedule')}
              </Button>
            </>
          )}
          <Popconfirm title={t('knowledgeBase.confirmDeleteSource')} onConfirm={() => handleDelete(r.id)}>
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
        message={t('knowledgeBase.title')}
        description={t('knowledgeBase.description')}
      />

      <Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setUrlModalOpen(true)}>
          {t('knowledgeBase.addUrlToCrawl')}
        </Button>
        <Upload beforeUpload={handleUpload} showUploadList={false} accept=".pdf,.docx,.txt,.md,.html">
          <Button icon={<UploadOutlined />}>{t('knowledgeBase.uploadDocument')}</Button>
        </Upload>
        <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>
          {t('knowledgeBase.trySearch')}
        </Button>
      </Space>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={sources}
        loading={loading}
        pagination={false}
        locale={{ emptyText: t('knowledgeBase.noSourcesConfigured') }}
      />

      <Modal
        title={t('knowledgeBase.addUrlToCrawl')}
        open={urlModalOpen}
        onCancel={() => setUrlModalOpen(false)}
        onOk={() => urlForm.submit()}
        confirmLoading={submitting}
      >
        <Form form={urlForm} layout="vertical" onFinish={handleAddUrl} initialValues={{ max_pages: 20 }}>
          <Form.Item name="url" label={t('knowledgeBase.startUrl')} rules={[{ required: true, type: 'url' }]}>
            <Input placeholder="https://www.comune.exampleville.it" />
          </Form.Item>
          <Form.Item name="max_pages" label={t('knowledgeBase.maxPagesPerCrawl')} tooltip={t('knowledgeBase.maxPagesTooltip')}>
            <InputNumber min={1} max={200} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="recrawl_interval_hours"
            label={t('knowledgeBase.autoRecrawlEvery')}
            tooltip={t('knowledgeBase.autoRecrawlTooltip')}
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder={t('knowledgeBase.hoursPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('knowledgeBase.editSchedule')}
        open={!!scheduleModalSource}
        onCancel={() => setScheduleModalSource(null)}
        onOk={() => scheduleForm.submit()}
        confirmLoading={savingSchedule}
      >
        <Form form={scheduleForm} layout="vertical" onFinish={handleSaveSchedule}>
          <Form.Item name="max_pages" label={t('knowledgeBase.maxPagesPerCrawl')}>
            <InputNumber min={1} max={3000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="recrawl_interval_hours"
            label={t('knowledgeBase.autoRecrawlEvery')}
            tooltip={t('knowledgeBase.autoRecrawlDisableTooltip')}
          >
            <InputNumber min={1} style={{ width: '100%' }} placeholder={t('knowledgeBase.hoursPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('knowledgeBase.trySearchTitle')}
        open={searchOpen}
        onCancel={() => setSearchOpen(false)}
        footer={null}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Input
            placeholder={t('knowledgeBase.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onPressEnter={handleSearch}
          />
          <Button type="primary" loading={searching} onClick={handleSearch}>{t('knowledgeBase.search')}</Button>
        </Space.Compact>
        {searchResults && (
          <List
            dataSource={searchResults}
            locale={{ emptyText: t('knowledgeBase.noResults') }}
            renderItem={(item) => (
              <List.Item>
                <div style={{ width: '100%' }}>
                  <Text type="secondary">{t('knowledgeBase.similarity')} {item.similarity.toFixed(3)}{item.origin_url ? ` · ${item.origin_url}` : ''}</Text>
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
