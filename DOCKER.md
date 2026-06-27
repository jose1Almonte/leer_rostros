# Reencuentros — Instalar y correr con Docker

App de reconocimiento facial para reunir personas desaparecidas con sus familias,
empaquetada como **una sola imagen Docker** que incluye **todo**:

- Base de datos **Postgres + pgvector** (incluida)
- **API** (FastAPI + DeepFace / Facenet512)
- **nginx** + el **frontend** (las 3 pestañas: familiar / rescatista / superadmin)
- El **modelo** de IA pre-descargado dentro de la imagen

**No necesita `.env`, ni base de datos externa, ni configurar nada.** Solo Docker.

---

## 1. Instalar Docker en el servidor (Ubuntu/Debian)

```bash
curl -fsSL https://get.docker.com | sh
```

(En un Droplet de DigitalOcean puedes crear directamente uno del Marketplace
**"Docker"**, que ya lo trae instalado, y saltarte este paso.)

---

## 2. Obtener la imagen

Elige UNA de estas tres:

**A) Construirla desde el código (lo más común):**
```bash
git clone https://github.com/jose1Almonte/leer_rostros.git
cd leer_rostros && git checkout felipe
docker build -f Dockerfile.standalone -t reencuentros:latest .
```
> Tarda ~10-15 min (instala TensorFlow y pre-descarga el modelo dentro de la imagen).

**B) Desde un registry (si ya la subiste):**
```bash
docker pull <registry>/<usuario>/reencuentros:latest
```

**C) Desde un archivo (sin internet/registry):**
```bash
docker load < reencuentros.tar.gz
```

---

## 3. Correr (un solo comando)

```bash
docker run -d --name reencuentros \
  -p 80:80 \
  -v rostros-data:/data \
  --restart unless-stopped \
  reencuentros:latest
```

¡Listo! La app queda en:
- **App:** `http://IP_DEL_SERVIDOR`
- **Documentación de la API (Swagger):** `http://IP_DEL_SERVIDOR/api/docs`

> La primera búsqueda puede tardar unos segundos más (carga el modelo en memoria).
> Las fotos y la base de datos se guardan en el volumen **`rostros-data`** (`/data`),
> así que sobreviven reinicios y actualizaciones.

---

## 4. Verificar que funciona

```bash
curl http://localhost/api/health      # -> {"status":"ok"}
docker logs -f reencuentros           # ver el arranque
```
Luego abre `http://IP_DEL_SERVIDOR` en el navegador y prueba registrar/buscar.

---

## 5. Configuración OPCIONAL (no hace falta para que funcione)

Por defecto no necesitas nada. Si quieres cambiar algo, pásalo con `-e`:

| Variable | Para qué | Default |
|---|---|---|
| `MATCH_THRESHOLD` | umbral de coincidencia (menor = más estricto) | `0.50` |
| `FACE_MODEL` | modelo (`Facenet512`, `SFace`, `ArcFace`...) | `Facenet512` |
| `SPACES_KEY` / `SPACES_SECRET` / `SPACES_BUCKET` / `SPACES_REGION` | guardar las fotos en DigitalOcean Spaces en vez de local | (local) |

Ejemplo con Spaces:
```bash
docker run -d -p 80:80 -v rostros-data:/data \
  -e SPACES_KEY=xxx -e SPACES_SECRET=yyy -e SPACES_BUCKET=mi-bucket -e SPACES_REGION=sfo3 \
  --restart unless-stopped reencuentros:latest
```

---

## 6. Operación diaria

```bash
docker ps                          # estado
docker logs -f reencuentros        # logs en vivo
docker restart reencuentros        # reiniciar
docker stop reencuentros           # detener (los datos se conservan)
docker start reencuentros          # volver a arrancar
```

**Actualizar a una versión nueva:**
```bash
git pull                                   # (o docker pull la nueva imagen)
docker build -f Dockerfile.standalone -t reencuentros:latest .
docker rm -f reencuentros
docker run -d --name reencuentros -p 80:80 -v rostros-data:/data --restart unless-stopped reencuentros:latest
```
(Los datos se conservan porque viven en el volumen `rostros-data`.)

---

## 7. Mover a otro VPS

La imagen es portable. Tres formas:

1. **Registry:** `docker push` en uno, `docker pull` + `docker run` en el otro.
2. **Tarball:**
   ```bash
   docker save reencuentros:latest | gzip > reencuentros.tar.gz
   scp reencuentros.tar.gz root@VPS_NUEVO:/root/
   # en el VPS nuevo:
   docker load < reencuentros.tar.gz
   docker run -d -p 80:80 -v rostros-data:/data --restart unless-stopped reencuentros:latest
   ```
3. **Re-build:** `git clone` + `docker build` + `docker run` en el VPS nuevo.

**Conservar los datos** (personas ya registradas) al mudarte:
```bash
# En el VPS viejo: respaldar el volumen
docker run --rm -v rostros-data:/data -v $(pwd):/backup alpine tar czf /backup/datos.tar.gz -C /data .
# Copiar datos.tar.gz al VPS nuevo y restaurar:
docker run --rm -v rostros-data:/data -v $(pwd):/backup alpine tar xzf /backup/datos.tar.gz -C /data
```
(O simplemente empezar limpio y re-registrar.)

---

## Requisitos del servidor
- Docker instalado.
- **~15 GB de disco** libre (la imagen con TensorFlow pesa ~5 GB).
- **4 GB de RAM** o más recomendado.

## HTTPS + dominio
Apunta tu dominio (A record) al servidor y pon **Cloudflare** delante (SSL gratis),
o usa Caddy/certbot como reverse proxy frente al puerto 80.
