# Evaluación híbrida manual

Esta evaluación ejecuta 90 denuncias sintéticas mediante el mismo servicio de intake
que utiliza la plataforma. Un actor ciudadano de OpenAI genera respuestas naturales a
partir de un escenario factual oculto; el intake no recibe las etiquetas esperadas ni el
grupo de clustering. Las personas validan posteriormente los resultados en Excel.

## Alcance y aislamiento

- La aplicación se ejecuta localmente con la configuración local de base de datos.
- Los casos se marcan como `synthetic=true`, `evaluation_run_id` y
  `evaluation_source=hybrid_local_actor`.
- La indexación ocurre para cada caso y los clústeres se reconstruyen únicamente entre los
  incidentes de la corrida. No se incorporan casos previos al cálculo de sus métricas.
- El coste del actor ciudadano no se persiste ni se incluye en ningún total. Las métricas
  incluyen únicamente intake, embeddings y clustering de SGCIU.
- La latencia representa la ejecución local de la aplicación con los servicios externos
  configurados. No debe presentarse como latencia end-to-end de Cloud Run.

## Ejecución local intencional

Con el proxy de Cloud SQL y la aplicación local configurados, ejecute una sola vez:

```bash
cd backend
.venv/bin/python -m app.evaluation.hybrid_runner \
  --execute \
  --confirm-production \
  --run-id hybrid-20260913-v1
```

El comando crea 90 registros sintéticos y deja un reporte JSON en
`artifacts/hybrid-evaluation/<run-id>/hybrid_evaluation_report.json`. Si la base local no
usa `APP_ENV=production`, puede omitir `--confirm-production`; `--execute` siempre es
obligatorio para impedir una inserción accidental.

## Libro de validación

Con el reporte generado, exporte el libro Excel:

```bash
SGCIU_ARTIFACT_NODE_MODULES=/Users/aag/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  /Users/aag/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  app/evaluation/build_hybrid_workbook.mjs \
  ../artifacts/hybrid-evaluation/hybrid-20260913-v1/hybrid_evaluation_report.json \
  ../artifacts/hybrid-evaluation/hybrid-20260913-v1/SGCIU_metricas_hibridas.xlsx
```

En `Incidentes`, complete las columnas amarillas de validación con `SÍ` o `NO`. La hoja
`Resumen` calcula la exactitud manual de categoría únicamente sobre los casos revisados.
Use `Rubrica` para aplicar el mismo criterio a todas las filas.
