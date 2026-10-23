# Auditoría de preparación para publicación

Fecha de revisión: 22 de octubre de 2026 (Costa Rica).

## Alcance

Se revisaron los 133 commits disponibles al inicio, todas las ramas locales/remotas,
la etiqueta de entrega y las referencias de los 24 pull requests, incluidas las de
ramas eliminadas. También se descargaron los logs de las 48 ejecuciones de GitHub
Actions disponibles y los textos de issues/comentarios. El repositorio no tenía
releases, artefactos de Actions ni webhooks adicionales que revisar.

Los escaneos incluyeron 15 manifiestos históricos distintos y 190 combinaciones de
paquete/versión; extracción de 29 PDF y OCR de diez imágenes únicas, incluidas las
capturas incrustadas en la presentación; código Python/React; imágenes de producción;
autenticación, autorización, sesiones y exposición de la infraestructura utilizada.

La copia de recuperación y los resultados detallados de los escáneres se conservan
fuera del repositorio. No se incluyen volcados de la base de datos, secretos ni logs
privados en la publicación.

## Hallazgos y correcciones

| Hallazgo | Resultado |
| --- | --- |
| Posibles secretos en el historial | Las 15 coincidencias de Gitleaks eran identificadores públicos del corpus o sus fixtures. Se documentaron como excepciones por fingerprint exacto; no se excluyeron carpetas completas. El `.env` histórico estaba vacío. |
| Privacidad en documentos/logs | No se detectaron llaves reales en los textos/OCR ni en los logs descargados. El candidato de correo en los PDF corresponde al dominio institucional público del reglamento. La autoría personal se conserva por decisión del autor. |
| Dependencias históricas | Trece combinaciones antiguas tienen avisos de seguridad y existen requisitos históricos sin versión fija. Se conservan como historia no soportada; no representan las imágenes actuales. |
| Imágenes anteriores | Trivy registró 66 coincidencias altas/críticas en backend y 59 en frontend, con duplicaciones por bibliotecas que comparten CVE. Se actualizaron las bases, paquetes y dependencias transitivas, se retiró pip de la imagen de runtime y Nginx pasó a un usuario sin privilegios. |
| Aislamiento de conversaciones | Se añadió capacidad ciudadana separada con hash y caducidad, propietario de sesiones internas/operativas y separación de audiencias. Las sesiones previas sin estos datos requieren iniciarse de nuevo. |
| Reenvíos y abuso | Se impide enviar dos veces la misma sesión; se añaden cuotas atómicas compartidas, límites de cuerpo/contexto/salida y protección de intentos de login. Las escrituras públicas heredadas se deshabilitan en producción. |
| Errores y retención | Se evita reflejar payloads privados en errores, se ocultan parámetros SQL y texto sensible de excepciones y se utiliza `store=False` en el agente operativo. |
| Infraestructura | Se exige TLS en Cloud SQL y se retiran los roles de Editor, administrador de Cloud Run y escritor de imágenes de la antigua cuenta Compute, que no utiliza el despliegue actual. No se abren redes autorizadas a la base de datos. |
| Prevención | Se añaden Gitleaks/Bandit/Trivy a CI, CodeQL, Dependabot y política de seguridad. GitHub debe exigir las comprobaciones antes de aceptar cambios en las ramas soportadas. |

## Evidencia de validación

- 113 pruebas aprobadas; cobertura del 79,28 % en la ejecución local registrada.
- Migraciones verificadas desde cero en SQLite y PostgreSQL con pgvector.
- PostgreSQL: 40 intentos simultáneos contra una cuota de siete permitieron exactamente
  siete; dos envíos concurrentes de una misma sesión crearon un único incidente.
- Imágenes Linux AMD64 reconstruidas: cero hallazgos altos/críticos en Trivy, sin
  ignorar vulnerabilidades sin parche disponible.
- Auditorías actuales de Python y npm sin vulnerabilidades conocidas; Bandit sin
  hallazgos medios/altos y Semgrep sin hallazgos en los conjuntos aplicados.
- Escaneos históricos y de logs/documentos sin credenciales reales detectadas.

La entrega debe completar además CI en GitHub y el despliegue con sus smoke tests antes
de cambiar la visibilidad del repositorio.

## Límites

Esta revisión no garantiza ausencia de vulnerabilidades futuras. No constituye un
pentest destructivo, una certificación normativa ni una auditoría de la infraestructura
interna de GCP/OpenAI. Los requisitos históricos sin fijar no permiten reconstruir
exactamente cada entorno pasado. Los escáneres de secretos y el OCR pueden omitir patrones
desconocidos o texto ilegible; los resultados se contrastaron con revisión manual del código.

Las referencias archivadas conservan código antiguo deliberadamente: publicar la historia
no implica que esas versiones sean seguras para ejecutarse. Las URLs públicas permanecen
operativas para la demostración, bajo los controles de autorización y cuotas descritos.

## Referencias

- [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [GitHub: tratamiento de datos sensibles en el historial](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [OSV: base de avisos de dependencias](https://osv.dev/)
- [Gitleaks](https://github.com/gitleaks/gitleaks), [Bandit](https://bandit.readthedocs.io/), [Trivy](https://trivy.dev/), [Semgrep](https://semgrep.dev/)
