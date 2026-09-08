# Despliegue en Google Cloud

La implantación de referencia está activa en el proyecto `tfm-sgciu`, región
`us-central1`. El frontend, backend, base de datos, imágenes, jobs, secretos y llamadas a
OpenAI se ejecutan desde servicios cloud; el equipo local solo se utiliza para desarrollar,
probar y enviar cambios a Git.

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
6. Crear una cuenta de backend con acceso mínimo a Cloud SQL y secretos. La configuración
   usa `sgciu-runtime@PROJECT_ID.iam.gserviceaccount.com`. El instalador del paso siguiente
   crea además `sgciu-frontend@PROJECT_ID.iam.gserviceaccount.com` sin roles de proyecto,
   porque Nginx no llama APIs de GCP.
7. Ejecutar `infra/iam/setup-cloud-build.sh PROJECT_ID REGION`. Este instalador crea una
   cuenta exclusiva y dos roles personalizados: a nivel de proyecto solo puede iniciar el
   build y leer operaciones; la escritura se concede individualmente a `sgciu-backend`,
   `sgciu-frontend` y los tres jobs existentes. También obtiene `Artifact Registry Writer`
   solo sobre el repositorio, `Service Account User` solo sobre las dos identidades de
   runtime y `Logs Writer`. El agente de Cloud Build obtiene `Service Account Token Creator`
   únicamente sobre la cuenta de build. No se utiliza la cuenta por defecto con rol
   `Editor`.
8. Conceder una sola vez `roles/run.invoker` a `allUsers` sobre los servicios frontend y
   backend. La pipeline conserva esta política y no puede modificar IAM de Cloud Run.
9. Sustituir `_CLOUD_SQL_INSTANCE` y las demás variables de `infra/cloudbuild.yaml`.

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

1. Audita dependencias Python y npm, ejecuta Ruff, migraciones desde cero, 78 pruebas
   (incluida la E2E), cobertura, build web, proyección de costes y sintaxis de infraestructura.
2. Construye y publica una imagen inmutable con el SHA del commit.
3. Configura un Cloud Run Job para Alembic y espera la migración.
4. Despliega backend con recursos, escalado y probes explícitos.
5. Provisiona los usuarios de Policía y Administrativo desde Secret Manager.
6. Indexa de forma idempotente el corpus legal mediante `sgciu-index-legal-corpus`.
7. Construye el frontend con la URL real del backend y lo despliega.
8. Ejecuta smoke tests de `/health`, `/ready`, `/metrics` y la página pública. Cualquier
   fallo marca el build como fallido.

`_FRONTEND_ORIGINS` en `infra/cloudbuild.yaml` enumera, separado por comas, todos los dominios
públicos de Cloud Run que sirven el frontend. Se inyecta durante el despliegue inicial del
backend para configurar `CORS_ORIGINS`; la opción `^@^` de `--set-env-vars` conserva el CSV
como un único valor. Esto evita una actualización posterior y permisos globales para listar
revisiones. Para una instalación nueva, despliegue una vez el frontend, consulte su URL con
`gcloud run services describe sgciu-frontend --region=REGION --format='value(status.url)'`,
agregue también el hostname legado si está publicado y actualice la sustitución antes del
despliegue definitivo.

El trigger regional `sgciu-production-main` escucha exclusivamente pushes a `main` desde el
repositorio conectado `andazo/SGCIU`. `Develop` ejecuta CI, pero nunca despliega producción.
Consulte el [flujo de ramas](development-workflow.md).

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

Las métricas, uptime checks, dashboard y siete alertas se versionan en `infra/monitoring/` y
se aplican de forma idempotente con `make monitoring-setup`. Consulte la
[guía de monitorización](monitoring.md) y la [estimación de costes](costs.md).
