import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import './App.css'

type ToolEvent = { ts: string; type: string; detail: string }
type Reminder = { id: string; title: string; remind_at: string }
type GatewayActionRequest = {
  action: string
  arguments: Record<string, unknown>
  confirmation_phrase?: string
}

const agentId = import.meta.env.VITE_ELEVENLABS_AGENT_ID
const gatewayUrl = import.meta.env.VITE_GATEWAY_URL ?? 'http://127.0.0.1:8765'
const localToken = import.meta.env.VITE_JARVIS_LOCAL_TOKEN

async function gatewayFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (localToken) headers.set('X-Jarvis-Token', localToken)
  const response = await fetch(`${gatewayUrl}${path}`, { ...init, headers })
  const payload = (await response.json()) as T & { ok?: boolean; error?: unknown }
  if (!response.ok || payload.ok === false) throw new Error(JSON.stringify(payload.error ?? payload))
  return payload
}

async function gatewayAction(request: GatewayActionRequest): Promise<string> {
  return JSON.stringify(await gatewayFetch('/action', { method: 'POST', body: JSON.stringify(request) }))
}

type SpeechRecognitionInstance = {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: () => void
  stop: () => void
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error?: string }) => void) | null
}

function ConversationPanel() {
  const [events, setEvents] = useState<ToolEvent[]>([])
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [micNotice, setMicNotice] = useState('Activa el micrófono para usar “Jarvis, despierta”.')
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [dueAlerts, setDueAlerts] = useState<Reminder[]>([])
  const [wakeEnabled, setWakeEnabled] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const wakeEnabledRef = useRef(false)
  const restartingRecognitionRef = useRef(false)
  const { startSession, endSession, status, mode, isListening, isSpeaking, message } = useConversation({
    onMessage: (incoming) => setTranscript(JSON.stringify(incoming)),
    onAgentToolRequest: (evt) =>
      setEvents((prev) => [{ ts: new Date().toISOString(), type: 'tool_request', detail: JSON.stringify(evt) }, ...prev]),
    onAgentToolResponse: (evt) =>
      setEvents((prev) => [{ ts: new Date().toISOString(), type: 'tool_response', detail: JSON.stringify(evt) }, ...prev]),
    onError: (msg) => setError(msg),
  })

  const notifyDueReminders = useCallback(async () => {
    try {
      const [duePayload, upcomingPayload] = await Promise.all([
        gatewayFetch<{ reminders: Reminder[] }>('/reminders/due'),
        gatewayFetch<{ reminders: Reminder[] }>('/reminders/upcoming'),
      ])
      setReminders(upcomingPayload.reminders)
      setDueAlerts((current) => {
        const known = new Set(current.map((reminder) => reminder.id))
        return [...current, ...duePayload.reminders.filter((reminder) => !known.has(reminder.id))]
      })
      duePayload.reminders.forEach((reminder) => {
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('JARVIS · Recordatorio', { body: reminder.title })
        }
        void gatewayFetch(`/reminders/${reminder.id}/delivered`, { method: 'POST' })
      })
    } catch {
      // The connection indicator and gateway errors remain the source of truth.
    }
  }, [])

  useEffect(() => {
    void notifyDueReminders()
    const timer = window.setInterval(() => void notifyDueReminders(), 15000)
    return () => window.clearInterval(timer)
  }, [notifyDueReminders])

  const startWakeWord = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((track) => track.stop())
      if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission()
      const speechWindow = window as Window & {
        SpeechRecognition?: new () => SpeechRecognitionInstance
        webkitSpeechRecognition?: new () => SpeechRecognitionInstance
      }
      const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition
      if (!Recognition) {
        setMicNotice('El navegador no ofrece escucha continua; usa Iniciar conversación.')
        return
      }
      const recognition = new Recognition()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = 'es-CO'
      recognition.onresult = (event) => {
        const text = Array.from(event.results, (result) => result[0]?.transcript ?? '').join(' ').toLowerCase()
        if (text.includes('jarvis despierta') || text.includes('jarvis, despierta')) {
          setError(null)
          if (status !== 'connected' && status !== 'connecting') void startSession()
        }
      }
      recognition.onend = () => {
        if (!wakeEnabledRef.current || restartingRecognitionRef.current) return
        restartingRecognitionRef.current = true
        window.setTimeout(() => {
          restartingRecognitionRef.current = false
          if (!wakeEnabledRef.current) return
          try {
            recognition.start()
            setMicNotice('Escuchando “Jarvis, despierta”.')
          } catch {
            setMicNotice('El navegador pausó la escucha. Pulsa Activar micrófono para reanudarla.')
            wakeEnabledRef.current = false
            setWakeEnabled(false)
          }
        }
        , 250)
      }
      recognition.onerror = (event) => {
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          wakeEnabledRef.current = false
          setWakeEnabled(false)
          setMicNotice('El micrófono fue bloqueado. Permítelo para este sitio y vuelve a intentarlo.')
          return
        }
        if (event.error === 'audio-capture') {
          wakeEnabledRef.current = false
          setWakeEnabled(false)
          setMicNotice('No se encontró un micrófono disponible.')
          return
        }
        if (event.error !== 'aborted') {
          setMicNotice('La escucha se reiniciará automáticamente.')
        }
      }
      recognitionRef.current = recognition
      wakeEnabledRef.current = true
      setWakeEnabled(true)
      recognition.start()
      setMicNotice('Escuchando “Jarvis, despierta”. El navegador puede requerir interacción periódica.')
    } catch (err) {
      wakeEnabledRef.current = false
      setWakeEnabled(false)
      setError(err instanceof Error ? err.message : 'No se pudo obtener el micrófono')
    }
  }

  const stopWakeWord = () => {
    wakeEnabledRef.current = false
    setWakeEnabled(false)
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setMicNotice('Escucha en espera.')
  }

  const startConversationNow = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((track) => track.stop())
      setError(null)
      await startSession()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo iniciar la conversación')
    }
  }

  const listeningState = isListening || mode === 'listening'
  const speakingState = isSpeaking || mode === 'speaking'

  return (
    <main className={`app-shell ${speakingState ? 'is-speaking' : ''} ${listeningState ? 'is-listening' : ''}`}>
      <div className="ambient ambient-one" /><div className="ambient ambient-two" />
      <header className="hero">
        <div><span className="eyebrow">PERSONAL VOICE OS · LOCAL FIRST</span><h1>JARVIS<span className="dot">.</span></h1><p>Tu asistente, con memoria práctica y control humano.</p></div>
        <div className="status-pill"><span className={`status-dot ${status === 'connected' ? 'online' : ''}`} />{status}</div>
      </header>
      <section className="orb-card">
        <div className="orb"><span /><span /><span /></div>
        <div className="voice-copy"><strong>{speakingState ? 'JARVIS está hablando' : listeningState ? 'Te estoy escuchando' : wakeEnabled ? 'Di “Jarvis, despierta”' : 'Listo cuando tú quieras'}</strong><small>{micNotice}</small></div>
      </section>
      <section className="control-row">
        <button className="primary" type="button" onClick={() => void startWakeWord()} disabled={wakeEnabled}>Activar micrófono</button>
        <button type="button" onClick={() => void startConversationNow()} disabled={status === 'connected' || status === 'connecting'}>Hablar ahora</button>
        <button type="button" onClick={() => { stopWakeWord(); void endSession() }}>Detener</button>
        <button type="button" className="emergency" onClick={() => { stopWakeWord(); void endSession() }}>Emergencia</button>
      </section>
      {error && <p className="error">{error}</p>}
      {dueAlerts.length > 0 && <aside className="reminder-alert" role="alert"><strong>✦ Recordatorio de JARVIS</strong>{dueAlerts.map((reminder) => <div key={reminder.id}>{reminder.title}</div>)}<button type="button" onClick={() => setDueAlerts([])}>Entendido</button></aside>}
      <section className="dashboard-grid">
        <article className="panel"><div className="panel-heading"><span>Recordatorios</span><span className="count">{reminders.length}</span></div><p className="muted">Los recordatorios creados por voz aparecerán aquí y dispararán un popup.</p>{reminders.length ? <ul className="reminder-list">{reminders.map((reminder) => <li key={reminder.id}><span className="reminder-icon">✦</span><div><strong>{reminder.title}</strong><small>{new Date(reminder.remind_at).toLocaleString()}</small></div></li>)}</ul> : <div className="empty">No hay recordatorios pendientes.</div>}</article>
        <article className="panel"><div className="panel-heading"><span>Estado de sesión</span><span className="live">● LIVE</span></div><div className="metrics"><div><span>Escucha</span><strong>{listeningState ? 'Activa' : 'En espera'}</strong></div><div><span>Respuesta</span><strong>{speakingState ? 'Hablando' : 'Silencio'}</strong></div></div><div className="transcript">{message ?? transcript ?? 'La transcripción aparecerá durante la conversación.'}</div></article>
      </section>
      <section className="panel events-panel"><div className="panel-heading"><span>Actividad reciente</span><span className="muted">{events.length} eventos</span></div>{events.slice(0, 4).map((event) => <div className="event" key={`${event.ts}-${event.type}`}><span>{event.type}</span><small>{new Date(event.ts).toLocaleTimeString()}</small></div>)}</section>
      <p className="footer-note">Privacidad local · sin shell arbitrario · confirmación antes de acciones sensibles</p>
    </main>
  )
}

function MissingConfiguration() {
  return <main className="app-shell"><section className="panel"><span className="eyebrow">CONFIGURACIÓN</span><h1>JARVIS<span className="dot">.</span></h1><p className="error">Falta VITE_ELEVENLABS_AGENT_ID en apps/desktop/.env.</p></section></main>
}

function App() {
  const clientTools = useMemo(() => ({ gateway_action: async (params: GatewayActionRequest) => gatewayAction(params) }), [])
  if (!agentId) return <MissingConfiguration />
  return <ConversationProvider agentId={agentId} clientTools={clientTools}><ConversationPanel /></ConversationProvider>
}

export default App
