# Resumen ejecutivo de pruebas híbridas de IA

## Propósito

Se realizó una evaluación híbrida de la plataforma SGCIU para medir, en un escenario
controlado pero representativo, la calidad de las respuestas generadas por los módulos
de IA, su latencia, coste y capacidad para relacionar incidentes similares. El objetivo
fue obtener evidencia cuantitativa para la memoria del TFM y detectar oportunidades de
mejora antes de una evaluación posterior con casos reales.

La ejecución se identificó como `hybrid-manual-20260913-final`. Se excluyó del cálculo
el coste de OpenAI usado para simular al ciudadano, porque ese coste no existe en el uso
normal: en producción, la persona usuaria escribe directamente en el formulario.

## Por qué se realizó la prueba

Las pruebas funcionales confirman que la plataforma opera; sin embargo, no demuestran
por sí solas que las extracciones de IA sean correctas ni cuantifican su coste o tiempo
de respuesta. La evaluación cubre cuatro preguntas:

1. ¿La IA interpreta correctamente la categoría, distrito, relación, lugar y fecha?
2. ¿Qué rendimiento temporal y económico tiene cada denuncia procesada?
3. ¿La similitud semántica identifica incidentes relacionados sin agrupar casos no
   relacionados en exceso?
4. ¿Los resultados automáticos coinciden con la valoración humana?

## Cómo se realizó

Se ejecutaron localmente 90 escenarios reproducibles contra Cloud SQL de producción,
sin usar Cloud Build para la carga de datos. Cada escenario fue procesado mediante el
flujo real de intake, extracción estructurada, persistencia, embeddings y clustering.

Un agente de OpenAI interpretó el papel de una persona residente del cantón de Flores y
generó conversaciones naturales a partir de hechos definidos, sin recibir la categoría
esperada ni el grupo de clustering. La muestra incluyó los distritos de San Joaquín,
Barrantes y Llorente, y combinó denuncias anónimas, con contacto completo, con contacto
parcial y registradas por personal administrativo. Las fechas de ocurrencia y registro
se distribuyeron entre enero y septiembre de 2026.

Las personas revisoras validaron manualmente los 90 resultados mediante las columnas
`SÍ/NO` del libro de evaluación. Esta validación humana es la referencia principal para
calidad semántica cuando la etiqueta sintética no refleja exactamente lo expresado en la
conversación.

## Elementos sometidos a prueba

| Componente | Evidencia evaluada |
| --- | --- |
| Intake conversacional | Captura de la denuncia, turnos, cierre y resumen generado. |
| Clasificación | Categoría preliminar asignada al incidente. |
| Extracción territorial | Distrito y dirección de referencia. |
| Extracción temporal | Fecha normalizada del momento del hecho. |
| Contexto de la persona reportante | Relación con el incidente. |
| Tipo de lugar | Casa, escuela, establecimiento, parque u otro. |
| Embeddings y clustering | Pares de incidentes esperados frente a pares relacionados encontrados. |
| Operación de IA | Latencia, tokens y coste estimado de SGCIU. |

## Tipos de métricas obtenidas

- **Calidad automática:** coincidencia entre la etiqueta sintética esperada y el valor
  extraído.
- **Calidad manual:** proporción de resultados aprobados por la persona revisora.
- **Operación:** latencia media, mediana y percentil 95; tokens de entrada y salida; y
  coste estimado atribuible a SGCIU.
- **Clustering:** precisión, recall y F1 calculados sobre pares de incidentes
  relacionados.
- **Completitud:** porcentaje de sesiones cerradas sin necesitar un cierre forzado.

## Métricas finales

| Área | Métrica | Resultado |
| --- | --- | ---: |
| Muestra | Casos procesados y revisados | 90 / 90 |
| Calidad manual | Categoría correcta | 90.0% (81/90) |
| Calidad manual | Distrito correcto | 100.0% (90/90) |
| Calidad manual | Relación correcta | 84.4% (76/90) |
| Calidad manual | Tipo de lugar correcto | 10.0% (9/90) |
| Calidad manual | Fecha correcta | 100.0% (90/90) |
| Calidad automática | Categoría | 86.7% |
| Calidad automática | Distrito | 100.0% |
| Calidad automática | Relación | 27.8% |
| Calidad automática | Tipo de lugar | 17.8% |
| Calidad automática | Fecha | 100.0% |
| Conversación | Cierre sin forzar | 74.4% (67/90) |
| Conversación | Cierre forzado | 25.6% (23/90) |
| Rendimiento | Latencia media | 28.21 s |
| Rendimiento | Latencia p50 | 24.36 s |
| Rendimiento | Latencia p95 | 49.26 s |
| Coste | Tokens de entrada | 397,872 |
| Coste | Tokens de salida | 162,925 |
| Coste | Coste total atribuible a SGCIU | USD 4.7955 |
| Coste | Coste medio por caso | USD 0.0533 |
| Embeddings | Incidentes indexados / fallidos | 90 / 0 |
| Embeddings | Coste estimado | USD 0.000274 |
| Clustering | Pares esperados / predichos | 36 / 88 |
| Clustering | Precisión | 39.8% |
| Clustering | Recall | 97.2% |
| Clustering | F1 | 56.5% |

## Interpretación y limitaciones

La categoría, el distrito y la fecha presentan resultados altos. La relación también
obtiene un resultado alto bajo evaluación humana; su métrica automática baja se explica
porque varias etiquetas sintéticas no coinciden con el papel que la persona asumió en la
conversación. Por ejemplo, una persona que relata “vi” un hecho se clasifica de forma
razonable como testigo, aunque la etiqueta sintética esperada indicara otro rol.

El tipo de lugar es la principal oportunidad de mejora. En 60 de los 90 casos no se
extrajo un tipo de lugar, porque los relatos incluían referencias geográficas como
“cerca del parque” o “costado de la iglesia” sin indicar explícitamente dónde ocurrió
el incidente. El agente evitó inventar ese dato. Por ello, esta métrica evalúa tanto el
diseño del caso como la extracción del modelo. Se recomienda añadir una pregunta de
seguimiento obligatoria para solicitar el tipo de lugar cuando no sea explícito.

El clustering logra encontrar casi todos los pares esperados, pero su precisión es
moderada. Esto indica una estrategia sensible que tiende a sobreagrupar incidentes. La
siguiente iteración debe calibrar el umbral de similitud y requerir mayor coincidencia
temporal, geográfica o categórica para reducir falsos positivos.
