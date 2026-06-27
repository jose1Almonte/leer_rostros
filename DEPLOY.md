# Despliegue con Docker (DevOps = un comando)

Todo el sistema (Postgres+pgvector + API + nginx/frontend) se levanta con
**un solo comando**. No hay que instalar nada a mano en el servidor.

## Requisitos del servidor
- Docker + Docker Compose.
- ~15 GB de disco libre (la imagen con TensorFlow pesa ~4-5 GB).
- 4 GB de RAM o más (recomendado).

## DigitalOcean (la forma más fácil)

1. Crea un **Droplet** desde el Marketplace **"Docker"** (ya trae Docker instalado).
   - Plan recomendado: **4 GB RAM / 2 vCPU / 80 GB** (o más para concurrencia).
   - Si usas un Droplet con disco chico, atacha un Volumen y apunta Docker ahí
     (`data-root` en `/etc/docker/daemon.json`).
2. Entra por SSH y despliega:

```bash
git clone https://github.com/jose1Almonte/leer_rostros.git
cd leer_rostros
git checkout felipe

cp .env.example .env
nano .env          # rellena SPACES_KEY/SECRET/REGION/BUCKET y un DB_PASSWORD

docker compose up -d --build
```

3. Listo. La app queda en **http://IP_DEL_DROPLET** (puerto 80).
   - Docs: `http://IP/api/docs`
   - La **primera** búsqueda descarga el modelo (~250 MB, una sola vez).

## HTTPS + dominio
- Apunta tu dominio (A record) al Droplet.
- Pon **Cloudflare** delante (SSL gratis), o agrega `certbot`/Caddy como reverse proxy.

## Operación

```bash
docker compose ps             # estado
docker compose logs -f api    # logs de la API
docker compose restart api    # reiniciar
docker compose down           # apagar (los datos persisten en los volúmenes)
docker compose up -d --build  # actualizar tras git pull
```

Los datos (Postgres) y los pesos del modelo viven en **volúmenes Docker**, así que
sobreviven reinicios y actualizaciones.

## Escalar (más rescatistas a la vez)
- Sube los workers de uvicorn: añade `--workers N` al `CMD` del `Dockerfile`
  (1 worker ≈ 1 búsqueda en paralelo; cada worker usa ~1.5-2 GB de RAM).
- O usa un Droplet con más vCPU/RAM.

## ¿Y DigitalOcean App Platform?
No es ideal aquí: la imagen con TensorFlow es muy pesada para los tiers de memoria
de App Platform. **Droplet + Docker Compose** es el encaje correcto para esta app.
