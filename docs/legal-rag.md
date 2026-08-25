# RAG normativo de SGCIU

## Objetivo y alcance

Este módulo ayuda al personal autorizado de la Policía Municipal de Flores a localizar y
comprender normativa relevante. No determina culpabilidad, no sustituye asesoría jurídica y
no convierte una recomendación de protocolo en una obligación legal.

El corpus `2026.08.1` contiene 16 documentos nacionales y municipales. El archivo
`backend/corpus/legal/manifest.json` es la fuente de verdad para títulos, autoridad, prioridad,
checksum y vacíos conocidos. Los PDF normalizados están en `backend/corpus/legal/pdfs/`.

El Decreto Ejecutivo 44486-S aportado originalmente estaba incompleto y terminaba en el
artículo 1. Fue sustituido por el extracto íntegro de las páginas 40 a 65 del
[Alcance N.º 114 a La Gaceta N.º 110](https://www.imprentanacional.go.cr/pub/2024/06/18/ALCA114_18_06_2024.pdf),
que incluye sus 40 artículos y el transitorio.

Vacíos conocidos que deben incorporarse en una versión posterior del corpus:

- Constitución Política de Costa Rica;
- Código Procesal Penal;
- protocolo oficial de cadena de custodia.

## Decisiones técnicas

- Cada chunk pertenece a una única página física del PDF.
- Tamaño objetivo: 512 tokens estimados; overlap: 77 tokens, cercano al 15%.
- Los encabezados de artículo se usan como límites naturales cuando están disponibles.
- Modelo por defecto: `text-embedding-3-large`, adecuado para recuperación multilingüe,
  con 1536 dimensiones configurables.
- Búsqueda híbrida: HNSW/coseno + BM25 + reciprocal-rank fusion.
- Diversificación: máximo tres fragmentos por documento y eliminación por hash de duplicados.
- Contexto de generación: hasta ocho fragmentos con identificadores `[F1]`, `[F2]`, etc.
- Respuesta estructurada, validación posterior de citas y abstención segura.
- Auditoría: hash de consulta, chunks citados, modelos, versión de prompt, tokens y latencia.

La API de embeddings de OpenAI acepta entradas en lote y permite reducir las dimensiones de
los modelos `text-embedding-3`. La configuración utilizada conserva lotes pequeños para no
acercarse al límite de tokens por solicitud. Véanse la
[referencia oficial de embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
y la [ficha de text-embedding-3-large](https://developers.openai.com/api/docs/models/text-embedding-3-large).

## Operación local

Configure `OPENAI_API_KEY`, inicie PostgreSQL y ejecute:

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m app.cli --role admin --transport mcp
```

En el menú use `7. Consultar normativa (RAG)`:

1. `Ver estado del corpus` muestra documentos, páginas, embeddings y vacíos.
2. `Indexar o actualizar documentos` valida e indexa únicamente cambios.
3. `Consultar normativa` genera una respuesta con fuentes verificables.

La primera indexación actual genera 3.505 embeddings. El número puede cambiar de forma
controlada cuando se actualice un PDF, el algoritmo de chunking o la versión del corpus.

## API y MCP

Endpoints administrativos:

- `GET /v1/legal-rag/corpus`
- `POST /v1/legal-rag/corpus/index`
- `POST /v1/legal-rag/query`

Cuando `REQUIRE_ADMIN_AUTH=true`, se exige `X-Admin-Key`.

Tools MCP de solo lectura:

- `search_legal_sources`: recuperación híbrida con evidencia y localizador exacto;
- `get_legal_corpus_status`: cobertura y versión del índice.

El agente ReAct operativo puede usar estas tools para preguntas mixtas. Para una consulta
normativa pura se recomienda la opción RAG dedicada, porque aplica generación estructurada y
validación de atribución adicional.

## Evaluación

Pruebas deterministas:

```bash
.venv/bin/ruff check app tests migrations
.venv/bin/pytest --cov=app --cov-fail-under=70
```

Evaluación real de recuperación, con consumo de OpenAI:

```bash
PYTHONPATH=. .venv/bin/python -m app.evaluation.legal_rag_runner
```

El reporte calcula `Hit@1`, `Hit@3`, `Hit@8`, MRR y latencia sobre 12 preguntas sintéticas.
Para la evaluación cualitativa del TFM se recomienda además revisar una muestra estratificada
con estos criterios: exactitud jurídica, groundedness, cobertura de citas, utilidad operativa,
abstención apropiada y claridad. Toda respuesta sensible debe ser validada por personal con
competencia institucional.
