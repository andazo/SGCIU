# Evaluación manual de funcionalidades de IA

SGCIU registra automáticamente una traza por interacción de intake, RAG jurídico y agente
operativo. La traza conserva modelo, versión del prompt, latencia, tokens, coste estimado,
resultado estructurado y fuentes o tools empleadas. El texto libre se representa únicamente
mediante SHA-256 para evitar duplicar relatos o información personal.

## Flujo recomendado

1. Inicie una sesión y utilice la aplicación normalmente.
2. Anote el `trace_id` devuelto por cada interacción.
3. Consulte las trazas de la sesión con `GET /v1/evaluation/interactions?session_id=...`.
4. Registre el resultado esperado y las puntuaciones humanas mediante
   `PUT /v1/evaluation/interactions/{trace_id}/label`.
5. Obtenga latencia, tokens, coste y promedios de calidad desde
   `GET /v1/evaluation/summary?created_from=YYYY-MM-DD&created_to=YYYY-MM-DD`.

Ejemplo de etiqueta:

```json
{
  "expected_output": {
    "category": "ruido",
    "district": "Llorente"
  },
  "quality_scores": {
    "classification": 1.0,
    "grounding": 0.8,
    "response_quality": 0.9
  },
  "notes": "La categoría y el distrito coinciden; una recomendación fue muy general."
}
```

Las puntuaciones usan el intervalo de 0 a 1. Para comparabilidad en la memoria, debe aplicarse
la misma rúbrica a todos los casos. La calidad necesita una etiqueta humana; latencia, tokens,
coste, herramientas y fuentes se calculan automáticamente.

Para una muestra controlada de 90 incidentes ciudadanos con conversaciones generadas de forma
natural, consulte [la evaluación híbrida](hybrid-evaluation.md). Esa corrida separa el coste del
actor de pruebas de las métricas de SGCIU y genera el libro Excel para la validación manual.

Para RAG, use `expected_document_keys` dentro de `expected_output`; el resumen calculará
hit-rate@1, @3 y @8 sobre las fuentes recuperadas. Para el agente operativo, use
`expected_tool_names`; el resumen calculará selección de tools y éxito de sus pasos. Para
intake se comparan automáticamente `category`, `district`, `relation` y `place_type`.

## Interpretación temporal

`created_at` indica cuándo SGCIU recibió el caso. `occurred_at` representa cuándo ocurrió el
hecho y es la referencia principal para similitud y patrones recurrentes. Cuando el momento del
hecho no puede normalizarse, el sistema usa `created_at` y declara
`temporal_basis=created_at_fallback` para que ese caso pueda analizarse por separado.
