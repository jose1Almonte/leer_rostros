#!/usr/bin/env python3
"""Carga masiva de personas ENCONTRADAS a la API de Reencuentros.

Lee un JSON (array de registros con `foto_url`) y los sube uno por uno al endpoint
`POST /encontrados/importar`. Es idempotente: si vuelves a correrlo, los ya
importados se omiten (no se duplican), así que puedes reanudar si se corta.

USO
---
    python scripts/cargar_encontrados.py data.json \
        --api https://symtechven.com/api \
        --usuario admin --password TU_PASSWORD

    # o pasando un token ya obtenido (sin login):
    python scripts/cargar_encontrados.py data.json --token eyJ...

Opciones:
    --solo-found     Importa solo los registros con estado == "found" (por defecto sí).
    --limite N       Importa solo los primeros N (para probar).
    --reintentos N   Reintentos por registro ante errores de red/servidor (def. 3).

Genera `fallidos.json` con los registros que no se pudieron importar (para revisar).
Requiere: pip install requests
"""

import argparse
import json
import sys
import time

import requests


def login(api: str, usuario: str, password: str) -> str:
    r = requests.post(f"{api}/admin/login", json={"usuario": usuario, "password": password}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"❌ Login falló ({r.status_code}): {r.text}")
    d = r.json()
    token = d.get("token") or d.get("access_token")
    if not token:
        sys.exit(f"❌ El login no devolvió token: {d}")
    return token


def to_payload(p: dict) -> dict:
    """Mapea un registro del JSON de origen al body del endpoint /encontrados/importar."""
    return {
        "foto_url": p.get("foto_url"),
        "nombre": p.get("nombre_pila") or p.get("nombre"),
        "apellido": p.get("apellido"),
        "cedula": p.get("cedula"),
        "edad": p.get("edad"),
        "ultima_ubicacion": p.get("ultima_ubicacion"),
        "reportante_phone": p.get("reportante_phone"),
        "reportante_name": p.get("reportante_name"),
        "fuente": p.get("fuente"),
        "id_externo": p.get("id"),
    }


def importar_uno(api: str, headers: dict, payload: dict, reintentos: int) -> tuple[str, str]:
    """Devuelve (resultado, detalle). resultado: creado|omitido|sin_rostro|error."""
    for intento in range(1, reintentos + 1):
        try:
            r = requests.post(f"{api}/encontrados/importar", json=payload, headers=headers, timeout=90)
        except requests.RequestException as e:
            if intento < reintentos:
                time.sleep(2 * intento)
                continue
            return "error", f"red: {e}"
        if r.status_code in (200, 201):
            return r.json().get("estado", "creado"), ""
        if r.status_code == 422:
            # Sin rostro o no se pudo descargar la foto: no tiene sentido reintentar.
            return "sin_rostro", r.json().get("detail", r.text)[:120]
        if r.status_code in (401, 403):
            sys.exit(f"❌ Token inválido/expirado ({r.status_code}). Vuelve a hacer login.")
        if r.status_code >= 500 and intento < reintentos:
            time.sleep(2 * intento)
            continue
        return "error", f"HTTP {r.status_code}: {r.text[:120]}"
    return "error", "agotados los reintentos"


def main():
    ap = argparse.ArgumentParser(description="Carga masiva de personas encontradas.")
    ap.add_argument("json", help="Ruta al archivo JSON (array de registros).")
    ap.add_argument("--api", default="https://symtechven.com/api", help="URL base de la API.")
    ap.add_argument("--usuario", help="Usuario admin (para login).")
    ap.add_argument("--password", help="Contraseña admin (para login).")
    ap.add_argument("--token", help="Token JWT ya obtenido (alternativa a usuario/password).")
    ap.add_argument("--solo-found", action="store_true", default=True)
    ap.add_argument("--limite", type=int, default=0, help="Importar solo los primeros N (0 = todos).")
    ap.add_argument("--reintentos", type=int, default=3)
    args = ap.parse_args()

    token = args.token
    if not token:
        if not (args.usuario and args.password):
            sys.exit("❌ Da --token, o bien --usuario y --password.")
        token = login(args.api, args.usuario, args.password)
        print("🔑 Login OK")
    headers = {"Authorization": f"Bearer {token}"}

    with open(args.json, encoding="utf-8") as f:
        registros = json.load(f)
    if args.solo_found:
        registros = [p for p in registros if str(p.get("estado", "")).lower() in ("found", "encontrada", "encontrado")]
    if args.limite:
        registros = registros[: args.limite]

    total = len(registros)
    print(f"📦 {total} personas encontradas para importar -> {args.api}")
    contadores = {"creado": 0, "omitido": 0, "sin_rostro": 0, "error": 0}
    fallidos = []

    for i, p in enumerate(registros, 1):
        payload = to_payload(p)
        if not payload["foto_url"]:
            contadores["error"] += 1
            fallidos.append({**p, "_motivo": "sin foto_url"})
            print(f"[{i}/{total}] ⚠️  {p.get('nombre','?')}: sin foto_url")
            continue
        estado, detalle = importar_uno(args.api, headers, payload, args.reintentos)
        contadores[estado] = contadores.get(estado, 0) + 1
        if estado in ("error", "sin_rostro"):
            fallidos.append({**p, "_motivo": f"{estado}: {detalle}"})
        icono = {"creado": "✅", "omitido": "⏭️ ", "sin_rostro": "🚫", "error": "❌"}.get(estado, "?")
        print(f"[{i}/{total}] {icono} {p.get('nombre','?')[:40]} -> {estado}"
              + (f" ({detalle})" if detalle else ""))

    print("\n===== RESUMEN =====")
    for k, v in contadores.items():
        print(f"  {k}: {v}")
    if fallidos:
        with open("fallidos.json", "w", encoding="utf-8") as f:
            json.dump(fallidos, f, ensure_ascii=False, indent=2)
        print(f"\n⚠️  {len(fallidos)} fallidos guardados en fallidos.json (revísalos / reintenta).")
    print("Listo.")


if __name__ == "__main__":
    main()
