# Despliegue propuesto en Google Cloud

## Servicios

- Cloud Run para el contenedor FastAPI.
- Cloud SQL for PostgreSQL con la extensión `vector`.
- Artifact Registry para las imágenes.
- Secret Manager para `DATABASE_URL`, `OPENAI_API_KEY` y `ADMIN_API_KEY`.
- Cloud Logging y Cloud Monitoring para logs JSON, latencia y alertas.
- Cloud Build para construir, migrar y desplegar revisiones inmutables.
- Cloud Storage con versionado para el corpus legal cuando deje de distribuirse dentro de
  la imagen del MVP.

## Preparación

1. Crear un proyecto y seleccionar una región.
2. Crear un repositorio Docker en Artifact Registry.
3. Crear Cloud SQL para PostgreSQL y una base/usuario de aplicación.
4. Guardar los tres secretos requeridos en Secret Manager.
5. Crear una cuenta de servicio de runtime con acceso mínimo a Cloud SQL y secretos.
6. Sustituir `_CLOUD_SQL_INSTANCE` y las demás variables de `infra/cloudbuild.yaml`.

La migración inicial ejecuta `CREATE EXTENSION IF NOT EXISTS vector`. La cuenta de base de
datos utilizada por el job debe tener permiso para habilitarla.

## Despliegue

```bash
gcloud builds submit --config infra/cloudbuild.yaml
```

La pipeline realiza el orden siguiente:

1. Construye y publica una imagen con el SHA del commit.
2. Configura un Cloud Run Job para Alembic.
3. Ejecuta y espera la migración.
4. Despliega el servicio únicamente si la migración termina correctamente.

Para el MVP local, los PDF legales se empaquetan de forma inmutable en la imagen. En la
transición a GCP conviene moverlos a un bucket privado con versionado y retención, conservar
el manifiesto/checksum en Git y ejecutar la indexación mediante un Cloud Run Job. El endpoint
de indexación no debe exponerse públicamente ni ejecutarse en cada arranque del servicio.

El servicio se crea privado. La exposición futura del panel debe realizarse detrás de un
mecanismo de identidad apropiado; `X-Admin-Key` es un control suficiente para el MVP y las
pruebas, pero no sustituye IAM o Identity-Aware Proxy en una versión institucional.

## Operación y costes

- Mantener Cloud Run con escalado mínimo en cero durante el TFM.
- Reservar el modelo con razonamiento alto para el intake ciudadano y mantener un modelo
  general independiente para el agente operativo.
- Generar cada embedding una sola vez y persistirlo.
- Separar el job de indexación legal del tráfico de consultas y dimensionarlo para procesos
  de varios minutos sin aumentar las instancias permanentes de Cloud Run.
- Configurar alertas por errores, latencia p95 y crecimiento de tokens.
- Aplicar backups y retención reducida en los entornos de demostración.
- Destruir los recursos de prueba cuando finalice la evaluación para evitar costes residuales.
