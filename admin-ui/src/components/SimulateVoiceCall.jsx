import { useState, useRef, useCallback, useEffect } from 'react'
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
// Stesso limite imposto lato server (app/routers/simulate_voice.py::
// SIMULATION_SILENCE_TIMEOUT_SECONDS) - qui solo per mostrare il conto
// alla rovescia, il taglio effettivo lo fa il backend. maintainer, 19/08:
// "i 30 secondi di timeout devono scattare dopo 30s di silenzio" - non
// un limite sulla durata totale della prova, si azzera ad ogni attivita'.
const SILENCE_TIMEOUT_SECONDS = 30

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
function SimulateVoiceCall({ open, onClose, projectId, promptA, consentMessage }) {
  const [status, setStatus] = useState('idle') // idle | connecting | live | error | ended
  const [error, setError] = useState(null)
  const [transcript, setTranscript] = useState([])
  const [timedOut, setTimedOut] = useState(false)
  const [remainingSeconds, setRemainingSeconds] = useState(SILENCE_TIMEOUT_SECONDS)
  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const streamRef = useRef(null)
  const processorRef = useRef(null)
  const playheadRef = useRef(0)
  const transcriptEndRef = useRef(null)
  const countdownRef = useRef(null)
  const lastActivityRef = useRef(Date.now())

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [transcript])

  // xAI a volte manda lo stesso evento di trascrizione piu' volte per
  // la stessa frase (interim + finale con contenuto identico) - maintainer,
  // 19/08: "riporta due volte le mie frasi". Ignora una nuova riga
  // identica, stesso ruolo, a quella appena aggiunta.
  const appendTranscript = useCallback((role, content) => {
    if (!content) return
    setTranscript((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.role === role && last.content === content) return prev
      return [...prev, { role, content }]
    })
  }, [])

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
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
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
    setTimedOut(false)
    setRemainingSeconds(SILENCE_TIMEOUT_SECONDS)
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
        ws.send(JSON.stringify({ type: 'start', instructions: promptA, consent_message: consentMessage }))
      }

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        // Stesso criterio del backend (silence_watchdog in simulate_voice.py):
        // qualunque evento reale inoltrato da xAI conta come attivita' e
        // riazzera il conto alla rovescia - non e' un limite sulla durata
        // totale della prova. Esclusi i messaggi che il backend genera lui
        // stesso (ascolta.*), che non riflettono attivita' del modello.
        if (!msg.type?.startsWith('ascolta.')) {
          lastActivityRef.current = Date.now()
        }
        if (msg.type === 'ascolta.ready') {
          setStatus('live')
          lastActivityRef.current = Date.now()
          // Conto alla rovescia visibile per il timeout di inattivita'
          // lato server (maintainer, 19/08: "i 30 secondi di timeout devono
          // scattare dopo 30s di silenzio").
          countdownRef.current = setInterval(() => {
            const elapsed = Math.floor((Date.now() - lastActivityRef.current) / 1000)
            setRemainingSeconds(Math.max(0, SILENCE_TIMEOUT_SECONDS - elapsed))
          }, 1000)
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
          appendTranscript('user', msg.transcript || '')
          return
        }
        if (msg.type === 'response.output_audio_transcript.done') {
          appendTranscript('assistant', msg.transcript || '')
          return
        }
        if (msg.type === 'ascolta.tool_call') {
          // maintainer, 19/08: "potresti riportare la chiamata al tool e la
          // risposta" - visibile in trascrizione, non solo eseguita in
          // silenzio dal backend.
          setTranscript((prev) => [...prev, { role: 'tool', name: msg.name, arguments: msg.arguments, result: msg.result }])
          return
        }
        if (msg.type === 'ascolta.timeout') {
          // Il backend chiude la sessione subito dopo questo messaggio -
          // segna il motivo cosi' onclose mostra "limite raggiunto"
          // invece del generico "chiamata terminata".
          setTimedOut(true)
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
  }, [projectId, promptA, consentMessage, playChunk, cleanup, status, appendTranscript])

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
    <Modal title="Prova la chiamata vocale" open={open} onCancel={handleClose} footer={null} width="min(520px, 92vw)">
      <Alert
        type="info"
        showIcon
        message="Modello vocale reale (grok-voice-latest), non un sostituto testuale"
        description={`Usa il microfono del browser e il prompt attuale nell'editor (anche non salvato), con accesso alla knowledge base del progetto. Non ha accesso agli altri strumenti (Cal.com, ecc.). Si chiude automaticamente dopo ${SILENCE_TIMEOUT_SECONDS} secondi di silenzio.`}
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
            <Text type="secondary">Timeout inattività tra: {remainingSeconds}s</Text>
            <Button danger icon={<StopOutlined />} onClick={stop}>Termina</Button>
          </Space>
        )}
        {status === 'ended' && (
          <Space direction="vertical" align="center">
            <Tag>{timedOut ? `Chiamata terminata - ${SILENCE_TIMEOUT_SECONDS}s di silenzio` : 'Chiamata terminata'}</Tag>
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
        <div style={{ maxHeight: 240, overflowY: 'auto', border: `1px solid ${BRAND.border}`, borderRadius: 8, padding: 8 }}>
          <List
            size="small"
            dataSource={transcript}
            renderItem={(t) => (
              <List.Item style={{ border: 'none', padding: '4px 0' }}>
                {t.role === 'tool' ? (
                  <Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    🔧 {t.name}({JSON.stringify(t.arguments)}) → {t.result?.status}
                    {t.result?.results?.length ? ` (${t.result.results.length} risultati)` : ''}
                  </Text>
                ) : (
                  // List.Item e' un flex container: senza un wrapper i due
                  // <Text> diventano flex item indipendenti e, se stretti,
                  // l'etichetta si comprime lettera per lettera invece di
                  // restare su una riga (maintainer, "agente è scritto tutto
                  // spezzato" + "i label a sinistra non hanno spazio").
                  <div style={{ display: 'flex', gap: 6, width: '100%' }}>
                    <Text type="secondary" strong style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
                      {t.role === 'user' ? 'Tu:' : 'Agente:'}
                    </Text>
                    <Text style={{ minWidth: 0 }}>{t.content}</Text>
                  </div>
                )}
              </List.Item>
            )}
          />
          <div ref={transcriptEndRef} />
        </div>
      )}
    </Modal>
  )
}

export default SimulateVoiceCall
