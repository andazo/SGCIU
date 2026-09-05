# Despliegue propuesto en Google Cloud

## Servicios

- Cloud Run para el contenedor FastAPI.
- Cloud SQL for PostgreSQL con la extensión `vector`.
- Artifact Registry para las imágenes.
- Secret Manager para `DATABASE_URL`, `OPENAI_API_KEY` y las contraseñas iniciales de los
  usuarios institucionales.
- Cloud Logging y Cloud Monitoring para logs JSON, latencia y alertas.
- Cloud Build para construir, migrar y desplegar revisiones inmutables.
- Cloud Storage con versionado para el corpus legal cuando deje de distribuirse dentro de
  la imagen del MVP.

## Preparación

1. Crear un proyecto y seleccionar una región.
2. Crear un repositorio Docker en Artifact Registry.
3. Crear Cloud SQL para PostgreSQL y una base/usuario de aplicación.
4. Guardar `DATABASE_URL` y `OPENAI_API_KEY` en Secret Manager.
5. Crear los secretos `sgciu-police-admin-password` y
   `sgciu-administrative-admin-password` con contraseñas de al menos 12 caracteres.
6. Crear una cuenta de servicio de runtime con acceso mínimo a Cloud SQL y secretos. La
   configuración incluida usa `sgciu-runtime@PROJECT_ID.iam.gserviceaccount.com`.
7. Conceder a la cuenta de Cloud Build permisos para desplegar Cloud Run, publicar en
   Artifact Registry y usar la cuenta de servicio de runtime.
8. Sustituir `_CLOUD_SQL_INSTANCE` y las demás variables de `infra/cloudbuild.yaml`.

La migración inicial ejecuta `CREATE EXTENSION IF NOT EXISTS vector`. La cuenta de base de
datos utilizada por el job debe tener permiso para habilitarla. Después de la migración,
Cloud Build ejecuta el job `sgciu-provision-users`, que crea de forma idempotente los dos
usuarios institucionales sin guardar sus contraseñas en Git ni en la imagen.

## Despliegue

```bash
gcloud builds submit --config infra/cloudbuild.yaml \
  --substitutions=_IMAGE_TAG=$(git rev-parse --short HEAD),_CLOUD_SQL_INSTANCE=PROJECT_ID:REGION:INSTANCE
```

La pipeline realiza el orden siguiente:

1. Construye y publica una imagen con el SHA del commit.
2. Configura un Cloud Run Job para Alembic.
3. Ejecuta y espera la migración.
4. Provisiona los usuarios de Policía y Administrativo desde Secret Manager.
5. Indexa de forma idempotente el corpus legal mediante `sgciu-index-legal-corpus`.
6. Despliega el backend y el frontend como revisiones identificadas por commit.
7. Ajusta `CORS_ORIGINS` del backend con el origen final de Cloud Run del frontend.

El backend se expone a nivel de red para que el formulario ciudadano pueda llegar a los
endpoints públicos, pero las rutas institucionales exigen `Authorization: Bearer <token>`.
El panel obtiene el token mediante `/v1/auth/login`; no se empaquetan contraseñas ni API keys
en el frontend. `ADMIN_API_KEY` se mantiene únicamente como compatibilidad temporal para
integraciones antiguas y no se necesita en el despliegue nuevo.

Para el MVP local, los PDF legales se empaquetan de forma inmutable en la imagen. En la
transición a GCP conviene moverlos a un bucket privado con versionado y retención, conservar
el manifiesto/checksum en Git y mantener la indexación mediante el Cloud Run Job
`sgciu-index-legal-corpus`. El endpoint de indexación no debe exponerse públicamente ni
ejecutarse en cada arranque del servicio.

El backend se expone públicamente solo a nivel de invocación para permitir el intake ciudadano;
la autorización de las rutas institucionales ocurre en la aplicación mediante sesiones Bearer.
Para una implantación institucional posterior se recomienda añadir Identity-Aware Proxy o SSO
como capa adicional.

## Operación y costes

- Mantener Cloud Run con escalado mínimo en cero durante el TFM.
- Reservar el modelo con razonamiento alto para el intake ciudadano y mantener un modelo
  general independiente para el agente operativo.
- Generar cada embedding una sola vez y persistirlo.
- Separar el job de indexación legal del tráfico de consultas y dimensionarlo para procesos
  de varios minutos sin aumentar las instancias permanentes de Cloud Run.
- Configurar alertas por errores, latencia p95 y crecimiento de tokens.
- Rotar las contraseñas en Secret Manager y revocar sesiones ante cualquier sospecha de
  exposición.
- Aplicar backups y retención reducida en los entornos de demostración.
- Destruir los recursos de prueba cuando finalice la evaluación para evitar costes residuales.
