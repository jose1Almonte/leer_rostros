# Despliegue

Dos formas. La **Opción A (imagen all-in-one)** es la más simple y la ideal para
**cambiar de VPS**: una sola imagen con TODO, cero configuración.

---

## Opción A — Imagen ALL-IN-ONE (recomendada)

Una sola imagen contiene **Postgres+pgvector + API + nginx + frontend + el modelo**.
No necesita `.env`, ni base de datos externa, ni configurar nada.

### Construir (una vez)
```bash
docker build -f Dockerfile.standalone -t reencuentros:latest .
```
(Tarda ~10-15 min: instala TensorFlow y pre-descarga el modelo dentro de la imagen.)

### Correr en CUALQUIER VPS
```bash
docker run -d --name reencuentros -p 80:80 -v rostros-data:/data reencuentros:latest
```
Listo → `http://IP_DEL_VPS`  ·  Docs → `http://IP_DEL_VPS/api/docs`

> Las fotos y la base de datos viven en el volumen `rostros-data` (`/data`).

### Cambiar de VPS (3 maneras)
1. **Registry (lo más limpio):**
   ```bash
   docker tag reencuentros:latest <registry>/<usuario>/reencuentros:latest
   docker push <registry>/<usuario>/reencuentros:latest
   # en el VPS nuevo:
   docker run -d -p 80:80 -v rostros-data:/data <registry>/<usuario>/reencuentros:latest
   ```
2. **Tarball (sin registry):**
   ```bash
   docker save reencuentros:latest | gzip > reencuentros.tar.gz
   scp reencuentros.tar.gz root@VPS_NUEVO:/root/
   # en el VPS nuevo:
   docker load < reencuentros.tar.gz
   docker run -d -p 80:80 -v rostros-data:/data reencuentros:latest
   ```
3. **Build en el VPS nuevo:** `git clone` + `docker build` + `docker run` (igual que arriba).

Para **conservar los datos** al mudarte, copia el volumen `rostros-data`; o empieza
limpio (re-registrar). Para que las fotos sobrevivan cualquier mudanza, usa Spaces (abajo).

### Opcional: usar DigitalOcean Spaces en vez de fotos locales
```bash
docker run -d -p 80:80 -v rostros-data:/data \
  -e SPACES_KEY=... -e SPACES_SECRET=... -e SPACES_BUCKET=... -e SPACES_REGION=sfo3 \
  reencuentros:latest
```

---

## Opción B — Docker Compose (servicios separados)

Para quien prefiere Postgres como contenedor aparte.
```bash
git clone https://github.com/jose1Almonte/leer_rostros.git
cd leer_rostros && git checkout felipe
cp .env.example .env          # opcional: solo si quieres Spaces o cambiar la clave
docker compose up -d --build  # db (pgvector) + api + nginx
```
App en `http://IP` (puerto 80).

---

## HTTPS + dominio
Apunta tu dominio (A record) al VPS y pon **Cloudflare** delante (SSL gratis), o
agrega Caddy/certbot como reverse proxy.

## Requisitos del VPS
- Docker. ~15 GB de disco libre. 4 GB+ de RAM recomendado.
- En DigitalOcean: Droplet del Marketplace **"Docker"** (ya viene instalado).
