# JARVIS Desktop (React)

UI local para conversar con ElevenLabs y reenviar `gateway_action` al gateway.

## Variables

Copiar `.env.example` a `.env` y configurar:

- `VITE_ELEVENLABS_AGENT_ID`: identificador del agente (no API key).
- `VITE_GATEWAY_URL`: URL local del gateway.
- `VITE_JARVIS_LOCAL_TOKEN`: token local opcional para desarrollo.

## Ejecución

```bash
npm install
npm run dev
```

Para producción con agentes privados, usar un backend que emita signed URLs; no exponer claves en frontend.
