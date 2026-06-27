# Resultado del experimento Azure AI Face

**Fecha:** 2026-06-26 · **Veredicto: NO usable sin aprobación.**

Se creó el recurso Face (`trilord243`, East US, Azure for Students) y se probó la
comparación con `test_azure.py`. Respuesta de Azure:

```
HTTP 403 UnsupportedFeature:
"missing approval for one or more of the following features:
 Identification, Verification. Please apply for access at https://aka.ms/facerecognition"
```

**Conclusión:** las funciones de comparación de caras (Verify/Identify) requieren
aprobación de "acceso limitado" de Microsoft, independientemente de la subscripción.
Para usar Azure habría que solicitar acceso en https://aka.ms/facerecognition (revisión
manual, días, y restrictivo para identificar personas).

**Decisión:** se mantiene **Facenet512 self-hosted** (rama `felipe`), que ya funciona,
no tiene gating, y mantiene los datos en infraestructura propia.
