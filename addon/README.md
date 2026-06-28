# Add-on: matching bidireccional + WhatsApp

Add-on **desacoplado** que vive en `addon/` y reusa la infraestructura de `app/`
(misma DB Postgres + pgvector, mismo `MatchingPolicy`, mismas tablas
`personas` / `persona_embeddings`). No duplica la lógica de reconocimiento facial.

## Qué resuelve

El sistema base ya hace match cruzado **en vivo**:
- `POST /buscados` (familiar) guarda a la persona buscada y busca entre las encontradas.
- `POST /encontrados` (rescatista) busca entre las buscadas y devuelve `AlertaFamiliar`.

Este add-on agrega lo que faltaba:

1. **Persistencia de matches** — tabla `coincidencias` (par buscada↔encontrada + estado de aviso). Evita re-notificar y deja auditoría.
2. **Botón "Contactar"** para el rescatista — link `wa.me` pre-armado (sin API, sin costo).
3. **Cron nocturno** — barre toda la base, detecta matches nuevos y **avisa a la familia por WhatsApp** vía **Evolution API**.

## Componentes

| Archivo | Rol |
|---|---|
| `config.py` | `AddonSettings` (Evolution API, país por defecto, umbrales de aviso). |
| `db.py` | Crea la tabla `coincidencias` (idempotente). |
| `whatsapp.py` | `wa.me` link (botón) + `EvolutionClient` (cron) + textos de mensajes. |
| `repository.py` | SQL: barrido bidireccional + estado de notificación. |
| `matching_service.py` | `scan_matches()` — detecta y persiste matches (no envía). |
| `cron.py` | Entrypoint del cron: barre + envía. |
| `router.py` | Endpoints FastAPI (`/addon/*`). |

## Configuración (`.env`)

Reusa el `.env` del proyecto (mismo `DATABASE_URL`, `MATCH_THRESHOLD`). Agrega:

```bash
# Canal de envío del cron. Preferencia: webhook n8n (recomendado). Si está vacío,
# usa Evolution directo. Si ambos faltan, el cron solo detecta y deja 'pendiente'.
MATCH_NOTIFY_WEBHOOK_URL=https://TU-N8N/webhook/reencuentros-match-notify

# Evolution API (fallback directo, si NO usas n8n)
EVOLUTION_URL=https://evo.tudominio.com
EVOLUTION_APIKEY=tu-apikey
EVOLUTION_INSTANCE=reencuentros

# WhatsApp
WA_DEFAULT_COUNTRY=58          # código de país sin '+' (Venezuela = 58)
WA_BUSINESS_NAME=Reencuentros

# Barrido
ADDON_SCAN_LIMITE=0              # 0 = todas las buscadas
ADDON_MIN_COINCIDENCIA_AVISO=80  # % mínimo para avisar (revisión humana)
```

### Notificación vía n8n (recomendado)

El flujo n8n `addon/n8n/reencuentros_whatsapp.json` (webhook `reencuentros-match-notify`)
recibe cada match del cron y manda el WhatsApp a la familia con tono *"tal vez encontramos
a alguien, revisa"*. Setea `MATCH_NOTIFY_WEBHOOK_URL` y la config de Evolution la maneja n8n
(no el addon). El cron postea este JSON por cada match >= 80 %:

```json
{ "familiar_telefono": "...", "nombre_buscada": "...", "refugio": "...",
  "ubicacion": "...", "encontrado_por": "...", "telefono_responsable": "...",
  "coincidencia": 87, "instance_name": "..." }
```

El webhook responde `{status: 'sent' | 'skipped'}`; el cron marca el match `enviada`
(canal `n8n`) o `fallida` según la respuesta.

## Endpoints (`/addon/*`)

| Método | Ruta | Auth | Para qué |
|---|---|---|---|
| `POST` | `/addon/wa-link` | pública | **Botón Contactar** del rescatista. Body: `{telefono, nombre_buscada?, refugio?}` → `{wa_link, mensaje}`. Stateless (no consulta BD). |
| `GET` | `/addon/matches` | admin | Lista coincidencias (`?estado=pendiente|enviada|fallida|sin_telefono`). |
| `POST` | `/addon/scan` | admin | Corre el barrido ahora (no envía). |
| `GET` | `/addon/contactar/{buscada_person_id}` | admin | Link `wa.me` a la familia desde el panel. |
| `GET` | `/addon/whatsapp/qr` | admin | QR de Evolution para conectar el WhatsApp (proxy server-side; el apikey no sale del server). |
| `GET` | `/addon/whatsapp/estado` | admin | Estado de conexión (`open`/`connecting`/`close`) sin regenerar QR. |

### Conectar WhatsApp desde el panel admin

El `frontend/index.html` (pestaña **Superadmin**) tiene la tarjeta *"📱 Conectar WhatsApp
(Evolution)"*: pulsa **Mostrar QR**, escanéalo desde WhatsApp → Dispositivos vinculados.
El front llama a `/api/addon/whatsapp/qr` con el Bearer del admin y auto-refresca cada 6 s
hasta que el estado pasa a `open` (conectado). Requiere `EVOLUTION_URL/APIKEY/INSTANCE` en el
`.env`; si faltan, la tarjeta muestra "Evolution no está configurada".

El router ya se incluye automáticamente en `app/main.py` (dentro de un `try/except`,
así que si borras `addon/` la app sigue corriendo).

### Botón "Contactar" en el front

Cuando el rescatista registra a alguien (`POST /encontrados`) y la respuesta trae
`alerta`, el front llama:

```js
const r = await fetch("/addon/wa-link", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    telefono: alerta.familiar_telefono,
    nombre_buscada: alerta.familiar_nombre,
    refugio: encontrado.refugio,
  }),
});
const { wa_link } = await r.json();
// <a href={wa_link} target="_blank">Contactar a la familia</a>
```

## Cron nocturno

```bash
# Manual / prueba (no envía):
python -m addon.cron --dry-run

# Real (detecta + envía si Evolution está configurada):
python -m addon.cron
```

### crontab (todas las noches 03:00)

```cron
0 3 * * *  cd /ruta/al/repo && /usr/bin/python -m addon.cron >> /var/log/reencuentros_cron.log 2>&1
```

### Docker (servicio aparte, comparte la misma DB)

Agrega un servicio al `docker-compose.yml` que reusa la imagen del API:

```yaml
  cron:
    build: .
    env_file: .env
    depends_on: [db]
    restart: "no"
    entrypoint: ["python", "-m", "addon.cron"]
    profiles: ["cron"]   # no arranca con `up`; se dispara bajo demanda
```

Y dispáralo desde el cron del host:

```cron
0 3 * * *  cd /ruta/al/repo && docker compose run --rm cron >> /var/log/reencuentros_cron.log 2>&1
```

## Flujo de estados de un match

```
detectado (scan)
   └── pendiente
         │  (cron, coincidencia ≥ ADDON_MIN_COINCIDENCIA_AVISO)
         ├── familiar sin teléfono ──→ sin_telefono  (se RE-EVALÚA cada corrida;
         │                                            si luego deja teléfono → se envía)
         ├── WhatsApp OK ───────────→ enviada        (notified_at, wa_message_id)
         ├── n8n 'skipped' ─────────→ omitida        (decisión, NO error; no reintenta)
         ├── falla transitoria ─────→ fallida        (intentos++; REINTENTA hasta
         │                                            ADDON_MAX_REINTENTOS, def. 5)
         └── admin usa /addon/contactar → contactado (el cron ya no reenvía)
```

Garantías:
- Un par `(buscada, encontrada)` es **único** (`UNIQUE`): nunca se duplica.
- **Reintentos:** `fallida` se reintenta mientras `intentos < ADDON_MAX_REINTENTOS`;
  una caída transitoria de Evolution/n8n ya **no** pierde la notificación para siempre.
- **Concurrencia:** el envío del cron toma un `pg_advisory_lock`, así dos corridas
  solapadas no mandan el mismo aviso dos veces.
- **Contacto manual:** abrir `/addon/contactar/{buscada}` marca los matches de esa
  buscada como `contactado` para que el cron no mande además el aviso automático.
- **Umbral y teléfono single-source:** el cron normaliza el número y manda el umbral en
  el payload; n8n los usa tal cual (no re-normaliza ni hardcodea el país).

## Tests

```bash
python -m pytest tests/addon/ -v
```

Lógica pura (normalización de teléfonos, armado de mensajes/links, barrido con repo
falso). No requieren DB ni el modelo InsightFace.
```
