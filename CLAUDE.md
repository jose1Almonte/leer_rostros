# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

App de reconocimiento facial en local. Convierte un rostro de una imagen en un vector
de características (embedding) con **DeepFace** (modelo `Facenet`) y lo guarda/consulta en
una base de datos vectorial **ChromaDB** persistida en disco. Pensada como prototipo de
identificación de personas (p. ej. registro de pacientes en un hospital).

## Ejecutar

No hay `requirements.txt`, suite de tests ni linter configurados. Es Python 3.13.

```bash
# Instalar dependencias (no declaradas en el repo)
pip install deepface chromadb

# Correr el flujo (edita las rutas/flags dentro de main.py antes)
python main.py
```

`main.py` es el punto de entrada y un *scratchpad*: las rutas de imagen y los datos de la
persona están **hardcodeados**, y se alterna entre cargar/buscar comentando líneas. Para
registrar un rostro se usa el bloque `LoadImage(...).loadData()`; para identificar uno se
usa `SearchImage(...).searchImage()`.

## Arquitectura

Dos clases, una por operación, ambas hablan con la misma colección de ChromaDB:

- **`load_image.py` → `LoadImage`**: `DeepFace.represent()` extrae el embedding y
  `collection.add()` lo inserta con un id `usr_<uuid4>` y metadatos
  (`nombre`, `rol`/`hospital_name`, `ci`). Crea la colección si no existe.
- **`search_image.py` → `SearchImage`**: extrae el embedding de la imagen nueva y hace
  `collection.query(n_results=10)`. Recorre los resultados y considera una coincidencia
  cuando la **distancia coseno < 1** (umbral hardcodeado).

Detalles que comparten y conviene respetar al editar:

- Colección ChromaDB: nombre `"rostros_usuarios"`, métrica `metadata={"hnsw:space": "cosine"}`.
  El umbral de match depende de esta métrica — si cambias la métrica, recalibra el `< 1`.
- Persistencia: `chromadb.PersistentClient(path="database/persistent_client_database")`.
  La carpeta `database/` está en `.gitignore` (no versionar embeddings).
- Modelo de DeepFace: `"Facenet"` con `enforce_detection=False` (no falla si no detecta
  rostro). **Ambas clases deben usar el mismo modelo**: los embeddings de modelos distintos
  no son comparables y romperían la búsqueda silenciosamente.
- Las dos primeras líneas de cada módulo silencian los logs de TensorFlow
  (`TF_CPP_MIN_LOG_LEVEL`, `TF_ENABLE_ONEDNN_OPTS`) y van **antes** de importar `deepface`.

## Notas del repo

- `haarcascade_frontalface_default.xml` está presente pero el código actual no lo referencia
  (DeepFace gestiona su propia detección). No lo borres sin confirmar.
- `env_template.py` está vacío; `env.py` está en `.gitignore`. No hay variables de entorno
  en uso por ahora.
- Hay un **clon anidado del propio repo** en `leer_rostros/` (con su propio `.git`). Es una
  duplicación accidental; trabaja siempre en la raíz `E:\personal\leer_rostros\`, no dentro
  de la subcarpeta.
