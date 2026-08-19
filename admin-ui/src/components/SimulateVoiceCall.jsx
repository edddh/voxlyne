import { useState, useRef, useCallback } from 'react'
import { Modal, Button, Space, Typography, Alert, Tag, List } from 'antd'
import { AudioOutlined, PhoneOutlined, StopOutlined } from '@ant-design/icons'
import { BRAND } from '../main'

const { Text } = Typography

// wss://host/... in ambiente di sviluppo (stesso dominio, come per le chiamate
// HTTP - vedi api/client.js), o costruito da VITE_API_URL se impostato
// esplicitamente per lo sviluppo locale.
function buildWsUrl(path) {
  const apiUrl = import.meta.env.VITE_API_URL
  if (apiUrl) {
    return apiUrl.replace(/^http/, 'ws') + path
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

const SAMPLE_RATE = 24000

function floatTo16BitPCM(float32) {
  const int16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return int16
}

function base64FromInt16(int16) {
  const bytes = new Uint8Array(int16.buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

function int16FromBase64(base64) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return new Int16Array(bytes.buffer)
}

/**
 * Vera chiamata di prova col modello vocale reale (grok-voice-latest),
 * microfono del browser in ingresso, altoparlante in uscita - non una
 * chat testuale. maintainer, 19/08: "ma deve corrispondere al modello usato
 * nella chiamata" + "io non dicevo una chat ma simulare la chiamata voce
 * con un tastino sul pannello".
 *
 * Il modello vocale non e' raggiungibile dall'API di completamento
 * testuale (verificato localmente: 400 "Model not found" sia per
 * grok-voice-fast-1.0 sia per grok-voice-latest) - esiste solo dietro
 * l'API realtime a WebSocket, quindi qui si parla davvero con quella,
 * non con un sostituto.
 */
function SimulateVoiceCall({ open, onClose, projectId, promptA }) {
  const [status, setStatus] = useState('idle') // idle | connecting | live | error | ended
  const [error, setError] = useState(null)
  const [transcript, setTranscript] = useState([])
  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const streamRef = useRef(null)
  const processorRef = useRef(null)
  const playheadRef = useRef(0)

  const cleanup = useCallback(() => {
    processorRef.current?.disconnect()
    processorRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close()
    }
    audioContextRef.current = null
    if (wsRef.current && wsRef.current.readyState <= 1) {
      wsRef.current.close()
    }
    wsRef.current = null
    playheadRef.current = 0
  }, [])

  const playChunk = useCallback((base64Audio) => {
    const ctx = audioContextRef.current
    if (!ctx) return
    const int16 = int16FromBase64(base64Audio)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff)

    const buffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE)
    buffer.copyToChannel(float32, 0)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)

    const now = ctx.currentTime
    const startAt = Math.max(now, playheadRef.current)
    source.start(startAt)
    playheadRef.current = startAt + buffer.duration
  }, [])

  const start = useCallback(async () => {
    setStatus('connecting')
    setError(null)
    setTranscript([])
    playheadRef.current = 0

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE })
      audioContextRef.current = audioContext

      const token = localStorage.getItem('accessToken')
      const ws = new WebSocket(buildWsUrl(`/ws/projects/${projectId}/simulate-voice?token=${encodeURIComponent(token)}`))
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'start', instructions: promptA }))
      }

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.type === 'ascolta.ready') {
          setStatus('live')
          // Avvia la cattura microfono solo ora che la sessione e' pronta.
          const source = audioContext.createMediaStreamSource(stream)
          const processor = audioContext.createScriptProcessor(4096, 1, 1)
          processorRef.current = processor
          processor.onaudioprocess = (e) => {
            const input = e.inputBuffer.getChannelData(0)
            const int16 = floatTo16BitPCM(input)
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                type: 'input_audio_buffer.append',
                audio: base64FromInt16(int16),
              }))
            }
          }
          source.connect(processor)
          processor.connect(audioContext.destination)
          return
        }
        if (msg.type === 'response.output_audio.delta' && msg.delta) {
          playChunk(msg.delta)
          return
        }
        if (msg.type === 'conversation.item.input_audio_transcription.completed') {
          setTranscript((prev) => [...prev, { role: 'user', content: msg.transcript || '' }])
          return
        }
        if (msg.type === 'response.output_audio_transcript.done') {
          setTranscript((prev) => [...prev, { role: 'assistant', content: msg.transcript || '' }])
        }
      }

      ws.onerror = () => {
        setError('Errore di connessione alla simulazione vocale')
        setStatus('error')
        cleanup()
      }

      ws.onclose = (event) => {
        if (status === 'live' || status === 'connecting') {
          if (event.code >= 4400) {
            setError(event.reason || 'Connessione rifiutata')
            setStatus('error')
          } else {
            setStatus('ended')
          }
        }
      }
    } catch (err) {
      setError(err.message || 'Impossibile accedere al microfono')
      setStatus('error')
      cleanup()
    }
  }, [projectId, promptA, playChunk, cleanup, status])

  const stop = useCallback(() => {
    cleanup()
    setStatus('ended')
  }, [cleanup])

  const handleClose = () => {
    cleanup()
    setStatus('idle')
    onClose()
  }

  return (
    <Modal title="Prova la chiamata vocale" open={open} onCancel={handleClose} footer={null} width={520}>
      <Alert
        type="info"
        showIcon
        message="Modello vocale reale (grok-voice-latest), non un sostituto testuale"
        description="Usa il microfono del browser e il prompt attuale nell'editor (anche non salvato). Non ha accesso alla knowledge base ne' agli altri strumenti - solo il ragionamento vocale del prompt."
        style={{ marginBottom: 16 }}
      />

      <div style={{ textAlign: 'center', marginBottom: 16 }}>
        {status === 'idle' && (
          <Button type="primary" size="large" icon={<PhoneOutlined />} onClick={start}>
            Avvia chiamata di prova
          </Button>
        )}
        {status === 'connecting' && <Tag icon={<AudioOutlined />} color="processing">Connessione in corso...</Tag>}
        {status === 'live' && (
          <Space direction="vertical" align="center">
            <Tag icon={<AudioOutlined />} color="green">In chiamata - parla pure</Tag>
            <Button danger icon={<StopOutlined />} onClick={stop}>Termina</Button>
          </Space>
        )}
        {status === 'ended' && (
          <Space direction="vertical" align="center">
            <Tag>Chiamata terminata</Tag>
            <Button icon={<PhoneOutlined />} onClick={start}>Richiama</Button>
          </Space>
        )}
        {status === 'error' && (
          <Space direction="vertical" align="center">
            <Alert type="error" message={error} />
            <Button icon={<PhoneOutlined />} onClick={start}>Riprova</Button>
          </Space>
        )}
      </div>

      {transcript.length > 0 && (
        <List
          size="small"
          dataSource={transcript}
          style={{ maxHeight: 240, overflowY: 'auto', border: `1px solid ${BRAND.border}`, borderRadius: 8, padding: 8 }}
          renderItem={(t) => (
            <List.Item style={{ border: 'none', padding: '4px 0' }}>
              <Text type="secondary" strong style={{ marginRight: 6 }}>
                {t.role === 'user' ? 'Tu:' : 'Agente:'}
              </Text>
              <Text>{t.content}</Text>
            </List.Item>
          )}
        />
      )}
    </Modal>
  )
}

export default SimulateVoiceCall
