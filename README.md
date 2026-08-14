# SGCIU

Sistema de Gestión y Clasificación de Incidentes Urbanos para apoyar el registro,
análisis y consulta de denuncias de la Policía Municipal de Flores, Costa Rica.

El MVP prioriza el backend Python y la arquitectura de IA generativa. Incluye intake
conversacional, extracción estructurada, guardrails, embeddings, agrupación semántica,
un agente operativo ReAct con tools tipados y un servidor MCP. El frontend existente se
conserva como prototipo, pero no es el foco de esta etapa.

## Funcionalidades implementadas

- Sesiones persistentes de intake ciudadano con correcciones acumulativas.
- Clasificación, resumen, entidades, urgencia y confianza por campo.
- Revisión humana ante baja confianza, riesgo inmediato o prompt injection.
- Embeddings de incidentes con PostgreSQL y `pgvector`.
- Detección híbrida de incidentes relacionados y clusters candidatos.
- Agente operativo ReAct con límite de pasos, tools y trazas sanitizadas.
- Servidor MCP `sgciu-incident-intelligence` sin acceso a SQL arbitrario.
- Control opcional de endpoints administrativos mediante `X-Admin-Key`.
- CLI para ciudadanos y administradores.
- Dataset sintético y métricas reproducibles para regresión del workflow.
- Logs JSON con correlation IDs, latencia, tokens y auditoría de tools.

El RAG de políticas municipales está deliberadamente fuera de esta versión porque aún
no se dispone del corpus documental autorizado.

## Ejecución local

Requisitos: Python 3.13+, Docker y Docker Compose para PostgreSQL.

```bash
cp .env.example .env
docker compose up -d db
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic -c alembic.ini upgrade head
```

Para trabajar sin consumir una API externa, configure `LLM_PROVIDER=mock`. Para usar
OpenAI, configure `LLM_PROVIDER=openai` y `OPENAI_API_KEY`.

### Interfaz terminal

```bash
cd backend
.venv/bin/python -m app.cli
```

También se puede seleccionar el rol directamente:

```bash
.venv/bin/python -m app.cli --role citizen
.venv/bin/python -m app.cli --role admin --transport local
.venv/bin/python -m app.cli --role admin --transport mcp
```

### API

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload
```

Documentación OpenAPI: `http://localhost:8000/docs`.

Cuando `REQUIRE_ADMIN_AUTH=true`, los endpoints administrativos requieren:

```text
X-Admin-Key: <ADMIN_API_KEY>
```

### MCP

```bash
cd backend
.venv/bin/python -m app.mcp_server
```

Tools disponibles:

- `get_incident`
- `search_incidents`
- `aggregate_incidents`
- `find_related_incidents`
- `get_incident_cluster`
- `request_human_review`

## Calidad y evaluación

```bash
cd backend
.venv/bin/ruff check app tests migrations
.venv/bin/pytest --cov=app --cov-fail-under=70
LLM_PROVIDER=mock PYTHONPATH=. .venv/bin/python -m app.evaluation.runner --provider mock
```

Para evaluar el proveedor configurado:

```bash
PYTHONPATH=. .venv/bin/python -m app.evaluation.runner --provider configured
```

El dataset se encuentra en `backend/evaluation/intake_cases.json` y contiene únicamente
casos sintéticos.

## Documentación técnica

- [Arquitectura](docs/architecture.md)
- [Despliegue en Google Cloud](docs/gcp-deployment.md)
- [Variables de entorno](.env.example)

## Estructura principal

```text
backend/app/
├── agents/       # loop ReAct y gateways local/MCP
├── ai/           # intake, embeddings y guardrails
├── api/          # endpoints versionados y control de acceso
├── evaluation/   # métricas y runner de regresión
├── services/     # casos de uso y reglas de dominio
└── tools/        # tools tipados compartidos por agente y MCP
```
