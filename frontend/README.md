# SGCIU Frontend

Interfaz React y Vite para el registro ciudadano y el espacio administrativo de SGCIU.

## Desarrollo local

Desde esta carpeta, con Node.js 22:

```bash
npm ci
npm run dev
```

El backend debe estar disponible en `http://localhost:8000`. Para usar otra URL, configure
`VITE_API_BASE_URL` al iniciar Vite o construir la imagen. Es una configuración pública
del navegador; no coloque credenciales en variables `VITE_*`.

## Construcción

```bash
npm run build
npm run preview
```

Vite genera `dist/`. La imagen de producción sirve ese directorio mediante Nginx en
el puerto 8080. El `Dockerfile` recibe `VITE_API_BASE_URL` como argumento de construcción.

## Organización

- `src/App.jsx`: flujos ciudadano y administrativo, formularios y paneles actuales.
- `src/styles.css`: estilos de la interfaz.
- `src/main.jsx`: entrada de React.
- `branding/`: recursos gráficos utilizados por la interfaz.
- `nginx.conf`: servicio de archivos y navegación de la aplicación en producción.

Los formularios actuales se implementan en `App.jsx`; los datos conversacionales y su
validación se gestionan en el backend. Consulte el README de la raíz para iniciar
la solución completa con Docker Compose.
