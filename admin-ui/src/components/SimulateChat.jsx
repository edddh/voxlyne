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
 * Ha accesso alla knowledge base (search_knowledge_base, un solo giro di
 * tool-calling per risposta - maintainer, 19/08: "anche nella chat testuale",
 * stessa cosa gia' fatta per la simulazione vocale). Non ha accesso agli
 * altri strumenti (Cal.com, ecc.).
 */
function SimulateChat({ open, onClose, projectId, promptA, openingMessage }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (open) {
      // La frase di apertura e' la prima cosa che chi chiama sente
      // davvero (consent_message del progetto) - mancava del tutto
      // (maintainer, 19/08: "non dice la frase in apertura"). Mostrata
      // subito e inclusa nella storia inviata al modello, cosi' le
      // risposte successive la tengono in considerazione come farebbe in
      // una chiamata vera.
      setMessages(openingMessage ? [{ role: 'assistant', content: openingMessage }] : [])
      setError(null)
      setInput('')
    }
  }, [open, openingMessage])

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
      // Il backend accetta solo role user/assistant nella history (vedi
      // SimMessage in app/routers/simulation.py) - le voci 'tool' sono
      // solo per la visualizzazione qui, non vanno rimandate indietro.
      const apiHistory = nextMessages.filter((m) => m.role === 'user' || m.role === 'assistant')
      const result = await simulateConversation(projectId, promptA, apiHistory)
      const toolEntries = (result.tool_calls || []).map((tc) => ({ role: 'tool', ...tc }))
      setMessages([...nextMessages, ...toolEntries, { role: 'assistant', content: result.reply }])
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
      width="min(600px, 92vw)"
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
          {messages.map((m, i) =>
            m.role === 'tool' ? (
              <Text key={i} type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                🔧 {m.name}({JSON.stringify(m.arguments)}) → {m.result?.status}
                {m.result?.results?.length ? ` (${m.result.results.length} risultati)` : ''}
              </Text>
            ) : (
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
            )
          )}
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
