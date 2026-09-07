# Estimación y control de costes

## Resultado de referencia

El escenario `backend/evaluation/cost_scenario.json`, revisado el 6 de septiembre de 2026,
estima **USD 44,95 mensuales** y **USD 0,33** una sola vez para indexar inicialmente el
corpus legal. No es una factura: combina recursos GCP realmente desplegados con una carga
mensual explícita y editable.

| Componente | Estimación mensual |
| --- | ---: |
| IA generativa y embeddings | USD 15,90 |
| Cloud SQL `db-g1-small` | USD 25,55 |
| Cloud SQL, 20 GiB SSD | USD 3,40 |
| Artifact Registry, 1,5 GiB asumidos | USD 0,10 |
| Cloud Run bajo la carga inicial y su free tier | USD 0,00 |
| Cloud Logging bajo 50 GiB/mes | USD 0,00 |
| **Total** | **USD 44,95** |

El intervalo prudente para planificación es **USD 45–55/mes**. El extremo superior cubre
variaciones de tokens, almacenamiento de backups, imágenes acumuladas, red e impuestos que
no pueden conocerse con exactitud sin datos de facturación de un mes completo.

## Base técnica

La inspección del proyecto `tfm-sgciu` confirmó dos servicios Cloud Run con escalado a cero,
1 vCPU, 512 MiB, concurrencia 80 y máximo 20 instancias; Cloud SQL PostgreSQL 16 en
`db-g1-small` con 20 GiB SSD; Artifact Registry; Secret Manager; tres Cloud Run Jobs y logs
administrados. La base de datos es el coste fijo dominante.

El catálogo de `backend/app/costs.py` usa precios por millón de tokens y resuelve alias y
snapshots de modelo. Las variables `LLM_INPUT_COST_PER_MILLION`,
`LLM_OUTPUT_COST_PER_MILLION` y `EMBEDDING_COST_PER_MILLION` solo lo reemplazan cuando tienen
un valor positivo. Esto evita volver a registrar coste cero por omisión.

Fuentes oficiales consultadas:

- [Precios de la API de OpenAI](https://openai.com/api/pricing/).
- [Precios de Cloud Run](https://cloud.google.com/run/pricing): 180.000 vCPU-s, 360.000
  GiB-s y dos millones de solicitudes gratis al mes con facturación por solicitud en
  `us-central1`.
- [Precios de Cloud SQL](https://cloud.google.com/sql/pricing): `db-g1-small` a USD 0,035
  por hora; el tipo de CPU compartida no dispone de SLA de Cloud SQL.
- [Precios de Artifact Registry](https://cloud.google.com/artifact-registry/pricing):
  primeros 0,5 GiB-mes sin coste y aproximadamente USD 0,10/GiB-mes después.
- [Precios de Google Cloud Observability](https://cloud.google.com/products/observability/pricing):
  primeros 50 GiB de logs por proyecto y mes sin coste; después USD 0,50/GiB.

La tarifa de GPT-5.6 Sol usada es promocional y OpenAI indica que se mantiene al menos hasta
el 21 de noviembre de 2026. Debe revisarse antes de esa fecha o al cambiar cualquier modelo.

## Reproducir y ajustar

```bash
make cost-report
cd backend
PYTHONPATH=. .venv/bin/python -m app.evaluation.cost_report --json
```

El primer comando falla si la proyección supera el umbral versionado de USD 75. Para simular
otro volumen, cambie únicamente cantidades y tokens del JSON, ejecute la prueba y registre el
cambio en Git. En producción, `/metrics` y Cloud Logging acumulan tokens y coste por
`feature` y `model`, por lo que después de un mes se deben reemplazar los supuestos por los
percentiles observados.

## Lo que la estimación no afirma

- No sustituye Billing Reports ni un presupuesto real de Cloud Billing.
- El free tier se comparte por cuenta de facturación y podría estar consumido por otros
  proyectos.
- No incluye conversión de moneda, impuestos, salida de red extraordinaria ni descuentos.
- Cloud SQL se cobra mientras la instancia siga activa, aunque no existan denuncias.
- El consumo OpenAI depende de tokens reales, reintentos, caché y futuros cambios de precio.
