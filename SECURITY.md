# Seguridad y versiones soportadas

Las ramas soportadas son `main` (producción) y `Develop` (integración).
Las etiquetas `archive/*` y las entregas históricas conservan el desarrollo del TFM;
pueden contener dependencias y controles antiguos y **no deben desplegarse** como
versiones actuales. Su presencia no equivale a soporte de seguridad.

Para comunicar una vulnerabilidad, utilice **Security → Report a vulnerability**
en este repositorio. No incluya credenciales, datos de ciudadanos ni pruebas de
explotación contra producción en issues públicos.

## Controles del proyecto

- Secretos de producción en Secret Manager; no se empaquetan en Git ni en las imágenes.
- Sesiones institucionales opacas de ocho horas; se almacena el hash del token.
  Las contraseñas se verifican mediante PBKDF2 con sal individual.
- Cada conversación institucional pertenece al usuario autenticado. El intake ciudadano
  requiere una capacidad aleatoria separada de su identificador, almacenada como hash,
  con vigencia de 24 horas. Las sesiones internas no pueden abrirse con el API ciudadano.
- En producción, las escrituras heredadas `/complaints`, `/submissions` y
  `/ai/intake/chat` están deshabilitadas. El formulario utiliza `/v1/intake/sessions`.
- Límite de 64 KiB por solicitud, veinte turnos de intake y 64.000 caracteres acumulados.
  Una sesión enviada no puede volver a crear un incidente.
- Cuotas compartidas mediante PostgreSQL para todas las instancias: cinco intentos de
  login por cuenta y minuto; límites por peer de conexión y globales; máximo inicial de
  500 solicitudes de IA diarias. No se confía en `X-Forwarded-For` enviado por clientes.
  `PUBLIC_AI_DAILY_REQUEST_LIMIT` permite ajustar el último límite. Son cuotas de
  solicitudes, no un presupuesto monetario exacto ni un sustituto de un WAF.
- Respuestas de IA con límites de salida y `store=False`. La conversación del agente
  se mantiene explícitamente en la aplicación sin encadenar respuestas almacenadas por
  el proveedor. Esto no cambia las condiciones generales de retención del proveedor.
- React no inserta HTML de las denuncias. El frontend aplica CSP con el origen concreto
  de la API, protección contra framing, HSTS y `no-store`. Ambos contenedores usan
  usuarios sin privilegios.
- Errores de validación sin copia del input, parámetros SQL ocultos y logs sin texto de
  excepciones ni identificadores concretos de sesiones en los mensajes de aplicación.
- CI comprueba secretos históricos, Bandit, auditorías de Python/npm y vulnerabilidades
  altas/críticas del sistema operativo y las dependencias de las imágenes. Dependabot
  y CodeQL mantienen la revisión posterior a la publicación.

Los dominios del frontend/backend y los identificadores de infraestructura no son secretos:
la seguridad depende de los controles anteriores, no de ocultar sus URLs. Conocerlos no
otorga acceso a datos institucionales ni a credenciales cloud.

El [informe de auditoría](docs/security-audit.md) documenta el alcance y sus límites.
