#!/bin/bash
set -e

export PATH="/usr/lib/postgresql/16/bin:$PATH"

mkdir -p /data/pgdata /data/fotos /data/weights
chown -R postgres:postgres /data/pgdata /data/fotos /data/weights

# Inicializar Postgres la primera vez (volumen vacío)
if [ ! -s "/data/pgdata/PG_VERSION" ]; then
  echo "[entrypoint] Inicializando Postgres..."
  su postgres -c "initdb -D /data/pgdata --auth-local=trust --auth-host=trust"
  echo "host all all 127.0.0.1/32 trust" >> /data/pgdata/pg_hba.conf
fi

# Arrancar Postgres temporalmente para crear BD/usuario/extensión
echo "[entrypoint] Preparando base de datos..."
su postgres -c "pg_ctl -D /data/pgdata -o '-c listen_addresses=127.0.0.1' -w start"
su postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='rostros'\" | grep -q 1 || psql -c \"CREATE USER rostros WITH SUPERUSER PASSWORD 'rostros'\""
su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='rostros'\" | grep -q 1 || psql -c \"CREATE DATABASE rostros OWNER rostros\""
su postgres -c "psql -d rostros -c 'CREATE EXTENSION IF NOT EXISTS vector'"
su postgres -c "pg_ctl -D /data/pgdata -w stop"

echo "[entrypoint] Arrancando servicios (Postgres + API + nginx)..."
exec supervisord -c /etc/supervisord.conf
