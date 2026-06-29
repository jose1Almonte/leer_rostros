FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INSIGHTFACE_HOME=/weights

# Dependencias de sistema: OpenCV (libgl1/libglib2) + toolchain para compilar
# insightface (extensiones C/Cython) durante el pip install.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
RUN mkdir -p /weights /data/fotos && \
    useradd -r -s /bin/false -u 1001 appuser && \
    chown -R appuser:appuser /code /weights /data
USER appuser

EXPOSE 8000
# root-path /api: el nginx del compose proxya /api/ -> aquí.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--root-path", "/api"]
