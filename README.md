# JARVIS - Base inicial segura

Base inicial de un asistente personal de voz JARVIS con:

- Gateway local seguro en FastAPI (`apps/gateway`).
- Interfaz local React + TypeScript + Vite (`apps/desktop`).
- Integración inicial con ElevenLabs ElevenAgents usando `@elevenlabs/react`.
- Abstracción MCP preparada para iteraciones futuras.

## Prompt inicial recomendado para el agente

> "Eres JARVIS, un asistente personal de voz. Responde en el idioma del usuario.
> Sé breve al hablar. Usa herramientas solo cuando sea necesario. Nunca inventes que
> una acción se ejecutó: espera el resultado. Prefiere herramientas de lectura.
> Antes de escribir, borrar, mover, enviar, abrir algo o cambiar configuración, explica
> la acción y solicita confirmación. No ejecutes shell arbitrario. No solicites,
> expongas ni almacenes contraseñas, tokens, cookies o claves privadas. Si una tool
> falla, informa el error claramente. Si falta información, formula una pregunta
> concreta."

## Requisitos

- Python 3.13 (fijado en `apps/gateway/pyproject.toml`)
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- npm 10+

## Estructura

- `apps/gateway`: API local para acciones permitidas, auditoría y capa MCP.
- `apps/desktop`: UI para iniciar/detener conversación y tool calls.
- `config/policy.example.yaml`: política de allowlist y límites.
- `config/mcp.example.json`: ejemplo de servidores MCP locales versionados.

## Configuración rápida

1. Copia `.env.example` en la raíz a `.env`.
2. Ajusta `JARVIS_ALLOWED_DIRS` con rutas absolutas permitidas.
3. Copia `apps/desktop/.env.example` a `apps/desktop/.env` y define `VITE_ELEVENLABS_AGENT_ID`.

## Ejecutar gateway (Linux/macOS)

```bash
cd apps/gateway
uv sync
uv run uvicorn jarvis_gateway.main:create_app --factory --host 127.0.0.1 --port 8765
```

## Ejecutar gateway (Windows PowerShell)

```powershell
cd apps/gateway
uv sync
uv run uvicorn jarvis_gateway.main:create_app --factory --host 127.0.0.1 --port 8765
```

## Ejecutar frontend

```bash
cd apps/desktop
npm install
npm run dev
```

## Crear agente en ElevenLabs y client tool

1. Crear un agente en ElevenLabs.
2. Configurar `VITE_ELEVENLABS_AGENT_ID` en frontend.
3. Registrar client tool `gateway_action` con parámetros:
   - `action`
   - `arguments`
   - `confirmation_phrase` (opcional)
4. El frontend llama a `http://127.0.0.1:8765/action`.

> `VITE_ELEVENLABS_AGENT_ID` es solo identificador. Para agentes privados en producción,
> crear backend con signed URL; nunca poner API keys en frontend.

## API del gateway

- `GET /health`
- `GET /actions`
- `POST /action`
- `POST /confirm/{request_id}`

Acciones registradas:

- `get_time`
- `list_allowed_files`
- `create_note` (confirmación requerida)
- `open_url` (confirmación requerida)

## Seguridad aplicada

- Host fijado a `127.0.0.1`.
- Sin endpoint de shell arbitrario.
- Allowlist de directorios con validación anti-traversal y symlink escape.
- Confirmación de un solo uso con token efímero generado por gateway.
- Auditoría SQLite solo con metadatos saneados (sin contenido completo de notas ni secretos).
- CORS restringido al origen de desarrollo configurado.

## MCP: qué es y qué no es

MCP **no es un modelo de IA**: es un protocolo para conectar herramientas/servidores.
En esta iteración, `apps/gateway/src/jarvis_gateway/mcp_client.py` solo carga y valida
configuración local versionada (`config/mcp.json`) y deja conexión real pendiente.

## Próximos pasos

- Conectar cliente MCP real (STDIO/HTTP streamable) con allowlist por servidor.
- UX de confirmación humana explícita en frontend para `/confirm/{request_id}`.
- Firmado de sesión ElevenLabs vía backend para entornos productivos.
