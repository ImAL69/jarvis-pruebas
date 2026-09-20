import { useMemo, useState } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import './App.css'

type ToolEvent = {
  ts: string
  type: string
  detail: string
}

type GatewayActionRequest = {
  action: string
  arguments: Record<string, unknown>
  confirmation_phrase?: string
}

const agentId = import.meta.env.VITE_ELEVENLABS_AGENT_ID
const gatewayUrl = import.meta.env.VITE_GATEWAY_URL ?? 'http://127.0.0.1:8765'
const localToken = import.meta.env.VITE_JARVIS_LOCAL_TOKEN

async function gatewayAction(request: GatewayActionRequest): Promise<string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (localToken) {
    headers['X-Jarvis-Token'] = localToken
  }

  const response = await fetch(`${gatewayUrl}/action`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  })

  const payload = (await response.json()) as Record<string, unknown>
  if (!response.ok || payload.ok === false) {
    throw new Error(JSON.stringify(payload))
  }
  return JSON.stringify(payload)
}

function ConversationPanel() {
  const [events, setEvents] = useState<ToolEvent[]>([])
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [micNotice, setMicNotice] = useState<string>('')

  const { startSession, endSession, status, mode, isListening, isSpeaking, message } = useConversation({
    onMessage: (incoming) => {
      setTranscript(JSON.stringify(incoming))
    },
    onAgentToolRequest: (evt) => {
      setEvents((prev) => [
        { ts: new Date().toISOString(), type: 'tool_request', detail: JSON.stringify(evt) },
        ...prev,
      ])
    },
    onAgentToolResponse: (evt) => {
      setEvents((prev) => [
        { ts: new Date().toISOString(), type: 'tool_response', detail: JSON.stringify(evt) },
        ...prev,
      ])
    },
    onError: (msg) => {
      setError(msg)
    },
  })

  const listeningState = isListening || mode === 'listening'
  const speakingState = isSpeaking || mode === 'speaking'

  const canStart = status !== 'connected' && status !== 'connecting'

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((track) => track.stop())
      setMicNotice('Permiso de micrófono concedido para esta sesión.')
      setError(null)
      startSession()
    } catch (err) {
      const messageError = err instanceof Error ? err.message : 'No se pudo obtener el micrófono'
      setError(messageError)
    }
  }

  return (
    <div className="container">
      <h1>JARVIS (base local)</h1>
      <p>Conexión: {status}</p>
      <p>
        Escuchando: {listeningState ? 'sí' : 'no'} | Hablando: {speakingState ? 'sí' : 'no'}
      </p>
      <div className="actions">
        <button type="button" onClick={start} disabled={!canStart}>
          Iniciar conversación
        </button>
        <button type="button" onClick={() => endSession()}>
          Detener conversación
        </button>
        <button type="button" className="emergency" onClick={() => endSession()}>
          Emergencia: detener sesión
        </button>
      </div>
      {micNotice ? <p>{micNotice}</p> : null}
      {error ? <p className="error">Error: {error}</p> : null}
      <section>
        <h2>Transcripción (solo memoria)</h2>
        <pre>{message ?? transcript}</pre>
      </section>
      <section>
        <h2>Eventos de herramientas</h2>
        <ul>
          {events.map((event) => (
            <li key={`${event.ts}-${event.type}`}>
              <strong>{event.type}</strong> <small>{event.ts}</small>
              <pre>{event.detail}</pre>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function MissingConfiguration() {
  return (
    <div className="container">
      <h1>JARVIS (base local)</h1>
      <p className="error">Falta VITE_ELEVENLABS_AGENT_ID en .env local del frontend.</p>
    </div>
  )
}

function App() {
  const clientTools = useMemo(
    () => ({
      gateway_action: async (params: GatewayActionRequest) => gatewayAction(params),
    }),
    [],
  )

  if (!agentId) {
    return <MissingConfiguration />
  }

  return (
    <ConversationProvider agentId={agentId} clientTools={clientTools}>
      <ConversationPanel />
    </ConversationProvider>
  )
}

export default App
