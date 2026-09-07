# Estrategia de pruebas de SGCIU

## Capas de validación

1. Las pruebas unitarias validan normalización, guardrails, costes y métricas.
2. Las pruebas de integración ejercitan servicios, PostgreSQL/SQLite, embeddings, tools,
   RAG, autenticación y contratos de API.
3. Las pruebas E2E recorren la aplicación desde HTTP hasta la persistencia y las respuestas
   públicas. Únicamente sustituyen los límites externos de OpenAI por dobles deterministas
   para evitar coste, variabilidad y exposición de datos durante CI.
4. El smoke test posterior al despliegue comprueba frontend, `/health` y `/ready` sobre las
   URLs reales de Cloud Run.

## Cobertura E2E

| Módulo | Recorrido automatizado |
|---|---|
| Ciudadano identificado | Inicio, mensaje, extracción, recuperación de sesión y envío |
| Ciudadano anónimo | Inicio, mensaje, envío y descarte verificable de contacto |
| Seguridad | Rechazo sin token, login, `/me`, logout y revocación |
| Registro interno | Intake administrativo, badge, análisis y persistencia |
| Incidentes | Creación, listado filtrado, detalle, reindexación y relacionados |
| Inteligencia semántica | Recálculo, clusters candidatos y patrones recurrentes |
| Supervisión humana | Revisiones, transiciones, resaltados y evaluación pendiente |
| Agente operativo | Sesión, tool tipado, respuesta con traza y feedback |
| RAG normativo | Estado, indexación idempotente, consulta, cita y página PDF |

Ejecute solo los recorridos E2E:

```bash
make e2e
```

Ejecute el control completo de calidad:

```bash
make verify
```

## Escenarios del cantón de Flores

Los datos están versionados en `backend/evaluation/flores_e2e_scenarios.json`. Los nombres de
distrito y barrio proceden de la *División Territorial Administrativa de la República de Costa
Rica 2017* del Instituto Nacional de Estadística y Censos:

<https://inec.cr/wwwisis/documentos/Imprenta_Nacional/Division_Territorial_Administrativa_2017.pdf>

Se utilizan San Joaquín, Barrantes y Llorente, junto con los barrios Santa Marta, Ugalde y
Ángeles. Todos los hechos, personas, contactos, badges y tiempos descritos son sintéticos; no
representan denuncias reales.
