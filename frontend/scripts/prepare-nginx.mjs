import { readFileSync, writeFileSync } from 'node:fs';

const url = new URL(process.env.VITE_API_BASE_URL || 'http://localhost:8000');
if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))) {
  throw new Error('The API must use HTTPS, or a local development origin.');
}
if (url.username || url.password) throw new Error('Credentials must never appear in the API URL.');
writeFileSync('nginx.runtime.conf', readFileSync('nginx.conf', 'utf8').replaceAll('__API_ORIGIN__', url.origin));
