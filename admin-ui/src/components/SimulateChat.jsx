import { useState, useRef, useEffect } from 'react'
import { Modal, Input, Button, Space, Avatar, Typography, Alert, Spin } from 'antd'
import { SendOutlined, UserOutlined, RobotOutlined, ReloadOutlined } from '@ant-design/icons'
import { simulateConversation } from '../api/simulation'
import { BRAND } from '../main'

const { Text } = Typography

/**
 * Chat di prova per testare come risponderebbe l'agente con il prompt
 * attuale nell'editor - PRIMA di salvare/pubblicare. maintainer, 19/08:
 * "sarebbe bello poter simulare la chiamata sul sito prima di pubblicare".
 *
 * Non e' una vera chiamata vocale (il modello realtime usato in chiamata
 * e' un'API WebSocket, non richiamabile da una chat testuale) - usa un
 * modello di testo comparabile con lo stesso prompt e la stessa
 * credenziale del tenant, per verificare tono/contenuto delle risposte.
 * Non ha accesso alla knowledge base ne' agli altri strumenti (Cal.com,
 * ecc.) - solo il ragionamento del prompt puro.
 */
function SimulateChat({ open, onClose, projectId, promptA }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (open) {
      setMessages([])
      setError(null)
      setInput('')
    }
  }, [open])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    const nextMessages = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setInput('')
    setSending(true)
    setError(null)
    try {
      const result = await simulateConversation(projectId, promptA, nextMessages)
      setMessages([...nextMessages, { role: 'assistant', content: result.reply }])
    } catch (err) {
      setError(err.response?.data?.detail || 'Errore nella simulazione')
    } finally {
      setSending(false)
    }
  }

  return (
    <Modal
      title="Prova la conversazione"
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <Alert
        type="info"
        showIcon
        message="Simulazione testuale del prompt attuale nell'editor (anche non salvato)"
        description="Non e' una vera chiamata vocale, e non ha accesso alla knowledge base ne' agli altri strumenti - serve per verificare tono e contenuto delle risposte prima di pubblicare."
        style={{ marginBottom: 12 }}
      />

      <div
        ref={scrollRef}
        style={{
          height: 360,
          overflowY: 'auto',
          border: `1px solid ${BRAND.border}`,
          borderRadius: 8,
          padding: 12,
          marginBottom: 12,
          background: BRAND.bg,
        }}
      >
        {messages.length === 0 && (
          <Text type="secondary">Scrivi un messaggio come farebbe chi chiama, per vedere come risponde.</Text>
        )}
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {messages.map((m, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, flexDirection: m.role === 'user' ? 'row-reverse' : 'row' }}>
              <Avatar
                size="small"
                icon={m.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                style={{ background: m.role === 'user' ? BRAND.border : BRAND.orange, flexShrink: 0 }}
              />
              <div
                style={{
                  background: m.role === 'user' ? BRAND.bgElevated : BRAND.orangeSoft,
                  padding: '8px 12px',
                  borderRadius: 8,
                  maxWidth: '75%',
                }}
              >
                <Text>{m.content}</Text>
              </div>
            </div>
          ))}
          {sending && <Spin size="small" />}
        </Space>
      </div>

      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}

      <Space.Compact style={{ width: '100%' }}>
        <Input
          placeholder="Scrivi come farebbe chi chiama..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={send}
          disabled={sending}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={sending}>
          Invia
        </Button>
      </Space.Compact>
      {messages.length > 0 && (
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => setMessages([])}
          style={{ marginTop: 8 }}
        >
          Ricomincia
        </Button>
      )}
    </Modal>
  )
}

export default SimulateChat
