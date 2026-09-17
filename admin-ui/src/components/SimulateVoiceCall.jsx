import { useState, useRef, useCallback, useEffect } from 'react'
import { Modal, Button, Space, Typography, Alert, Tag, List } from 'antd'
import { AudioOutlined, PhoneOutlined, StopOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
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

const XAI_SAMPLE_RATE = 24000
const ELEVEN_SAMPLE_RATE = 16000
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

function int16ToFloat32(int16) {
  const float32 = new Float32Array(int16.length)
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff)
  }
  return float32
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
function SimulateVoiceCall({ open, onClose, projectId, promptA, consentMessage, voiceEngine }) {
  const { t: translate } = useTranslation()
  const [status, setStatus] = useState('idle') // idle | connecting | live | error | ended
  const [error, setError] = useState(null)
  const [transcript, setTranscript] = useState([])
  const [timedOut, setTimedOut] = useState(false)
  const [remainingSeconds, setRemainingSeconds] = useState(SILENCE_TIMEOUT_SECONDS)
  const elevenConversationIdRef = useRef(null)
  const elevenToolTraceRef = useRef(new Set())
  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const streamRef = useRef(null)
  const processorRef = useRef(null)
  const mutedMicSinkRef = useRef(null)
  const playheadRef = useRef(0)
  const activePlaybackSourcesRef = useRef(new Set())
  const transcriptEndRef = useRef(null)
  const countdownRef = useRef(null)
  const elevenToolTracePollRef = useRef(null)
  const lastActivityRef = useRef(Date.now())
  const isXaiVoiceSimulation = !voiceEngine || voiceEngine === 'xai_sip_direct'
  const isElevenVoiceSimulation = voiceEngine === 'elevenlabs_agent'
  const isSupportedVoiceSimulation = isXaiVoiceSimulation || isElevenVoiceSimulation

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
      // xAI can emit consecutive completed ASR items while the same user
      // turn is still being assembled. Keep one visible line and show the
      // latest recognition instead of rendering every partial fragment.
      if (role === 'user' && last && last.role === 'user') {
        if (last.content === content) return prev
        return [...prev.slice(0, -1), { ...last, content }]
      }
      if (last && last.role === role && last.content === content) return prev
      return [...prev, { role, content }]
    })
  }, [])

  const cleanup = useCallback(() => {
    processorRef.current?.disconnect()
    processorRef.current = null
    mutedMicSinkRef.current?.disconnect()
    mutedMicSinkRef.current = null
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
    activePlaybackSourcesRef.current.forEach((source) => source.stop())
    activePlaybackSourcesRef.current.clear()
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    if (elevenToolTracePollRef.current) {
      clearInterval(elevenToolTracePollRef.current)
      elevenToolTracePollRef.current = null
    }
  }, [])

  const refreshElevenToolTrace = useCallback(async () => {
    const conversationId = elevenConversationIdRef.current
    if (!conversationId || !isElevenVoiceSimulation) return
    const token = localStorage.getItem('accessToken')
    try {
      const response = await fetch(`/api/elevenlabs/projects/${projectId}/conversations/${encodeURIComponent(conversationId)}/tool-trace`, {
        headers: { Authorization: token ? `Bearer ${token}` : '' },
      })
      if (!response.ok) return
      const body = await response.json()
      for (const toolCall of body.tool_calls || []) {
        const key = toolCall.request_id || JSON.stringify(toolCall)
        if (elevenToolTraceRef.current.has(key)) continue
        elevenToolTraceRef.current.add(key)
        const result = toolCall.result?.result || toolCall.result || {}
        setTranscript((prev) => [...prev, {
          role: 'tool',
          name: toolCall.name || 'tool',
          arguments: toolCall.arguments || {},
          result: {
            status: result.status || toolCall.status || 'ok',
            results: result.results || [],
          },
        }])
      }
    } catch {
      // A trace is diagnostic UI only; it must not interrupt the call.
    }
  }, [isElevenVoiceSimulation, projectId])

  const playChunk = useCallback((base64Audio) => {
    const ctx = audioContextRef.current
    if (!ctx) return
    const int16 = int16FromBase64(base64Audio)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff)

    const buffer = ctx.createBuffer(1, float32.length, ctx.sampleRate || XAI_SAMPLE_RATE)
    buffer.copyToChannel(float32, 0)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)

    const now = ctx.currentTime
    const startAt = Math.max(now, playheadRef.current)
    activePlaybackSourcesRef.current.add(source)
    source.onended = () => activePlaybackSourcesRef.current.delete(source)
    source.start(startAt)
    playheadRef.current = startAt + buffer.duration
  }, [])

  const stopAgentPlayback = useCallback(() => {
    activePlaybackSourcesRef.current.forEach((source) => source.stop())
    activePlaybackSourcesRef.current.clear()
    playheadRef.current = audioContextRef.current?.currentTime || 0
  }, [])

  const start = useCallback(async () => {
    setStatus('connecting')
    setError(null)
    setTranscript([])
    setTimedOut(false)
    setRemainingSeconds(SILENCE_TIMEOUT_SECONDS)
    elevenToolTraceRef.current.clear()
    playheadRef.current = 0

    if (!isSupportedVoiceSimulation) {
      setError(translate('simulateVoice.engineNotAvailable', { engine: voiceEngine }))
      setStatus('error')
      return
    }

    try {
      // Avoid re-transcribing the agent audio played through speakers as user input.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream

      const sampleRate = isElevenVoiceSimulation ? ELEVEN_SAMPLE_RATE : XAI_SAMPLE_RATE
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate })
      audioContextRef.current = audioContext

      let ws
      if (isElevenVoiceSimulation) {
        const token = localStorage.getItem('accessToken')
        const response = await fetch(`/api/elevenlabs/projects/${projectId}/signed-url`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: token ? `Bearer ${token}` : '',
          },
        })
        const body = await response.json().catch(() => ({}))
        if (!response.ok || !body?.signed_url) {
          throw new Error(body?.detail || translate('simulateVoice.cannotOpenElevenSession'))
        }
        elevenConversationIdRef.current = body.conversation_id || null
        ws = new WebSocket(body.signed_url)
      } else {
        const token = localStorage.getItem('accessToken')
        ws = new WebSocket(buildWsUrl(`/ws/projects/${projectId}/simulate-voice?token=${encodeURIComponent(token)}`))
      }
      wsRef.current = ws

      ws.onopen = () => {
        if (isElevenVoiceSimulation) {
          // Eleven must use its provisioned agent configuration exactly:
          // it contains the webhook tools, V3 voice and the production
          // prompt. Overriding the prompt here made the browser preview
          // differ from the real Eleven phone agent.
          ws.send(JSON.stringify({ type: 'conversation_initiation_client_data' }))
          return
        }
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
          const mutedMicSink = audioContext.createGain()
          mutedMicSink.gain.value = 0
          processorRef.current = processor
          mutedMicSinkRef.current = mutedMicSink
          processor.onaudioprocess = (e) => {
            const input = e.inputBuffer.getChannelData(0)
            const int16 = floatTo16BitPCM(input)
            if (ws.readyState !== WebSocket.OPEN) return
            ws.send(JSON.stringify({
              type: 'input_audio_buffer.append',
              audio: base64FromInt16(int16),
            }))
          }
          source.connect(processor)
          // ScriptProcessor deve restare collegato per ricevere i frame,
          // ma il ritorno microfono e' silenziato: mai rimandarlo alle casse.
          processor.connect(mutedMicSink)
          mutedMicSink.connect(audioContext.destination)
          return
        }
        if (msg.type === 'conversation_initiation_metadata') {
          elevenConversationIdRef.current = msg.conversation_initiation_metadata_event?.conversation_id
            || msg.conversation_id
            || elevenConversationIdRef.current
          setStatus('live')
          lastActivityRef.current = Date.now()
          countdownRef.current = setInterval(() => {
            const elapsed = Math.floor((Date.now() - lastActivityRef.current) / 1000)
            if (elapsed >= SILENCE_TIMEOUT_SECONDS) {
              ws.close()
              setTimedOut(true)
              setStatus('ended')
              return
            }
            setRemainingSeconds(Math.max(0, SILENCE_TIMEOUT_SECONDS - elapsed))
          }, 1000)
          // Eleven executes webhooks server-to-server, so no websocket
          // event reaches the browser at dispatch time. Poll its official
          // conversation trace while the test is live to show the real tool
          // result before the agent's follow-up answer arrives.
          elevenToolTracePollRef.current = setInterval(refreshElevenToolTrace, 2000)
          refreshElevenToolTrace()

          const source = audioContext.createMediaStreamSource(stream)
          const processor = audioContext.createScriptProcessor(4096, 1, 1)
          const mutedMicSink = audioContext.createGain()
          mutedMicSink.gain.value = 0
          processorRef.current = processor
          mutedMicSinkRef.current = mutedMicSink
          processor.onaudioprocess = (e) => {
            const input = e.inputBuffer.getChannelData(0)
            const int16 = floatTo16BitPCM(input)
            if (ws.readyState !== WebSocket.OPEN) return
            ws.send(JSON.stringify({ user_audio_chunk: base64FromInt16(int16) }))
          }
          source.connect(processor)
          processor.connect(mutedMicSink)
          mutedMicSink.connect(audioContext.destination)
          return
        }
        if (msg.type === 'response.output_audio.delta' && msg.delta) {
          playChunk(msg.delta)
          return
        }
        if (msg.type === 'audio' && msg.audio_event?.audio_base_64) {
          playChunk(msg.audio_event.audio_base_64)
          return
        }
        if (msg.type === 'conversation.item.input_audio_transcription.completed') {
          appendTranscript('user', msg.transcript || '')
          return
        }
        if (msg.type === 'user_transcript') {
          appendTranscript('user', msg.user_transcription_event?.user_transcript || '')
          return
        }
        if (msg.type === 'response.output_audio_transcript.done') {
          appendTranscript('assistant', msg.transcript || '')
          return
        }
        if (msg.type === 'agent_response') {
          appendTranscript('assistant', msg.agent_response_event?.agent_response || '')
          refreshElevenToolTrace()
          return
        }
        if (msg.type === 'interruption') {
          // Il server ha riconosciuto che l'utente ha iniziato a parlare.
          // Ferma anche i chunk gia' accodati nel browser: il microfono
          // resta sempre attivo e il barge-in segue l'agente reale.
          stopAgentPlayback()
          return
        }
        if (msg.type === 'agent_tool_response_full_payload') {
          const tool = msg.agent_tool_response_full_payload || {}
          let result = tool.full_tool_result
          try {
            result = typeof result === 'string' ? JSON.parse(result) : result
          } catch {
            result = { status: tool.is_error ? 'error' : 'ok' }
          }
          const key = tool.tool_call_id || `${tool.tool_name}:${JSON.stringify(result)}`
          if (!elevenToolTraceRef.current.has(key)) {
            elevenToolTraceRef.current.add(key)
            const nested = result?.result || result || {}
            setTranscript((prev) => [...prev, {
              role: 'tool',
              name: tool.tool_name || 'tool',
              arguments: tool.parameters || {},
              result: {
                status: nested.status || (tool.is_error ? 'error' : 'ok'),
                results: nested.results || [],
              },
            }])
          }
          return
        }
        if (msg.type === 'agent_tool_response') {
          // Il payload completo puo' arrivare subito dopo questo evento.
          // Aggiorna comunque il trace, che contiene il risultato canonico.
          refreshElevenToolTrace()
          return
        }
        if (msg.type === 'ping' && msg.ping_event?.event_id && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'pong', event_id: msg.ping_event.event_id }))
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

      // Il browser emette spesso error prima di close: per i rifiuti del
      // backend il motivo utile arriva su close.reason, quindi non
      // sovrascriverlo con il messaggio generico.
      ws.onerror = () => {}

      ws.onclose = (event) => {
        // Eleven may publish the final webhook trace only after it closes
        // the conversation. Keep the id through cleanup and fetch once
        // more, so ending a test cannot hide its final tool result.
        if (isElevenVoiceSimulation) {
          window.setTimeout(refreshElevenToolTrace, 1200)
        }
        if (status === 'live' || status === 'connecting') {
          if (event.code >= 4400) {
            setError(event.reason || translate('simulateVoice.connectionRefused'))
            setStatus('error')
          } else {
            setError(translate('simulateVoice.simulationConnectionError'))
            setStatus('error')
          }
        }
      }
    } catch (err) {
      setError(err.message || translate('simulateVoice.micAccessError'))
      setStatus('error')
      cleanup()
    }
  }, [projectId, promptA, consentMessage, playChunk, stopAgentPlayback, cleanup, status, appendTranscript, isElevenVoiceSimulation, isSupportedVoiceSimulation, voiceEngine, refreshElevenToolTrace])

  const stop = useCallback(() => {
    cleanup()
    setStatus('ended')
    if (isElevenVoiceSimulation) {
      window.setTimeout(refreshElevenToolTrace, 1200)
      window.setTimeout(refreshElevenToolTrace, 2600)
    }
  }, [cleanup, isElevenVoiceSimulation, refreshElevenToolTrace])

  const handleClose = () => {
    cleanup()
    setStatus('idle')
    onClose()
  }

  return (
    <Modal title={translate('simulateVoice.tryVoiceCall')} open={open} onCancel={handleClose} footer={null} width="min(520px, 92vw)">
      <Alert
        type="info"
        showIcon
        message={!isSupportedVoiceSimulation
          ? translate('simulateVoice.voiceTestUnavailable')
          : isElevenVoiceSimulation
          ? translate('simulateVoice.realElevenEngine')
          : translate('simulateVoice.realXaiEngine')}
        description={!isSupportedVoiceSimulation
          ? translate('simulateVoice.openaiEngineNote')
          : isElevenVoiceSimulation
          ? translate('simulateVoice.elevenDescription', { seconds: SILENCE_TIMEOUT_SECONDS })
          : translate('simulateVoice.xaiDescription', { seconds: SILENCE_TIMEOUT_SECONDS })}
        style={{ marginBottom: 16 }}
      />

      <div style={{ textAlign: 'center', marginBottom: 16 }}>
        {status === 'idle' && (
          <Button type="primary" size="large" icon={<PhoneOutlined />} onClick={start}>
            {translate('simulateVoice.startTestCall')}
          </Button>
        )}
        {status === 'connecting' && <Tag icon={<AudioOutlined />} color="processing">{translate('simulateVoice.connecting')}</Tag>}
        {status === 'live' && (
          <Space direction="vertical" align="center">
            <Tag icon={<AudioOutlined />} color="green">{translate('simulateVoice.inCallSpeak')}</Tag>
            <Text type="secondary">{translate('simulateVoice.inactivityTimeout', { seconds: remainingSeconds })}</Text>
            <Button danger icon={<StopOutlined />} onClick={stop}>{translate('simulateVoice.end')}</Button>
          </Space>
        )}
        {status === 'ended' && (
          <Space direction="vertical" align="center">
            <Tag>{timedOut ? translate('simulateVoice.callEndedSilence', { seconds: SILENCE_TIMEOUT_SECONDS }) : translate('simulateVoice.callEnded')}</Tag>
            <Button icon={<PhoneOutlined />} onClick={start}>{translate('simulateVoice.callBack')}</Button>
          </Space>
        )}
        {status === 'error' && (
          <Space direction="vertical" align="center">
            <Alert type="error" message={error} />
            <Button icon={<PhoneOutlined />} onClick={start}>{translate('simulateVoice.retry')}</Button>
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
                    {t.result?.results?.length
                      ? ` (${translate('simulateChat.results', { count: t.result.results.length })})`
                      : ''}
                  </Text>
                ) : (
                  // List.Item e' un flex container: senza un wrapper i due
                  // <Text> diventano flex item indipendenti e, se stretti,
                  // l'etichetta si comprime lettera per lettera invece di
                  // restare su una riga (maintainer, "agente è scritto tutto
                  // spezzato" + "i label a sinistra non hanno spazio").
                  <div style={{ display: 'flex', gap: 6, width: '100%' }}>
                    <Text type="secondary" strong style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
                      {t.role === 'user' ? translate('simulateVoice.you') : translate('simulateVoice.agent')}
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
