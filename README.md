# SGCIU

Sistema de Gestión y Clasificación de Incidentes Urbanos para apoyar el registro,
análisis y consulta de denuncias de la Policía Municipal de Flores, Costa Rica.

El MVP prioriza el backend Python y la arquitectura de IA generativa. Incluye intake
conversacional, extracción estructurada, guardrails, embeddings, agrupación semántica,
un agente operativo ReAct con tools tipados, un servidor MCP y un panel administrativo web.

El panel institucional utiliza usuarios con roles `police` y `administrative`. Las
contraseñas se almacenan mediante PBKDF2-SHA256 con salt único y las sesiones se representan
por tokens opacos revocables cuyo hash es el único valor persistido.

## Funcionalidades implementadas

- Sesiones persistentes de intake ciudadano con correcciones acumulativas y razonamiento
  de alta precisión mediante OpenAI.
- Registro interno de incidentes por oficiales o personal administrativo mediante un flujo
  conversacional protegido por el rol administrativo, con identificación manual por badge.
- Registro previo por CLI de nombre, identificación y contacto antes del relato.
- Clasificación, resumen, entidades, urgencia, evidencia y confianza por campo.
- Follow-ups priorizados según valor operativo, con cierre parcial cuando la persona no
  sabe o no desea aportar más información.
- Control de calidad asistido por IA ante datos incompletos, ambiguos o de baja confianza.
- Embeddings de incidentes con PostgreSQL y `pgvector`.
- Agrupación recurrente proactiva de incidentes similares en los últimos 30 días, con
  similitud semántica de ubicación, relato, categoría y refuerzo por distrito.
- Agente operativo ReAct con límite de pasos, tools y trazas sanitizadas.
- Servidor MCP `sgciu-incident-intelligence` sin acceso a SQL arbitrario.
- RAG normativo con corpus versionado, extracción por página, recuperación híbrida,
  abstención y citas verificables de documento, página PDF y artículo detectado.
- Autenticación institucional por usuarios, roles y sesiones Bearer revocables.
- CLI para ciudadanos y administradores.
- Dataset sintético y métricas reproducibles para regresión del workflow.
- Logs JSON con correlation IDs, latencia, tokens y auditoría de tools.

## Ejecución local reproducible

La ruta recomendada levanta PostgreSQL con `pgvector`, aplica las migraciones y construye
el backend y el frontend en contenedores. Solo requiere Docker con Compose v2 y una API key
de OpenAI; no necesita Python ni Node.js instalados en el equipo anfitrión.

```bash
make bootstrap
# Edite .env y defina OPENAI_API_KEY.
make up
make smoke
```

La interfaz queda en `http://localhost:5173`, la API en `http://localhost:8000` y OpenAPI en
`http://localhost:8000/docs`. `make status`, `make logs` y `make down` permiten operar el
entorno. El volumen `sgciu_postgres_data` conserva los datos entre reinicios; `make down` no
lo elimina.

Para desarrollo directo fuera de contenedores se mantienen disponibles Python 3.13+ y
Node.js 22. Consulte los comandos de cada componente más adelante en esta guía.

Para crear los usuarios institucionales localmente, utilice el comando interactivo. Las
contraseñas no se muestran ni se guardan en el repositorio:

```bash
.venv/bin/python -m app.cli --create-user policia.flores --user-role police
.venv/bin/python -m app.cli --create-user administrativo.flores --user-role administrative
```

El runtime usa exclusivamente servicios de OpenAI. Configure `OPENAI_API_KEY`; el modelo
general se define con `OPENAI_MODEL` y el intake ciudadano, de forma independiente, con
`OPENAI_INTAKE_MODEL`. `INTAKE_REASONING_EFFORT=high` activa razonamiento reforzado solo en
la recepción ciudadana y `INTAKE_MAX_FOLLOW_UPS` limita la extensión de la conversación.

La suite automatizada reemplaza las conexiones externas mediante dobles ubicados únicamente
en `backend/tests/`; no existe un modo offline seleccionable en la aplicación.

El RAG utiliza de forma independiente `LEGAL_RAG_MODEL` y
`LEGAL_RAG_EMBEDDING_MODEL`. El valor recomendado y configurado por defecto para el corpus
en español es `text-embedding-3-large` reducido a 1536 dimensiones. Los embeddings legales
no se mezclan con los embeddings de denuncias.

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

### Registro interno desde el panel

En `http://localhost:5173/admin` seleccione **Registrar incidente**. El funcionario introduce
manualmente su badge, conversa con el mismo asistente de intake, revisa el resumen y confirma
la veracidad y el uso institucional de la información. El incidente se guarda en
`complaint_submissions` con `police_input=true`, conserva el badge del funcionario y aparece
junto con las denuncias ciudadanas. La acción también queda registrada en `audit_events`.

Endpoints administrativos del flujo interno:

- `POST /v1/internal-intake/sessions`
- `POST /v1/internal-intake/sessions/{session_id}/messages`
- `POST /v1/internal-intake/sessions/{session_id}/submit`

El asistente operacional usa sesiones persistentes para conservar el contexto entre
preguntas:

- `POST /v1/operational/sessions`
- `GET /v1/operational/sessions/{session_id}`
- `POST /v1/operational/sessions/{session_id}/messages`

El badge se valida como identificador de procedencia, pero no constituye autenticación. En
producción, los endpoints administrativos exigen una sesión Bearer creada mediante
`POST /v1/auth/login`. La autenticación usa sesiones revocables con expiración configurable.

El flujo ciudadano permite elegir entre registro con datos de contacto y registro anónimo.
En ambos casos la conversación usa una sesión persistente; en el modo anónimo el backend
descarta cualquier dato de contacto enviado por el cliente. En el modo completo, la
identificación, el correo y el teléfono son opcionales; estos datos se persisten con la
denuncia, pero se excluyen de embeddings, tools del agente y trazas. El agente entiende
referencias locales de Costa Rica, jerga y abreviaturas, registra evidencia por campo y
permite terminar con frases como `eso es todo`, `no tengo más información` o `llamaré al
911`; en ese caso guarda el reporte con los datos disponibles. La orientación al 9-1-1 se
muestra una sola vez por sesión y no sustituye la extracción del incidente.

### Datos sintéticos para el panel administrativo

El repositorio incluye 50 incidentes completamente ficticios y sin datos personales para
probar listados, búsquedas, embeddings, clusters, revisiones humanas y el agente ReAct. Antes
de cargarlos, asegúrese de que PostgreSQL esté activo y que `OPENAI_API_KEY` esté configurada:

```bash
cd backend
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m app.evaluation.seed_incidents
```

El comando es idempotente: cada caso tiene un identificador `FLO-*` y las ejecuciones
posteriores omiten registros existentes. También intenta completar embeddings pendientes. El
resultado indica cuántos casos fueron creados, omitidos, indexados y agrupados.

Después puede iniciar el administrador:

```bash
.venv/bin/python -m app.cli --role admin --transport mcp
```

Consultas sugeridas para la opción `5. Preguntar al agente operativo`:

- `¿Cuántos incidentes hay por distrito?`
- `¿Cuál es la categoría más frecuente en San Joaquín?`
- `Busca incidentes de ruido en Barrantes.`
- `¿Qué incidentes podrían estar relacionados con el incidente <ID>?`
- `Muéstrame los casos que requieren revisión humana.`

El dataset está en `backend/evaluation/flores_synthetic_incidents.json`. Las ubicaciones sirven
como contexto de prueba; todos los hechos descritos son inventados y no deben interpretarse
como denuncias reales.

### Clusters, resaltados y revisiones de calidad

La sección administrativa **Agrupación recurrente** muestra de forma independiente los
patrones que reúnen al menos tres incidentes similares dentro de una ventana móvil de 30 días.
La puntuación combina el embedding general del incidente con un embedding específico de la
ubicación, y aumenta cuando coinciden el distrito, la categoría o las referencias del lugar.
Estos patrones son informativos y proactivos: no sustituyen las denuncias originales ni
requieren confirmación o rechazo por parte del personal policial.

La opción administrativa `4. Clusters y recálculo de embeddings` permite consultar los
clusters candidatos existentes o regenerar manualmente todos los embeddings con OpenAI y
reconstruir las agrupaciones. El recálculo solicita confirmación porque consume tokens y puede
tardar según la cantidad de incidentes.

Dentro de la opción `4. Agrupación semántica y recurrente`, la opción `3. Ver agrupaciones
recurrentes` muestra en la terminal los patrones que cumplen el mínimo de tres incidentes
recientes, incluyendo sus puntuaciones, ubicación, categoría y motivos de coincidencia. Esta
consulta no modifica los datos ni requiere confirmación policial.

La opción `6. Gestionar resaltados y revisiones de calidad` separa dos decisiones independientes:

- Los **resaltados operativos** identifican hechos pasados o sin peligro de vida actual que
  merecen atención más pronta o precauciones especiales. Incluyen un resumen de IA, razones,
  evidencia y precauciones sugeridas.
- Las **revisiones de calidad** identifican datos incompletos, contradictorios o ambiguos.
  Incluyen un diagnóstico de IA, disponibilidad de contacto y acciones recomendadas. Al usar
  `dismissed`, solo se descarta la revisión; la denuncia se conserva con estado
  `insufficient_information`.

Un incidente puede aparecer en ambos apartados. Para analizar datos anteriores a esta función,
utilice `3. Analizar con IA incidentes pendientes` dentro de la opción 6.

El inicio ciudadano muestra siempre que SGCIU no sustituye al 9-1-1. Si durante la conversación
se detecta peligro inmediato, el agente muestra esa orientación una sola vez y continúa con
la extracción, sin confundir la emergencia con una revisión de calidad administrativa.

### Consulta normativa RAG

Después de aplicar las migraciones, abra el administrador y seleccione
`7. Consultar normativa (RAG)`:

```bash
cd backend
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m app.cli --role admin --transport mcp
```

La primera vez use `2. Indexar o actualizar documentos`. La operación valida checksums,
extrae el texto sin cruzar páginas, crea actualmente 4.985 fragmentos y solicita un
embedding por fragmento. Es idempotente: en ejecuciones posteriores omite documentos cuyo
PDF, modelo e indexador no hayan cambiado; los cambios exclusivos de metadatos se actualizan
sin recalcular embeddings.

Luego use `3. Consultar normativa`. Cada respuesta informa:

- embeddings recuperados y total de embeddings indexados;
- documento y archivo PDF versionado;
- página física exacta del PDF, empezando en 1;
- artículo detectado, chunk y señales de ranking semántico, léxico e híbrido;
- clasificación de cada hallazgo como obligación legal, facultad municipal o procedimiento
  recomendado, validada contra el alcance y fuerza jurídica de la fuente;
- trace ID, advertencias y abstención cuando la evidencia no es suficiente.

La consulta puede incluir el perfil (`administrative` o `police`) y una situación operativa.
La generación sintetiza la fuente para el flujo SGCIU y devuelve recomendaciones explícitas
para registrar, clasificar, derivar o revisar el incidente; no se limita a copiar el texto
del PDF.

El corpus contiene 27 documentos. El manifiesto registra como vacíos conocidos la
Constitución Política y el Código Procesal Penal;
el asistente no debe inferir su contenido. Consulte la [guía del RAG](docs/legal-rag.md) para
la cobertura y operación detalladas.

### API

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload
```

Documentación OpenAPI: `http://localhost:8000/docs`.

En producción la autenticación administrativa se activa automáticamente. El panel inicia
sesión mediante `POST /v1/auth/login` y utiliza el token Bearer devuelto para los endpoints
protegidos:

```text
Authorization: Bearer <access_token>
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
- `get_recurrent_patterns`
- `request_human_review`
- `search_legal_sources`
- `get_legal_corpus_status`

`search_incidents` y `aggregate_incidents` aceptan `created_from` y `created_to` en
formato `YYYY-MM-DD` para filtrar por la fecha de registro en SGCIU, además de paginación
en la búsqueda. `get_recurrent_patterns` permite definir `window_days` entre 1 y 365.

## Calidad y evaluación

```bash
cd backend
.venv/bin/ruff check app tests migrations
.venv/bin/pytest --cov=app --cov-fail-under=70
```

Para evaluar el intake real de OpenAI contra el dataset sintético:

```bash
PYTHONPATH=. .venv/bin/python -m app.evaluation.runner
```

El dataset se encuentra en `backend/evaluation/intake_cases.json` y contiene únicamente
casos sintéticos. El comando de evaluación sí consume la API de OpenAI; las pruebas de
`pytest` no realizan llamadas externas.

Para medir Hit@k y MRR de la recuperación legal con 12 consultas sintéticas:

```bash
PYTHONPATH=. .venv/bin/python -m app.evaluation.legal_rag_runner
```

La suite E2E recorre por HTTP los módulos ciudadano y administrativo, incluyendo
autenticación, persistencia, anonimización, intake interno, búsqueda semántica, clusters,
revisiones, resaltados, agente operativo, feedback y RAG normativo:

```bash
make e2e
```

Los límites de la prueba, sus escenarios geográficos y la matriz de cobertura están en la
[guía de pruebas](docs/testing.md). Los relatos son ficticios y los proveedores externos se
reemplazan por dobles deterministas; la API, reglas de dominio y base de datos sí se ejecutan
de extremo a extremo.

## Documentación técnica

- [Arquitectura](docs/architecture.md)
- [Despliegue en Google Cloud](docs/gcp-deployment.md)
- [Pruebas automatizadas](docs/testing.md)
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
