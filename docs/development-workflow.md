# Flujo de ramas y despliegue

## Ramas protegidas

- `main` representa exactamente la versión de producción. No recibe pushes directos.
- `Develop` es la rama de integración y pruebas. Toda funcionalidad parte de ella en una
  rama breve `feature/*`, `fix/*`, `test/*` o `docs/*`.
- Una funcionalidad entra a `Develop` mediante pull request y pasa CI completa.
- Una entrega entra a `main` únicamente mediante un pull request `Develop` → `main`.
- Un merge confirmado en `main` activa Cloud Build y despliega automáticamente en GCP.

La acción `validate-release-flow` rechaza pull requests hacia `main` cuyo origen no sea
`Develop`. Las protecciones remotas deben exigir, como mínimo, los checks `verify-backend`,
`verify-frontend`, `verify-infrastructure` y `verify-images`, una rama actualizada y todas las
conversaciones resueltas.

## Trabajo cotidiano

```bash
git switch Develop
git pull --ff-only origin Develop
git switch -c feature/nombre-breve

# Cambios y commits pequeños
make verify
git push -u origin feature/nombre-breve
```

Abra un PR hacia `Develop`, espere los checks y revise el diff. Para preparar una versión:

```bash
git switch Develop
git pull --ff-only origin Develop
# Abra un PR con base main y compare Develop.
```

No se ejecuta un despliegue de producción desde `Develop`: esta rama valida código e imágenes,
pero el trigger de GCP escucha exclusivamente `^main$`. Así, GitHub conserva la aprobación y
Cloud Build conserva la evidencia exacta del commit desplegado.

## Qué valida cada capa

| Capa | Validaciones |
| --- | --- |
| Pull request / push | Ruff, migración vacía, 78 pruebas incluida E2E, cobertura ≥ 70%, auditorías Python/npm, build frontend, coste y archivos de infraestructura |
| Imágenes | Build real de backend y frontend desde bases fijadas por digest |
| Cloud Build en `main` | Repite validaciones, migra, aprovisiona usuarios, indexa RAG, despliega revisiones inmutables y ejecuta smoke tests públicos |
| Cloud Monitoring | Uptime, 5xx, p95, PostgreSQL y anomalías de coste de IA |

## Incidente y rollback

Si falla cualquier validación previa, no se publica ni despliega una imagen. Si falla una
migración, no se crea una revisión nueva. Si el smoke test posterior falla, el build queda
rojo y debe restaurarse el tráfico a la revisión sana anterior desde Cloud Run; nunca se
reutiliza o sobrescribe el tag SHA que identifica una entrega.

Los cambios urgentes también se integran primero en `Develop`; esto evita que `main` y la rama
de pruebas diverjan. Después del rollback, abra un `fix/*`, reproduzca el fallo, añada una
prueba de regresión y repita el flujo normal.
