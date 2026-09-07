# Monitorización operativa

## Cobertura implementada

La API publica `/health`, `/ready` y `/metrics`. El último endpoint usa formato Prometheus y
no requiere credenciales para que pueda ser recolectado; por diseño no contiene relatos,
contactos, IDs de incidentes ni rutas concretas con identificadores.

Métricas propias principales:

| Métrica | Uso |
| --- | --- |
| `sgciu_http_requests_total` | Volumen y códigos HTTP por método y plantilla de ruta |
| `sgciu_http_request_duration_seconds` | Percentiles de latencia por ruta |
| `sgciu_http_requests_in_progress` | Concurrencia actual |
| `sgciu_ai_calls_total` | Éxitos y errores por funcionalidad/modelo |
| `sgciu_ai_call_duration_seconds` | Latencia de intake, agente, assessment, RAG y embeddings |
| `sgciu_ai_input_tokens_total` / `output_tokens_total` | Consumo real de tokens |
| `sgciu_ai_estimated_cost_usd_total` | Coste acumulado según el catálogo vigente |
| `sgciu_database_ready` | Resultado del último `SELECT 1` de readiness |

Los mismos eventos relevantes se escriben como JSON en stdout con `correlation_id`, por lo
que Cloud Logging los ingiere sin agentes. `infra/monitoring/` define cuatro métricas basadas
en logs, dos uptime checks, siete políticas de alerta y un dashboard único.

## Objetivos y alertas

| Señal | Objetivo / umbral | Respuesta inicial |
| --- | --- | --- |
| Frontend y `/ready` | Disponibilidad mensual ≥ 99%; fallo mayoritario por 2 min | Ver revisión activa, Cloud SQL y logs |
| HTTP 5xx | Ideal 0; alerta ante cualquier 5xx en 5 min | Buscar `correlation_id` y rollback si inició tras deploy |
| Latencia backend p95 | < 30 s durante 5 min | Separar latencia OpenAI, DB y cold start |
| Cloud SQL CPU | < 80% durante 5 min | Revisar queries/conexiones y dimensionamiento |
| Readiness PostgreSQL | 0 fallos | Revisar instancia, secreto y conexión Cloud SQL |
| Coste estimado de IA | p99 < USD 0,25/operación y < USD 75/mes | Revisar tokens, reintentos y modelo por `feature` |

Treinta segundos es un límite general deliberadamente amplio porque intake y RAG esperan
una API generativa. Para diagnóstico fino se utilizan los histogramas de `/metrics`, donde
cada módulo de IA aparece por separado.

## Provisionamiento reproducible

Con una sesión `gcloud` autorizada y los roles `Monitoring Editor` y
`Logs Configuration Writer`:

```bash
make monitoring-setup
```

El instalador consulta las URLs vigentes de Cloud Run y crea o actualiza métricas, uptime
checks, políticas y dashboard sin duplicarlos. Al actualizar una política conserva sus
canales y estrategia de notificación. Las plantillas pueden validarse antes de un cambio con
`gcloud monitoring dashboards create --validate-only` y con las pruebas del pipeline.

Las políticas se crean activas pero sin destinatarios porque un canal de correo, SMS o chat
debe verificarse por una persona. En Cloud Monitoring > Alerting > Notification channels,
cree al menos dos canales institucionales y asígnelos a las siete políticas. Esta es la única
parte deliberadamente manual de la monitorización.

## Comprobación posterior a un despliegue

1. `/health` devuelve `{"status":"ok"}` y `/ready`, `{"status":"ready"}`.
2. `/metrics` incluye series `sgciu_*` y ninguna PII.
3. Los dos uptime checks pasan desde tres regiones.
4. El dashboard muestra requests, p95, tokens/coste y Cloud SQL.
5. Una política de prueba notifica al canal verificado y luego se cierra.

No se debe provocar un 5xx real en producción para probar alertas. Use la función de prueba
del canal de Cloud Monitoring y valide condiciones con datos históricos o en `Develop`.
