# Arquitectura — Reencuentros (reconocimiento facial)

App de reconocimiento facial para **reunir personas desaparecidas con sus familias**.
Un familiar sube la foto de a quién busca; un rescatista sube la foto de a quién
encontró; el sistema hace **match facial automático** y muestra candidatos para que
una persona confirme.

> Caso de uso real: identificación de personas (incl. niños que no hablan o adultos
> en shock) en emergencias. Por eso prioriza **precisión** sobre velocidad.

---

## 1. Vista general

```
                       ┌─────────────────────────────────────────────┐
   Navegador           │             Droplet DigitalOcean            │
  (rescatista /        │                                             │
   familiar)           │   ┌─────────┐      ┌───────────────────┐    │
       │   HTTPS        │   │  nginx  │─────▶│  FastAPI (uvicorn │    │
       └──────────────▶ │   │  :443   │ /api │  + pm2, N workers)│    │
   symtechven.com       │   │  SSL    │─────▶│   DeepFace        │    │
                        │   └────┬────┘  /   │   SFace+retinaface│    │
                        │        │           └─────────┬─────────┘    │
                        │   frontend                   │              │
                        │  (HTML estático)   ┌──────────┴───────────┐  │
                        │                    ▼                      ▼  │
                        │            ┌───────────────┐   ┌─────────────┐
                        │            │ Postgres +    │   │  Volumen 20GB│
                        │            │ pgvector      │   │ (datos, venv,│
                        │            │ (índice HNSW) │   │  pesos, PG)  │
                        │            └───────────────┘   └─────────────┘
                        └───────────────┬─────────────────────────────┘
                                        │  (URL de la imagen)
                                        ▼
                            ┌───────────────────────────┐
                            │ DigitalOcean Spaces (S3)  │
                            │  bucket: flowcheckapp      │  ← imágenes originales
                            └───────────────────────────┘
```

---

## 2. Componentes

| Componente | Tecnología | Rol |
|---|---|---|
| **Frontend** | HTML/CSS/JS estático (`frontend/index.html`) | Registrar y buscar desde el navegador |
| **Reverse proxy** | nginx + Certbot (SSL) | Sirve el frontend en `symtechven.com` y enruta `/api/` → uvicorn |
| **API** | FastAPI + uvicorn, gestionada por **pm2** | Endpoints REST; doc Swagger en `/api/docs` |
| **Motor facial** | DeepFace · **SFace** (modelo) · **retinaface** (detector) | Convierte rostro → vector de 128 dimensiones |
| **Base vectorial** | PostgreSQL 16 + **pgvector** (índice **HNSW**) | Guarda vectores y busca por distancia coseno |
| **Almacenamiento** | DigitalOcean **Spaces** (S3-compatible, `boto3`) | Guarda las imágenes originales |

---

## 3. Flujos de datos

### Registrar persona (`POST /api/personas`)
1. Llega la foto (multipart).
2. Se decodifica y **reescala** a ≤1000 px (acelera la detección).
3. DeepFace (**SFace + retinaface**) extrae el **vector de 128-dim**.
4. La imagen original se sube a **Spaces** → se obtiene su URL pública.
5. Se inserta en Postgres: `id, nombre, ci, rol, estado, image_url, image_key, embedding`.

### Buscar coincidencia (`POST /api/buscar`)
1. Llega la foto → mismo preprocesado → **vector**.
2. Consulta pgvector: `ORDER BY embedding <=> :vector` (distancia coseno) con índice **HNSW**.
3. Cada candidato se marca `es_match = distancia < umbral (0.55)`.
4. Se devuelven **ordenados** del más parecido al menos; un humano confirma.

---

## 4. Modelo de reconocimiento (decisión por evidencia)

Elegido tras **evaluación exhaustiva** (`evaluate.py`) de 5 modelos × 3 detectores
sobre fotos reales etiquetadas, midiendo el **margen de seguridad** =
`(mín. distancia entre personas distintas) − (máx. distancia entre la misma persona)`.

| Modelo + detector | Margen | Aciertos |
|---|---|---|
| **SFace + retinaface** ✅ | **+0.237** | 100% |
| Facenet + retinaface | +0.187 | 100% |
| ArcFace + retinaface | +0.075 | 100% |
| *(yunet/opencv)* | negativo | ✗ |

- **Modelo:** `SFace` (128-dim, ONNX, liviano y rápido).
- **Detector:** `retinaface` (mejor alineación; el costo CPU dominante ~6 s/imagen).
- **Umbral:** `0.55` → en las pruebas, 0 falsos positivos / 0 falsos negativos.
- Config en variables de entorno: `FACE_MODEL`, `EMBEDDING_DIM`, `MATCH_THRESHOLD`, `FACE_DETECTOR`.

---

## 5. Infraestructura

- **Droplet** DigitalOcean (Ubuntu 24.04) en `137.184.107.94`.
  - Disco de boot pequeño (~10 GB) → **todo lo pesado vive en un volumen de 20 GB**
    (`/mnt/volumen1`): código, venv, pesos de DeepFace y **datos de Postgres**.
- **nginx** sirve también `unimetlabs.lat` (otra app) — no tocar.
- **pm2** gestiona el proceso `rostros-api` (auto-restart, logs en el volumen).
- **SSL** por Certbot (Let's Encrypt) para `symtechven.com`.

### Particularidades técnicas (lecciones aprendidas)
- `app.database` (psycopg) se importa **antes** que `app.faces` (TensorFlow) para
  evitar un crash nativo `free(): invalid pointer`.
- **No** se usa índice `ivfflat` (con pocos registros omite filas y devuelve vacío);
  se usa **HNSW**, correcto con pocos o muchos registros.
- Los datos de Postgres se movieron al volumen porque el disco de boot se llenaba.

---

## 6. Escalabilidad

| Eje | Estado | Nota |
|---|---|---|
| Imágenes | ✅ Ilimitado | Spaces |
| Vectores | ✅ A millones | pgvector + HNSW |
| Búsqueda | ✅ Rápida a escala | índice HNSW |
| **Procesar caras (CPU)** | ⚠️ Cuello de botella | ~6 s/imagen en CPU; concurrencia limitada por nº de vCPU |

- **Latencia** por búsqueda: ~6 s (inferencia de retinaface en CPU). Aceptable para el
  caso de uso (no es tiempo real).
- **Concurrencia**: se escala con **más vCPUs** + más *workers* de uvicorn
  (no con GPU en DigitalOcean, que solo ofrece H100 ~$2.5k/mes).
- Para carga muy alta sostenida: GPU en proveedor externo (RunPod/Lambda) + cola de
  trabajos; arquitectura preparada para ello (la API ya es stateless).

---

## 7. Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado del servicio |
| `POST` | `/api/personas` | Registrar persona (foto → bucket + vector) |
| `GET` | `/api/personas` | Listar personas registradas |
| `POST` | `/api/buscar` | Buscar coincidencias por foto |

Documentación interactiva: **`/api/docs`** (Swagger) y **`/api/redoc`** (ReDoc).

---

## 8. Estructura del repositorio

```
app/
  main.py        # FastAPI: endpoints + metadatos Swagger
  config.py      # configuración (pydantic-settings, desde .env)
  database.py    # Postgres + pgvector, índice HNSW
  faces.py       # extracción de vector (DeepFace) + warmup
  storage.py     # subida a DigitalOcean Spaces (boto3)
  schemas.py     # modelos de respuesta (Pydantic)
frontend/
  index.html     # frontend de prueba
evaluate.py      # evaluación exhaustiva de modelos × detectores
Dockerfile, docker-compose.yml   # despliegue en contenedores
requirements.txt, .env.example
```
