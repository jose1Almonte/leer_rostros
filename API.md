# API — Guía para el frontend

Base URL: `https://symtechven.com/api` (o `http://IP/api` en el VPS).
Swagger interactivo: **`/api/docs`** · ReDoc: `/api/redoc`. En el Swagger, el botón
**Authorize** (candado arriba a la derecha) acepta un Bearer token para probar los
endpoints de admin sin copiar el header a mano.

Todas las peticiones que suben foto son **`multipart/form-data`**. La foto va en
**`files`** (puedes mandar varias del mismo registro). Errores: HTTP `422` (validación),
`400` (parámetro inválido), `401` (sin token / token inválido o expirado en endpoints
de admin), `403` (cuenta desactivada), o `404`. El body siempre es `{"detail": "..."}`.

---

## 🟣 FAMILIAR — `POST /buscados`

Registra una búsqueda y devuelve los encontrados más parecidos.

**Campos (form-data):** `files`*· `nombre` · `apellido` · `edad` · `doc_tipo` · `doc_numero` · `telefono_contacto`
(\\*obligatorio: foto con rostro. Validación: manda al menos `nombre` o `doc_numero`.)

```js
const fd = new FormData();
fd.append("files", file);                 // File del <input type=file>
fd.append("nombre", "María");
fd.append("doc_numero", "12345678");
fd.append("telefono_contacto", "0412-1234567");
fd.append("limit", "10");                // resultados por pagina
fd.append("offset", "0");                // primera pagina
const r = await fetch("/api/buscados", { method: "POST", body: fd });
const data = await r.json();
```

**Respuesta 201:**

```json
{
  "codigo": "REE-CC66DA69",
  "total": 2,
  "coincidencias": [
    {
      "person_id": "b16bf3ec-...", "estado": "encontrada", "es_menor": false,
      "nombre": "Juan", "apellido": "Gómez", "edad": null,
      "refugio": "Refugio Central", "ubicacion": "Plaza Bolívar",
      "telefono": "0414-9999999", "descripcion": null,
      "image_url": "/fotos/personas/xxx.jpg",
      "distancia": 0.395, "coincidencia": 67, "confianza": "alta"
    }
  ]
}
```

La respuesta tambien incluye `data` (mismos items que `coincidencias`) y `meta`
para clientes nuevos:

```json
{
  "data": ["... array de resultados ..."],
  "meta": {
    "total_records": 150,
    "current_page": 1,
    "total_pages": 15,
    "limit": 10,
    "offset": 0
  }
}
```

Para cargar mas resultados sin registrar otra busqueda:

```http
GET /api/buscados/REE-CC66DA69/coincidencias?limit=10&offset=10
```

> Muestra `coincidencia`% y `confianza`. Al pulsar **"Es mi familiar"** revela
> `ubicacion` y `telefono`. Si `es_menor=true`, `nombre`/`apellido` vienen `null`
> (muéstralo como *"Menor protegido"*).

---

## 🟢 RESCATISTA — `POST /encontrados`

Registra a la persona encontrada; avisa si un familiar ya la buscaba.

**Campos:** `files`*· `es_menor` (bool) · `nombre` · `apellido` · `doc_tipo` · `doc_numero` ·
`refugio`* · `ubicacion` · `telefono_responsable`* · `doc_responsable` (*obligatorio si menor*) · `descripcion`

```js
const fd = new FormData();
fd.append("files", file);
fd.append("es_menor", true);              // oculta nombre del menor
fd.append("refugio", "Refugio Norte");
fd.append("telefono_responsable", "0426-5555555");
fd.append("doc_responsable", "V-11111111"); // obligatorio si es_menor
fd.append("descripcion", "cabello castaño");
await fetch("/api/encontrados", { method: "POST", body: fd });
```

**Respuesta 201:**

```json
{
  "codigo": "REE-D38D8CF1",
  "person_id": "...",
  "alerta": {
    "person_id": "...", "familiar_nombre": "María", "familiar_telefono": "0412-1234567",
    "image_url": "/fotos/personas/yyy.jpg", "coincidencia": 67, "confianza": "alta"
  }
}
```

> Si `alerta` es `null`, nadie lo buscaba aún. Si trae datos, **muéstralos** (un
> familiar ya busca a esta persona, con su teléfono).

---

## 🛡️ SUPERADMIN

### Login — `POST /admin/login`

Body **JSON** (no form-data): `{"usuario":"admin","password":"..."}`.
Devuelve un **JWT** firmado (HS256) con expiración (`JWT_EXPIRES_MINUTES`, def. 60 min).
Envialo como header en TODOS los endpoints de admin.

```js
const r = await fetch("/api/admin/login", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ usuario: "admin", password: "..." })
});
const { token } = await r.json();          // JWT — guárdalo
// en cada llamada admin:
fetch("/api/admin/personas", { headers: { Authorization: "Bearer " + token } });
```

**Respuesta:** `{ "token": "eyJhbGci...", "tipo": "Bearer" }`.
Sin token, token expirado o inválido → **HTTP 401**.

> ⚠️ **Tokens previos a esta versión quedan invalidados** (cambio de formato).
> Si el front guardó un token viejo, el próximo request va a recibir 401; simplemente
> volver a loguearse.

**Sobre la password:** el login valida **siempre contra la BD** (tabla `admins`,
hash bcrypt — nunca en plano). Las variables `ADMIN_USER` / `ADMIN_PASSWORD` del
`.env` se usan **solo la primera vez** para sembrar el admin inicial (si la tabla
está vacía). Después se ignoran para el login. Para cambiar la password:

```bash
python -m app.cli change-password admin
```

> Todos los endpoints de abajo requieren el header `Authorization: Bearer <token>`.

### Comparar foto contra toda la base — `POST /buscar`

**Campos:** `file`* · `limite` (def. 25) · `offset`/`page` · `paginado` ·
`estado` (`buscada`|`encontrada`|vacío).
Por compatibilidad devuelve un array de candidatos. Si envías `paginado=true`,
devuelve `{ data, meta }` para poder implementar "Cargar más".

```js
const fd = new FormData();
fd.append("file", file);
fd.append("limite", "25");
fd.append("offset", "0");
fd.append("paginado", "true");
const r = await fetch("/api/buscar", {
  method: "POST",
  headers: { Authorization: "Bearer " + token },  // <-- requerido
  body: fd,
});
```

### Listar / moderar — `GET /admin/personas`

Query: `limite`/`per_page`, `offset`/`page`, `paginado`, `estado`/`status`,
`moderacion` (`aprobada`|`rechazada`|`pendiente`), `nombre`, `apellido`,
`cedula`/`doc_numero`, `es_menor` (boolean).

Para dashboard usa `paginado=true`; por compatibilidad, sin ese flag sigue
devolviendo un array legacy.

```js
const params = new URLSearchParams({
  per_page: "25",
  offset: "0",
  paginado: "true",
  nombre: "ana",
  es_menor: "true"
});
const r = await fetch(`/api/admin/personas?${params}`, {
  headers: { Authorization: "Bearer " + token }
});
const page = await r.json();
// page.data => filas visibles
// page.meta => total_records, current_page, total_pages, limit, offset
```

```json
{
  "data": [{ "person_id":"...", "estado":"encontrada", "es_menor":false, "nombre":"Juan",
    "refugio":"Refugio Central", "telefono":"0414-9999999", "codigo":"REE-...",
    "moderacion":"aprobada", "fotos":["/fotos/..."], "created_at":"2026-06-27T..." }],
  "meta": { "total_records": 150, "current_page": 1, "total_pages": 6, "limit": 25, "offset": 0 }
}
```

### Aprobar / rechazar — `PATCH /admin/personas/{person_id}/moderacion?valor=aprobada`

`valor` = `aprobada` | `rechazada` | `pendiente`. Las **rechazadas no aparecen** en búsquedas.

```js
await fetch(`/api/admin/personas/${id}/moderacion?valor=rechazada`, { method: "PATCH" });
```

### Eliminar (contenido indebido) — `DELETE /admin/personas/{person_id}`

Borra a la persona, sus fotos y sus filas.

```js
await fetch(`/api/admin/personas/${id}`, { method: "DELETE" });
```

---

## 🚩 REPORTES (público)

Cualquier usuario puede reportar fallas de la web o publicaciones inadecuadas.
Quedan en estado `pendiente` para que el superadmin los revise.

### Reportar falla de la página — `POST /reportes/falla`

**Body JSON:** `descripcion`* (≥3 chars) · `url?` · `contacto?`.

```js
await fetch("/api/reportes/falla", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    descripcion: "Al subir una foto el botón se queda cargando.",
    url: "https://symtechven.com/",
    contacto: "user@example.com"
  })
});
```

**Respuesta 201:**

```json
{
  "id": "5b7c4d6e-…",
  "tipo": "falla",
  "estado": "pendiente",
  "created_at": "2026-06-27T20:30:00Z"
}
```

### Reportar publicación inadecuada — `POST /reportes/publicacion`

**Body JSON:** `person_id`* (UUID) · `descripcion`* (≥3 chars) · `contacto?`.

La publicación **NO** se oculta automáticamente: queda registrada para que el
admin la revise y decida (puede rechazarla o eliminarla con los endpoints de
moderación).

```js
await fetch("/api/reportes/publicacion", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    person_id: "992865da-fcc6-4bb2-9db3-3d4af38269ff",
    descripcion: "La foto no corresponde a una persona / contenido ofensivo.",
    contacto: "tester@example.com"
  })
});
```

**Respuesta 201** (igual que falla) o `404` si el `person_id` no existe.

---

## 🛡️ REPORTES (admin)

### Listar reportes — `GET /admin/reportes`

Query: `tipo` (`falla`|`publicacion`), `estado`
(`pendiente`|`revisado`|`resuelto`|`descartado`), `limite` (def. 100),
`offset`/`page`, `paginado`.

```js
const r = await fetch("/api/admin/reportes?tipo=falla&estado=pendiente&paginado=true", {
  headers: { Authorization: "Bearer " + token }
});
const page = await r.json();
```

**Respuesta 200:** por defecto array de `ReporteAdmin`; con `paginado=true`,
`{ data, meta }`. Los de tipo `publicacion` traen
`pub_nombre`, `pub_estado`, `pub_image_url` y `pub_moderacion` (snapshot de
la publicación al momento del query).

### Listar testimonios — `GET /admin/testimonios`

Query: `estado` (`pendiente`|`aprobada`|`rechazada`), `limite` (def. 100),
`offset`/`page`, `paginado`.

```js
const r = await fetch("/api/admin/testimonios?estado=pendiente&paginado=true", {
  headers: { Authorization: "Bearer " + token }
});
const page = await r.json();
```

**Respuesta 200:** por defecto array de `TestimonioAdmin`; con `paginado=true`,
`{ data, meta }`.

### Cambiar estado de un reporte — `PATCH /admin/reportes/{id}/estado?valor=revisado`

`valor` = `pendiente` | `revisado` | `resuelto` | `descartado`.

```js
await fetch(`/api/admin/reportes/${id}/estado?valor=revisado`, {
  method: "PATCH",
  headers: { Authorization: "Bearer " + token }
});
```

---

## Referencia de campos de respuesta

| Campo | Significado |
|---|---|
| `coincidencia` | % de parecido (0-100) para mostrar |
| `confianza` | `alta` (<0.40) · `media` (0.40-0.50, revisar) · `baja` |
| `distancia` | técnico: menor = más parecido (0 = idéntico) |
| `es_menor` | si `true`, `nombre`/`apellido` van `null` → mostrar "Menor protegido" |
| `moderacion` | `aprobada` (visible) · `rechazada` (oculta) · `pendiente` |
| `image_url` | ruta de la foto (`/fotos/...` local o URL de Spaces) |
