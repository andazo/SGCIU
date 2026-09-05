import { useEffect, useMemo, useRef, useState } from 'react';
import logoFlores from '../branding/logoFlores.png';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const ADMIN_ROUTE = '/admin';
const ADMIN_AUTH_STORAGE_KEY = 'sgciu.admin.auth';
const CITIZEN_SESSION_STORAGE_KEY = 'sgciu.citizen.intake.session';
const OPERATIONAL_SESSION_STORAGE_KEY = 'sgciu.operational.session';
const NAV_ITEMS = [
  { label: 'Inicio', icon: '⌂' },
  { label: 'Registrar incidente', icon: '+' },
  { label: 'Incidentes', icon: '!' },
  { label: 'Agrupación recurrente', icon: '↻' },
  { label: 'Analítica', icon: '∿' },
  { label: 'Asistente de Políticas', icon: '?' },
];
const DISTRICTS = ['Todos', 'San Joaquin', 'Barrantes', 'Llorente'];

const INITIAL_EXTRACTED_DATA = {
  descripcion_detallada: null,
  relacion_incidente: null,
  categoria_preliminar: null,
  distrito: null,
  direccion_exacta: null,
  tipo_lugar: null,
  fecha_hora_aproximada: null,
};

const SUMMARY_LABELS = {
  descripcion_detallada: 'Descripción incidente',
  relacion_incidente: 'Relación con el incidente',
  categoria_preliminar: 'Categoría preliminar',
  distrito: 'Distrito',
  direccion_exacta: 'Dirección exacta',
  tipo_lugar: 'Tipo de lugar',
  fecha_hora_aproximada: 'Fecha y hora aproximada',
};

const VALUE_LABELS = {
  ruido: 'Ruido',
  vehiculo_sospechoso: 'Vehículo sospechoso',
  venta_drogas: 'Venta de drogas',
  violencia: 'Violencia',
  robo: 'Robo',
  vandalismo: 'Vandalismo',
  persona_sospechosa: 'Persona sospechosa',
  emergencia: 'Emergencia',
  disturbio_publico: 'Disturbio público',
  basura_o_contaminacion: 'Basura o contaminación',
  alumbrado_publico: 'Alumbrado público',
  obstruccion_via_publica: 'Obstrucción de vía pública',
  animal_peligroso: 'Animal peligroso',
  consumo_alcohol_drogas: 'Consumo de alcohol o drogas',
  acoso_o_amenaza: 'Acoso o amenaza',
  problema_transito: 'Problema de tránsito',
  otro: 'Otro',
  victima: 'Víctima',
  testigo: 'Testigo',
  vecino: 'Vecino',
  comerciante: 'Comerciante',
  establecimiento: 'Establecimiento',
  casa: 'Casa',
  parque: 'Parque',
  escuela: 'Escuela',
};

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  let storedAuth = null;
  try {
    storedAuth = JSON.parse(sessionStorage.getItem(ADMIN_AUTH_STORAGE_KEY) || 'null');
  } catch {
    sessionStorage.removeItem(ADMIN_AUTH_STORAGE_KEY);
  }
  if (storedAuth?.access_token && !path.startsWith('/v1/auth/login')) {
    headers.set('Authorization', `Bearer ${storedAuth.access_token}`);
  }
  const response = await fetch(API_BASE_URL + path, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/v1/auth/')) {
      sessionStorage.removeItem(ADMIN_AUTH_STORAGE_KEY);
      window.dispatchEvent(new Event('sgciu-auth-expired'));
    }
    let message = 'La operación no se pudo completar (' + response.status + ').';
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      const body = await response.text();
      if (body) {
        message = body;
      }
    }
    throw new Error(message);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function normalizeValue(value) {
  if (value === null || value === undefined || value === '') {
    return 'Pendiente';
  }

  return VALUE_LABELS[value] ?? String(value).replaceAll('_', ' ');
}

function formatDateTime(value) {
  if (!value) {
    return 'Sin registrar';
  }

  return new Intl.DateTimeFormat('es-CR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function toDateKey(date) {
  return date.toISOString().slice(0, 10);
}

function getLastSevenDays() {
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() - (6 - index));
    return date;
  });
}

function countBy(items, getKey) {
  return items.reduce((counts, item) => {
    const key = getKey(item) || 'sin_clasificar';
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
}

function buildDetailBullets(extractedData) {
  return Object.entries(SUMMARY_LABELS)
    .filter(([key]) => key !== 'descripcion_detallada' && extractedData[key])
    .map(([key, label]) => ({
      label,
      value: normalizeValue(extractedData[key]),
    }));
}

function renderInlineMessage(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function ChatMessageContent({ content }) {
  const normalizedContent = content
    .replace(/\r\n/g, '\n')
    .replace(/\s+-\s+(?=[A-ZÁÉÍÓÚÑ][^:\n]{0,80}:)/g, '\n- ');
  const lines = normalizedContent.split('\n');

  return (
    <div className="chatFormattedContent">
      {lines.map((line, index) => {
        const trimmedLine = line.trim();
        if (!trimmedLine) {
          return <div className="chatMessageSpacer" key={`spacer-${index}`} />;
        }
        if (/^[-*]\s+/.test(trimmedLine)) {
          return (
            <div className="chatMessageBullet" key={`bullet-${index}`}>
              <span aria-hidden="true">•</span>
              <span>{renderInlineMessage(trimmedLine.slice(2))}</span>
            </div>
          );
        }
        return <p key={`line-${index}`}>{renderInlineMessage(trimmedLine)}</p>;
      })}
    </div>
  );
}

function ChatTranscript({ messages, isLoading, loadingLabel = 'Procesando información' }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isLoading]);

  return (
    <div className="chatMessages" aria-live="polite" aria-busy={isLoading}>
      {messages.map((message, index) => (
        <div className={`chatBubble ${message.role}`} key={`${message.role}-${index}`}>
          <ChatMessageContent content={message.content} />
        </div>
      ))}
      {isLoading && (
        <div className="chatBubble assistant chatProcessing" role="status">
          <span className="chatTypingDots" aria-hidden="true"><i /><i /><i /></span>
          <p>{loadingLabel}…</p>
        </div>
      )}
      <div ref={endRef} aria-hidden="true" />
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <article className="adminStat">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function WeeklyReportsChart({ complaints }) {
  const days = getLastSevenDays();
  const counts = countBy(complaints, (complaint) => toDateKey(new Date(complaint.created_at)));
  const maxCount = Math.max(1, ...days.map((day) => counts[toDateKey(day)] ?? 0));
  const width = 640;
  const height = 220;
  const padding = 28;
  const points = days.map((day, index) => {
    const count = counts[toDateKey(day)] ?? 0;
    const x = padding + index * ((width - padding * 2) / (days.length - 1));
    const y = height - padding - (count / maxCount) * (height - padding * 2);

    return { count, day, x, y };
  });
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');

  return (
    <div className="adminLineChart" aria-label="Incidentes reportados en los últimos 7 días">
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <path className="lineGrid" d={`M ${padding} ${height - padding} H ${width - padding}`} />
        <path className="lineGrid" d={`M ${padding} ${height / 2} H ${width - padding}`} />
        <path className="lineStroke" d={path} />
        {points.map((point) => (
          <g key={toDateKey(point.day)}>
            <circle className="lineDot" cx={point.x} cy={point.y} r="5" />
            <text className="lineValue" x={point.x} y={Math.max(16, point.y - 12)}>
              {point.count}
            </text>
            <text className="lineLabel" x={point.x} y={height - 6}>
              {new Intl.DateTimeFormat('es-CR', { weekday: 'short' }).format(point.day)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function CategoryChart({ complaints }) {
  const recentStart = new Date();
  recentStart.setHours(0, 0, 0, 0);
  recentStart.setDate(recentStart.getDate() - 6);

  const recentComplaints = complaints.filter(
    (complaint) => new Date(complaint.created_at) >= recentStart,
  );
  const categories = Object.entries(
    countBy(recentComplaints, (complaint) => complaint.ai_extracted_data?.categoria_preliminar),
  )
    .sort(([, countA], [, countB]) => countB - countA)
    .slice(0, 5);
  const maxCount = Math.max(1, ...categories.map(([, count]) => count));

  if (categories.length === 0) {
    return <p className="adminEmpty">Sin datos para los últimos 7 días.</p>;
  }

  return (
    <div className="adminCategoryChart" aria-label="Incidentes por categorías últimos 7 días">
      {categories.map(([category, count]) => (
        <div className="adminCategoryRow" key={category}>
          <span>{normalizeValue(category)}</span>
          <div className="adminCategoryTrack">
            <div className="adminCategoryFill" style={{ width: `${(count / maxCount) * 100}%` }} />
          </div>
          <strong>{count}</strong>
        </div>
      ))}
    </div>
  );
}

function RecurrentPatternsPanel({ patterns, isLoading, error }) {
  if (isLoading) {
    return <p className="adminEmpty">Buscando patrones recurrentes...</p>;
  }

  if (error) {
    return <p className="statusMessage error">{error}</p>;
  }

  if (patterns.length === 0) {
    return (
      <p className="adminEmpty">
        No se han detectado patrones recurrentes en los últimos 30 días.
      </p>
    );
  }

  return (
    <div className="recurrentPatternList">
      {patterns.map((pattern) => (
        <article className="recurrentPatternCard" key={pattern.id}>
          <div className="recurrentPatternHeader">
            <div>
              <span className="eyebrow">Patrón recurrente #{pattern.id}</span>
              <h2>{pattern.title}</h2>
            </div>
            <strong>{pattern.incident_count} incidentes</strong>
          </div>
          <p className="recurrentPatternSummary">
            Repetición detectada entre {formatDateTime(pattern.first_seen)} y{' '}
            {formatDateTime(pattern.last_seen)}. Similitud promedio:{' '}
            {(pattern.average_similarity * 100).toFixed(0)}%.
          </p>
          <div className="recurrentPatternBadges">
            <span className="tableBadge district">{normalizeValue(pattern.district)}</span>
            <span className="tableBadge category">{normalizeValue(pattern.category)}</span>
            {pattern.signals.map((signal) => (
              <span className="patternSignal" key={signal}>{signal}</span>
            ))}
          </div>
          <div className="adminTableWrap">
            <table className="adminTable">
              <thead>
                <tr>
                  <th>Incidente</th>
                  <th>Fecha</th>
                  <th>Ubicación</th>
                  <th>Coincidencias</th>
                </tr>
              </thead>
              <tbody>
                {pattern.members.map((member) => (
                  <tr key={member.incident_id}>
                    <td><span className="idBadge">#{member.incident_id}</span></td>
                    <td>{formatDateTime(member.created_at)}</td>
                    <td>{member.address || 'Sin dirección registrada'}</td>
                    <td>
                      {(member.similarity_score * 100).toFixed(0)}% · {member.match_reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ))}
    </div>
  );
}

function CandidateClustersPanel({ clusters, isLoading, error }) {
  if (isLoading) {
    return <p className="adminEmpty">Cargando clusters candidatos...</p>;
  }
  if (error) {
    return <p className="statusMessage error">{error}</p>;
  }
  if (clusters.length === 0) {
    return <p className="adminEmpty">No hay clusters candidatos disponibles.</p>;
  }
  return (
    <div className="candidateClusterList">
      {clusters.map((cluster) => (
        <article className="candidateClusterCard" key={cluster.id}>
          <div>
            <span className="eyebrow">Cluster #{cluster.id} · {cluster.status}</span>
            <h3>{cluster.label}</h3>
          </div>
          <p>{cluster.explanation || 'Agrupación generada a partir de similitud semántica.'}</p>
          <div className="clusterMembers">
            {cluster.members.map((member) => (
              <span key={member.incident_id}>
                #{member.incident_id} · {(member.similarity_score * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function ReviewsPanel({ onRefresh }) {
  const [reviews, setReviews] = useState([]);
  const [highlights, setHighlights] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isHighlightsLoading, setIsHighlightsLoading] = useState(true);
  const [error, setError] = useState('');
  const [workingId, setWorkingId] = useState(null);
  const [assessmentMessage, setAssessmentMessage] = useState('');

  async function loadReviews() {
    setIsLoading(true);
    setError('');
    try {
      setReviews(await apiRequest('/v1/reviews?status=pending'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudieron cargar las revisiones.');
    } finally {
      setIsLoading(false);
    }
  }

  async function loadHighlights() {
    setIsHighlightsLoading(true);
    try {
      setHighlights(await apiRequest('/v1/reviews/highlights?status=pending'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudieron cargar los resaltados.');
    } finally {
      setIsHighlightsLoading(false);
    }
  }

  useEffect(() => {
    loadReviews();
    loadHighlights();
  }, []);

  async function transition(review, action) {
    setWorkingId(review.id);
    setError('');
    try {
      const path = action === 'resolve'
        ? '/v1/reviews/' + review.id + '/resolve'
        : '/v1/reviews/' + review.id + '/transition';
      await apiRequest(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          action === 'resolve'
            ? { notes: 'Gestionado desde el panel administrativo.' }
            : { notes: 'Gestionado desde el panel administrativo.', action },
        ),
      });
      await loadReviews();
      await loadHighlights();
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo actualizar la revisión.');
    } finally {
      setWorkingId(null);
    }
  }

  async function transitionHighlight(highlight, action) {
    setWorkingId('highlight-' + highlight.id);
    setError('');
    try {
      await apiRequest('/v1/reviews/highlights/' + highlight.id + '/transition', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notes: 'Gestionado desde el panel administrativo.',
          action,
        }),
      });
      await loadHighlights();
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo actualizar el resaltado.');
    } finally {
      setWorkingId(null);
    }
  }

  async function assessPending() {
    setWorkingId('assessment');
    setAssessmentMessage('');
    setError('');
    try {
      const result = await apiRequest('/v1/reviews/assess-pending', { method: 'POST' });
      setAssessmentMessage(
        'Análisis terminado: ' + result.completed + ' completados, ' + result.failed + ' fallidos.',
      );
      await loadReviews();
      await loadHighlights();
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo analizar la cola pendiente.');
    } finally {
      setWorkingId(null);
    }
  }

  return (
    <section className="adminPanel workspacePanel">
      <div className="sectionIntro">
        <div>
          <span className="eyebrow">Control humano</span>
          <h2>Revisiones pendientes</h2>
          <p>Revisa los casos que necesitan criterio administrativo y conserva la trazabilidad de la decisión.</p>
        </div>
        <div className="panelActions">
          <button className="secondaryButton" type="button" onClick={loadReviews}>↻ Actualizar</button>
          <button className="primaryButton" type="button" onClick={assessPending} disabled={workingId === 'assessment'}>
            {workingId === 'assessment' ? 'Analizando...' : 'Analizar pendientes con IA'}
          </button>
        </div>
      </div>
      {assessmentMessage && <p className="statusMessage success">{assessmentMessage}</p>}
      {error && <p className="statusMessage error">{error}</p>}
      {!isHighlightsLoading && highlights.length > 0 && (
        <section className="highlightSection">
          <div className="subPanelHeader">
            <span className="eyebrow">Atención prioritaria</span>
            <h3>Resaltados operativos</h3>
            <p>Señales que requieren una revisión rápida por su relevancia operacional.</p>
          </div>
          <div className="reviewList">
            {highlights.map((highlight) => (
              <article className="highlightCard" key={highlight.id}>
                <div className="reviewHeader">
                  <div>
                    <span className="eyebrow">Resaltado #{highlight.id} · incidente #{highlight.incident_id}</span>
                    <h3>{highlight.attention_level === 'priority' ? 'Atención prioritaria' : 'Revisar incidente'}</h3>
                  </div>
                  <span className="sourceBadge">{highlight.status}</span>
                </div>
                <p>{highlight.ai_summary}</p>
                {highlight.reasons?.length > 0 && <ul>{highlight.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
                <div className="panelActions">
                  <button className="secondaryButton" type="button" disabled={workingId === 'highlight-' + highlight.id} onClick={() => transitionHighlight(highlight, 'start')}>
                    Iniciar
                  </button>
                  <button className="primaryButton" type="button" disabled={workingId === 'highlight-' + highlight.id} onClick={() => transitionHighlight(highlight, 'resolve')}>
                    Resolver
                  </button>
                  <button className="ghostButton" type="button" disabled={workingId === 'highlight-' + highlight.id} onClick={() => transitionHighlight(highlight, 'escalate')}>
                    Escalar
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      {isLoading ? (
        <p className="adminEmpty">Cargando revisiones...</p>
      ) : reviews.length === 0 ? (
        <p className="adminEmpty">No hay revisiones pendientes.</p>
      ) : (
        <div className="reviewList">
          {reviews.map((review) => (
            <article className="reviewCard" key={review.id}>
              <div className="reviewHeader">
                <div>
                  <span className="eyebrow">Revisión #{review.id} · incidente #{review.incident_id}</span>
                  <h3>{review.reason}</h3>
                </div>
                <span className="sourceBadge">{review.review_type}</span>
              </div>
              {review.ai_summary && <p>{review.ai_summary}</p>}
              {review.quality_issues?.length > 0 && (
                <ul>
                  {review.quality_issues.map((issue) => <li key={issue}>{issue}</li>)}
                </ul>
              )}
              <div className="panelActions">
                <button className="secondaryButton" type="button" disabled={workingId === review.id} onClick={() => transition(review, 'start')}>
                  Iniciar
                </button>
                <button className="primaryButton" type="button" disabled={workingId === review.id} onClick={() => transition(review, 'resolve')}>
                  Resolver
                </button>
                <button className="secondaryButton" type="button" disabled={workingId === review.id} onClick={() => transition(review, 'escalate')}>
                  Escalar
                </button>
                <button className="ghostButton" type="button" disabled={workingId === review.id} onClick={() => transition(review, 'dismiss')}>
                  Descartar
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function IncidentTable({ incidents, selectedId, onSelect, isLoading }) {
  return (
    <div className="adminTableWrap">
      <table className="adminTable">
        <thead>
          <tr>
            <th>ID</th>
            <th>Registro</th>
            <th>Distrito</th>
            <th>Categoría</th>
            <th>Momento del hecho</th>
            <th>Origen</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan="6" className="adminEmptyTable">Cargando incidentes…</td></tr>
          ) : incidents.map((incident) => (
            <tr
              className={selectedId === incident.id ? 'isSelected' : ''}
              key={incident.id}
              onClick={() => onSelect(incident)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(incident);
                }
              }}
              tabIndex="0"
            >
              <td><span className="idBadge">#{incident.id}</span></td>
              <td>{formatDateTime(incident.created_at)}</td>
              <td>{normalizeValue(incident.ai_extracted_data?.distrito)}</td>
              <td>{normalizeValue(incident.ai_extracted_data?.categoria_preliminar)}</td>
              <td>
                <span className={'temporalBadge ' + (incident.ai_extracted_data?.temporal_relation || 'desconocido')}>
                  {normalizeValue(incident.ai_extracted_data?.temporal_relation)}
                </span>
              </td>
              <td>
                {incident.police_input
                  ? 'Personal · ' + (incident.entered_by_badge || 'sin badge')
                  : 'Ciudadano'}
              </td>
            </tr>
          ))}
          {incidents.length === 0 && (
            <tr>
              <td colSpan="6" className="adminEmptyTable">
                No hay incidentes que coincidan con los filtros.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function IncidentQualityCard({ incident, data }) {
  const fieldLabels = {
    descripcion_detallada: 'Descripción del incidente',
    distrito: 'Distrito',
    direccion_exacta: 'Ubicación exacta',
    fecha_hora_aproximada: 'Fecha y hora aproximada',
  };
  const missingFields = Object.entries(data.field_states || {})
    .filter(([, field]) => ['missing', 'ambiguous', 'unknown', 'declined'].includes(field?.status))
    .map(([field]) => fieldLabels[field] || SUMMARY_LABELS[field] || field);
  const qualityControl = incident.analysis_metadata?.quality_control;
  const issues = qualityControl?.issues?.length > 0
    ? qualityControl.issues
    : incident.review_reason
      ? [incident.review_reason]
      : missingFields;
  const hasLimitedReliability = qualityControl
    ? qualityControl.reliability === 'limited'
    : incident.requires_human_review || missingFields.length > 0;

  return (
    <section className={`qualityControlCard ${hasLimitedReliability ? 'isLimited' : 'isReliable'}`} aria-label="Control de calidad asistido por IA">
      <div className="qualityControlHeader">
        <span className="qualityControlIcon" aria-hidden="true">{hasLimitedReliability ? '!' : '✓'}</span>
        <div>
          <span className="eyebrow">Control de calidad asistido por IA</span>
          <h4>{hasLimitedReliability ? 'Fiabilidad limitada' : 'Información suficientemente completa'}</h4>
        </div>
      </div>
      {hasLimitedReliability ? (
        <>
          <p>La información contiene elementos incompletos o poco claros. Verifica estos datos antes de tomar una decisión operativa.</p>
          {issues.length > 0 && <ul>{issues.slice(0, 4).map((issue) => <li key={issue}>{issue}</li>)}</ul>}
          {missingFields.length > 0 && <p className="qualityControlMissing"><strong>Datos pendientes:</strong> {missingFields.join(', ')}.</p>}
        </>
      ) : (
        <p>La IA no detectó faltantes críticos en los datos estructurados del incidente.</p>
      )}
    </section>
  );
}

function IncidentDetail({ incident, related, isLoadingRelated, onFindRelated, onReindex }) {
  const data = incident?.ai_extracted_data || {};
  const isAnonymous = incident?.analysis_metadata?.anonymous === true
    || incident?.analysis_metadata?.registration_mode === 'anonymous';
  if (!incident) {
    return (
      <aside className="detailEmpty">
        <span className="detailIcon" aria-hidden="true">↗</span>
        <h3>Selecciona un incidente</h3>
        <p>Consulta el resumen, la ubicación y sus coincidencias semánticas.</p>
      </aside>
    );
  }

  return (
    <aside className="incidentDetail">
      <div className="detailHeader">
        <div>
          <span className="eyebrow">Ficha operativa</span>
          <h3>Incidente #{incident.id}</h3>
        </div>
        <span className={incident.police_input ? 'sourceBadge staff' : 'sourceBadge'}>
          {incident.police_input ? 'Personal' : 'Ciudadano'}
        </span>
      </div>
      <p className="detailSummary">
        {incident.ai_summary_text || data.descripcion_detallada || 'Sin resumen disponible.'}
      </p>
      <IncidentQualityCard incident={incident} data={data} />
      <section className="detailContactCard" aria-label="Procedencia y contacto del incidente">
        <h4>Procedencia y contacto</h4>
        {incident.police_input ? (
          <dl className="detailGrid detailContactGrid">
            <div><dt>Registrado por</dt><dd>Personal administrativo o policial</dd></div>
            <div><dt>Identificador</dt><dd>{incident.entered_by_badge || 'No disponible'}</dd></div>
          </dl>
        ) : isAnonymous ? (
          <dl className="detailGrid detailContactGrid">
            <div><dt>Modalidad</dt><dd>Registro anónimo</dd></div>
            <div><dt>Contacto</dt><dd>No proporcionado</dd></div>
          </dl>
        ) : (
          <dl className="detailGrid detailContactGrid">
            <div><dt>Nombre</dt><dd>{incident.name || 'No proporcionado'}</dd></div>
            <div><dt>Teléfono</dt><dd>{incident.phone || 'No proporcionado'}</dd></div>
            <div><dt>Correo</dt><dd>{incident.email || 'No proporcionado'}</dd></div>
          </dl>
        )}
      </section>
      <dl className="detailGrid">
        <div><dt>Categoría</dt><dd>{normalizeValue(data.categoria_preliminar)}</dd></div>
        <div><dt>Distrito</dt><dd>{normalizeValue(data.distrito)}</dd></div>
        <div><dt>Ubicación</dt><dd>{data.direccion_exacta || 'Pendiente'}</dd></div>
        <div><dt>Momento</dt><dd>{data.fecha_hora_aproximada || 'Pendiente'}</dd></div>
        <div><dt>Relación temporal</dt><dd>{normalizeValue(data.temporal_relation)}</dd></div>
        <div><dt>Estado del embedding</dt><dd>{incident.analysis_metadata?.embedding_status || 'Pendiente'}</dd></div>
      </dl>
      <div className="detailActions">
        <button className="secondaryButton" type="button" onClick={onFindRelated} disabled={isLoadingRelated}>
          {isLoadingRelated ? 'Buscando...' : 'Buscar similares'}
        </button>
        <button className="ghostButton" type="button" onClick={onReindex}>
          Recalcular embedding
        </button>
      </div>
      {related && (
        <section className="relatedResults">
          <h4>Incidentes relacionados</h4>
          {related.length === 0 ? (
            <p className="adminEmpty">No se encontraron coincidencias suficientes.</p>
          ) : (
            <ul>
              {related.map((item) => (
                <li key={item.incident_id}>
                  <strong>#{item.incident_id}</strong>
                  <span>{(item.similarity_score * 100).toFixed(0)}% · {item.match_reasons.join(', ')}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </aside>
  );
}

const INCIDENTS_PAGE_SIZE = 30;

function IncidentFilters({
  dateFilter,
  districtFilter,
  incidentSearch,
  setDateFilter,
  setDistrictFilter,
  setIncidentSearch,
  isOpen,
  onClose,
}) {
  const activeFilters = [dateFilter, districtFilter !== 'Todos' ? districtFilter : '', incidentSearch]
    .filter(Boolean).length;

  function clearFilters() {
    setDateFilter('');
    setDistrictFilter('Todos');
    setIncidentSearch('');
  }

  return (
    <aside
      className={`filterDrawer ${isOpen ? 'isOpen' : ''}`}
      aria-label="Filtros globales de incidentes"
      aria-hidden={!isOpen}
      role="dialog"
    >
      <div className="incidentFiltersHeader">
        <div>
          <span className="eyebrow">Filtros globales</span>
          <h2>Buscar información</h2>
          <p>Estos filtros se aplican en Inicio, Incidentes y Analítica.</p>
        </div>
        <div className="incidentFiltersActions">
          {activeFilters > 0 && <span className="filterCount">{activeFilters} activo{activeFilters > 1 ? 's' : ''}</span>}
          <button
            className="ghostButton"
            type="button"
            aria-label="Cerrar filtros"
            onClick={onClose}
          >
            Cerrar
          </button>
        </div>
      </div>
      <div className="incidentFilterFields" id="incident-filter-fields">
          <label className="field">
            <span>Fecha de registro</span>
            <input
              type="date"
              value={dateFilter}
              onChange={(event) => setDateFilter(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Distrito</span>
            <select value={districtFilter} onChange={(event) => setDistrictFilter(event.target.value)}>
              {DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}
            </select>
          </label>
          <label className="field">
            <span>ID del incidente</span>
            <input
              type="search"
              placeholder="Ej. 24"
              value={incidentSearch}
              onChange={(event) => setIncidentSearch(event.target.value)}
            />
          </label>
          {activeFilters > 0 && (
            <button className="clearFiltersButton" type="button" onClick={clearFilters}>
              Limpiar filtros
            </button>
          )}
      </div>
    </aside>
  );
}

function IncidentPagination({ currentPage, totalPages, totalItems, pageStart, pageEnd, onPageChange }) {
  if (totalItems === 0) return null;

  return (
    <nav className="incidentPagination" aria-label="Paginación de incidentes">
      <span className="paginationSummary">Mostrando {pageStart}–{pageEnd} de {totalItems}</span>
      <div className="paginationControls">
        <button
          className="ghostButton"
          type="button"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
        >
          Anterior
        </button>
        <span className="paginationPage">Página <strong>{currentPage}</strong> de {totalPages}</span>
        <button
          className="secondaryButton"
          type="button"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
        >
          Siguiente
        </button>
      </div>
    </nav>
  );
}

function IncidentsPanel({
  incidents,
  onRefresh,
  isLoading,
}) {
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [related, setRelated] = useState(null);
  const [isLoadingRelated, setIsLoadingRelated] = useState(false);
  const [actionMessage, setActionMessage] = useState('');
  const [error, setError] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(incidents.length / INCIDENTS_PAGE_SIZE));
  const pageStartIndex = (currentPage - 1) * INCIDENTS_PAGE_SIZE;
  const visibleIncidents = incidents.slice(pageStartIndex, pageStartIndex + INCIDENTS_PAGE_SIZE);

  useEffect(() => {
    setCurrentPage(1);
    setSelectedIncident(null);
    setRelated(null);
  }, [incidents]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  async function findRelated() {
    if (!selectedIncident) return;
    setIsLoadingRelated(true);
    setError('');
    try {
      const result = await apiRequest('/v1/incidents/' + selectedIncident.id + '/related?top_k=8');
      setRelated(result.items);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudieron buscar similares.');
    } finally {
      setIsLoadingRelated(false);
    }
  }

  async function reindex() {
    if (!selectedIncident) return;
    setError('');
    setActionMessage('');
    try {
      await apiRequest('/v1/incidents/' + selectedIncident.id + '/semantic-index', { method: 'POST' });
      setActionMessage('Embedding del incidente #' + selectedIncident.id + ' actualizado.');
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo recalcular el embedding.');
    }
  }

  return (
    <section className="adminPanel workspacePanel">
      <div className="sectionIntro">
        <div>
          <span className="eyebrow">Consulta operacional</span>
          <h2>Incidentes</h2>
          <p>Explora los registros y abre su ficha para consultar coincidencias semánticas.</p>
        </div>
        <button className="secondaryButton" type="button" onClick={onRefresh}>↻ Actualizar lista</button>
      </div>
      {actionMessage && <p className="statusMessage success">{actionMessage}</p>}
      {error && <p className="statusMessage error">{error}</p>}
      <div className="incidentWorkspace">
        <IncidentTable
          incidents={visibleIncidents}
          selectedId={selectedIncident?.id}
          isLoading={isLoading}
          onSelect={(incident) => {
            setSelectedIncident(incident);
            setRelated(null);
            setActionMessage('');
          }}
        />
        <IncidentDetail
          incident={selectedIncident}
          related={related}
          isLoadingRelated={isLoadingRelated}
          onFindRelated={findRelated}
          onReindex={reindex}
        />
      </div>
      <IncidentPagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalItems={incidents.length}
        pageStart={pageStartIndex + 1}
        pageEnd={Math.min(pageStartIndex + INCIDENTS_PAGE_SIZE, incidents.length)}
        onPageChange={setCurrentPage}
      />
    </section>
  );
}

function AnalyticsPanel({ incidents }) {
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState(null);
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([]);
  const [isSessionLoading, setIsSessionLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState('');
  const categories = Object.entries(
    countBy(incidents, (incident) => incident.ai_extracted_data?.categoria_preliminar),
  ).sort(([, countA], [, countB]) => countB - countA);
  const districts = Object.entries(
    countBy(incidents, (incident) => incident.ai_extracted_data?.distrito),
  ).sort(([, countA], [, countB]) => countB - countA);
  const staffReports = incidents.filter((incident) => incident.police_input).length;
  const limitedReliability = incidents.filter((incident) => incident.requires_human_review).length;

  useEffect(() => {
    let cancelled = false;
    async function loadSession() {
      setIsSessionLoading(true);
      try {
        const storedSessionId = sessionStorage.getItem(OPERATIONAL_SESSION_STORAGE_KEY);
        let session;
        if (storedSessionId) {
          try {
            session = await apiRequest(`/v1/operational/sessions/${storedSessionId}`);
          } catch {
            sessionStorage.removeItem(OPERATIONAL_SESSION_STORAGE_KEY);
          }
        }
        if (!session) {
          session = await apiRequest('/v1/operational/sessions', { method: 'POST' });
          sessionStorage.setItem(OPERATIONAL_SESSION_STORAGE_KEY, session.session_id);
        }
        if (!cancelled) {
          setSessionId(session.session_id);
          setMessages(session.messages ?? []);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : 'No se pudo iniciar el asistente.');
        }
      } finally {
        if (!cancelled) setIsSessionLoading(false);
      }
    }
    loadSession();
    return () => { cancelled = true; };
  }, []);

  async function runQuery(event) {
    event.preventDefault();
    if (!query.trim() || !sessionId) return;
    const submittedQuery = query.trim();
    setMessages((current) => [...current, { role: 'user', content: submittedQuery }]);
    setQuery('');
    setIsRunning(true);
    setError('');
    try {
      const result = await apiRequest(`/v1/operational/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: submittedQuery }),
      });
      setAnswer(result);
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo consultar al asistente.');
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="adminPanel workspacePanel">
      <div className="sectionIntro">
        <div>
          <span className="eyebrow">Lectura del territorio</span>
          <h2>Analítica operativa</h2>
          <p>Observa tendencias y pregunta por los datos usando el asistente operacional.</p>
        </div>
      </div>
      <div className="analyticsKpis">
        <StatCard label="Registros totales" value={incidents.length} />
        <StatCard label="Ingresados por personal" value={staffReports} />
        <StatCard label="Fiabilidad limitada" value={limitedReliability} />
      </div>
      <div className="analyticsGrid">
        <article className="insightCard">
          <h3>Distribución por distrito</h3>
          {districts.map(([district, count]) => (
            <div className="insightRow" key={district}>
              <span>{normalizeValue(district)}</span><strong>{count}</strong>
            </div>
          ))}
          {districts.length === 0 && <p className="adminEmpty">Sin datos.</p>}
        </article>
        <article className="insightCard">
          <h3>Categorías más frecuentes</h3>
          {categories.slice(0, 6).map(([category, count]) => (
            <div className="insightRow" key={category}>
              <span>{normalizeValue(category)}</span><strong>{count}</strong>
            </div>
          ))}
          {categories.length === 0 && <p className="adminEmpty">Sin datos.</p>}
        </article>
      </div>
      <div className="assistantSessionMeta">
        <span className={'statusDot ' + (sessionId ? 'ready' : '')} />
        {isSessionLoading
          ? 'Conectando con la sesión del asistente…'
          : sessionId
            ? 'Sesión persistente activa'
            : 'Sesión no disponible; reintenta la conexión'}
      </div>
      <form className="agentQueryBox" onSubmit={runQuery}>
        <label htmlFor="operational-query"><strong>Pregunta al asistente operacional</strong></label>
        <p className="queryHint">Puedes hacer varias preguntas; el asistente conserva el contexto y valida cada conteo contra SGCIU.</p>
        <ChatTranscript messages={messages} isLoading={isRunning} loadingLabel="Consultando incidentes" />
        <div className="queryRow">
          <input
            id="operational-query"
            type="text"
            placeholder="Ej. ¿Qué incidentes de ruido hubo en Llorente?"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button className="primaryButton" type="submit" disabled={isRunning || isSessionLoading || !sessionId || !query.trim()}>
            {isRunning ? 'Consultando...' : 'Consultar'}
          </button>
        </div>
      </form>
      {error && <p className="statusMessage error">{error}</p>}
      {answer && (
        <article className="agentAnswer">
          <div className="answerHeader">
            <h3>Verificación de la última respuesta</h3>
            <span>{answer.steps?.length || 0} pasos trazables · {answer.trace_id}</span>
          </div>
          {answer.incident_citations?.length > 0 && (
            <p className="citationLine">
              Incidentes consultados: {answer.incident_citations.map((id) => '#' + id).join(', ')}
            </p>
          )}
          {answer.incident_citations?.length === 0 && (
            <p className="citationLine">La respuesta no utilizó incidentes concretos como cita.</p>
          )}
        </article>
      )}
    </section>
  );
}

function PolicyAssistantPanel() {
  const [query, setQuery] = useState('');
  const [audience, setAudience] = useState('administrative');
  const [operationalContext, setOperationalContext] = useState('');
  const [messages, setMessages] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem('sgciu.policy.history') || '[]');
    } catch {
      return [];
    }
  });
  const [result, setResult] = useState(null);
  const [corpus, setCorpus] = useState(null);
  const [isQuerying, setIsQuerying] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const [error, setError] = useState('');

  async function loadCorpus() {
    try {
      setCorpus(await apiRequest('/v1/legal-rag/corpus'));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo consultar el corpus normativo.');
    }
  }

  useEffect(() => {
    loadCorpus();
  }, []);

  useEffect(() => {
    sessionStorage.setItem('sgciu.policy.history', JSON.stringify(messages.slice(-24)));
  }, [messages]);

  async function indexCorpus() {
    setIsIndexing(true);
    setError('');
    try {
      await apiRequest('/v1/legal-rag/corpus/index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: false }),
      });
      await loadCorpus();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo indexar el corpus.');
    } finally {
      setIsIndexing(false);
    }
  }

  async function askPolicy(event) {
    event.preventDefault();
    if (!query.trim()) return;
    const submittedQuery = query.trim();
    setMessages((current) => [...current, { role: 'user', content: submittedQuery }]);
    setQuery('');
    setIsQuerying(true);
    setError('');
    try {
      const response = await apiRequest('/v1/legal-rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: submittedQuery,
          audience,
          operational_context: operationalContext.trim() || null,
        }),
      });
      setMessages((current) => [...current, { role: 'assistant', content: response.answer }]);
      setResult(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo consultar la normativa.');
    } finally {
      setIsQuerying(false);
    }
  }

  return (
    <section className="adminPanel workspacePanel policyWorkspace">
      <div className="sectionIntro">
        <div>
          <span className="eyebrow">Normativa autorizada</span>
          <h2>Asistente de Políticas</h2>
          <p>Consulta procedimientos municipales respaldados por fuentes citables.</p>
        </div>
        <div className="corpusStatus">
          <span className={'statusDot ' + (corpus?.indexed_documents > 0 ? 'ready' : '')} />
          <span>{corpus?.indexed_documents > 0 ? corpus.indexed_documents + ' documentos indexados' : 'Corpus pendiente'}</span>
          <button className="ghostButton" type="button" onClick={indexCorpus} disabled={isIndexing}>
            {isIndexing ? 'Indexando...' : 'Actualizar corpus'}
          </button>
        </div>
      </div>
      <form className="policyQuery" onSubmit={askPolicy}>
        <label htmlFor="policy-query"><strong>¿Qué necesitas consultar?</strong></label>
        <div className="policyContextGrid">
          <label className="field" htmlFor="policy-audience">
            <span>Perfil que consulta</span>
            <select id="policy-audience" value={audience} onChange={(event) => setAudience(event.target.value)}>
              <option value="administrative">Personal administrativo</option>
              <option value="police">Personal policial</option>
            </select>
          </label>
          <label className="field" htmlFor="policy-context">
            <span>Situación del incidente <small>(opcional)</small></span>
            <input
              id="policy-context"
              type="text"
              placeholder="Ej. pelea en curso reportada en San Joaquín"
              value={operationalContext}
              onChange={(event) => setOperationalContext(event.target.value)}
            />
          </label>
        </div>
        <textarea
          id="policy-query"
          rows="3"
          placeholder="Ej. ¿Qué procedimiento aplica para una denuncia de ruido?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <ChatTranscript messages={messages} isLoading={isQuerying} loadingLabel="Interpretando la normativa para SGCIU" />
        <button className="primaryButton" type="submit" disabled={isQuerying || !query.trim()}>
          {isQuerying ? 'Revisando fuentes...' : 'Consultar normativa'}
        </button>
      </form>
      {error && <p className="statusMessage error">{error}</p>}
      {result && (
        <article className="policyAnswer">
          <div className="answerHeader">
            <h3>Respuesta fundamentada</h3>
            <span>{result.insufficient_evidence ? 'Evidencia insuficiente' : (result.citations?.length || 0) + ' fuentes'}</span>
          </div>
          {result.operational_guidance?.length > 0 && (
            <div className="operationalGuidance">
              <strong>Aplicación operativa:</strong>
              <ul>{result.operational_guidance.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {result.citations?.length > 0 && (
            <div className="citationCards">
              {result.citations.map((citation) => (
                <article key={citation.source_id}>
                  <strong>[{citation.source_id}] {citation.document_title}</strong>
                  <span>Página {citation.pdf_page} · {citation.source_category}</span>
                  <p>{citation.excerpt}</p>
                </article>
              ))}
            </div>
          )}
        </article>
      )}
    </section>
  );
}

function InternalIncidentForm({ onSaved }) {
  const [enteredByBadge, setEnteredByBadge] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [extractedData, setExtractedData] = useState(INITIAL_EXTRACTED_DATA);
  const [isAiComplete, setIsAiComplete] = useState(false);
  const [summaryText, setSummaryText] = useState('');
  const [truthConfirmation, setTruthConfirmation] = useState(false);
  const [dataUsageConsent, setDataUsageConsent] = useState(false);
  const [isStarting, setIsStarting] = useState(true);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  async function startSession() {
    setIsStarting(true);
    setError('');
    try {
      const data = await apiRequest('/v1/internal-intake/sessions', {
        method: 'POST',
      });
      setSessionId(data.session_id);
      setMessages([{ role: 'assistant', content: data.assistant_message }]);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'No se pudo iniciar el registro.');
    } finally {
      setIsStarting(false);
    }
  }

  useEffect(() => {
    startSession();
  }, []);

  const canSubmit = Boolean(
    sessionId &&
      enteredByBadge.trim() &&
      isAiComplete &&
      truthConfirmation &&
      dataUsageConsent &&
      !isSubmitting,
  );

  async function handleSendMessage(event) {
    event.preventDefault();
    const trimmedMessage = currentMessage.trim();
    if (!trimmedMessage || !sessionId || isChatLoading) {
      return;
    }

    setCurrentMessage('');
    setError('');
    setIsChatLoading(true);
    try {
      const data = await apiRequest(`/v1/internal-intake/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: trimmedMessage }),
      });
      setMessages(data.messages);
      setExtractedData(data.extracted_data);
      setIsAiComplete(Boolean(data.is_complete));
      setSummaryText(data.summary_text ?? '');
    } catch (chatError) {
      setError(chatError instanceof Error ? chatError.message : 'No se pudo analizar el mensaje.');
    } finally {
      setIsChatLoading(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setError('');
    setSuccessMessage('');
    setIsSubmitting(true);
    try {
      const saved = await apiRequest(`/v1/internal-intake/sessions/${sessionId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entered_by_badge: enteredByBadge.trim(),
          truth_confirmation: truthConfirmation,
          data_usage_consent: dataUsageConsent,
        }),
      });
      if (onSaved) {
        await onSaved(saved);
      }
      setSuccessMessage(`Incidente #${saved.id} guardado correctamente.`);
      setEnteredByBadge('');
      setMessages([]);
      setCurrentMessage('');
      setExtractedData(INITIAL_EXTRACTED_DATA);
      setIsAiComplete(false);
      setSummaryText('');
      setTruthConfirmation(false);
      setDataUsageConsent(false);
      await startSession();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'No se pudo guardar el incidente.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="internalIncidentForm" onSubmit={handleSubmit}>
      <label className="field internalBadgeField" htmlFor="enteredByBadge">
        <span>Badge del funcionario que registra</span>
        <input
          id="enteredByBadge"
          type="text"
          autoComplete="off"
          placeholder="Ej. POL-042 o ADM-015"
          value={enteredByBadge}
          onChange={(event) => setEnteredByBadge(event.target.value)}
        />
        <small>Este dato se registra manualmente para identificar al funcionario responsable.</small>
      </label>

      <div className="chatPanel">
        <ChatTranscript
          messages={messages}
          isLoading={isStarting || isChatLoading}
          loadingLabel={isStarting ? 'Preparando la sesión' : 'Extrayendo y verificando la información'}
        />
        <div className="chatInputRow">
          <textarea
            aria-label="Mensaje para el asistente interno"
            placeholder="Describa la denuncia recibida..."
            value={currentMessage}
            disabled={!sessionId || isStarting || isChatLoading}
            onChange={(event) => setCurrentMessage(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') handleSendMessage(event);
            }}
          />
          <button type="button" disabled={!sessionId || isStarting || isChatLoading} onClick={handleSendMessage}>
            {isChatLoading ? 'Enviando...' : 'Enviar'}
          </button>
        </div>
      </div>

      <section className="internalSummary">
        <h3>Resumen extraído</h3>
        {isAiComplete ? (
          <ul>
            {buildDetailBullets(extractedData).map((item) => (
              <li key={`${item.label}-${item.value}`}><strong>{item.label}:</strong> {item.value}</li>
            ))}
          </ul>
        ) : (
          <p className="summaryPlaceholder">El resumen aparecerá cuando el asistente termine de recolectar la información.</p>
        )}
        {summaryText && <p className="internalSummaryText">{summaryText}</p>}
      </section>

      <div className="consentGroup">
        <label className="checkField">
          <input
            type="checkbox"
            checked={truthConfirmation}
            onChange={(event) => setTruthConfirmation(event.target.checked)}
          />
          <span>Confirmo que la información registrada corresponde a la denuncia recibida.</span>
        </label>
        <label className="checkField">
          <input
            type="checkbox"
            checked={dataUsageConsent}
            onChange={(event) => setDataUsageConsent(event.target.checked)}
          />
          <span>Confirmo el uso institucional de los datos para gestionar el incidente.</span>
        </label>
      </div>

      <button className="internalSubmitButton" type="submit" disabled={!canSubmit}>
        {isSubmitting ? 'Guardando...' : 'Guardar incidente interno'}
      </button>
      {!enteredByBadge.trim() && <p className="statusMessage warning">El badge del funcionario es obligatorio.</p>}
      {error && <p className="statusMessage error">{error}</p>}
      {successMessage && <p className="statusMessage success">{successMessage}</p>}
    </form>
  );
}

function AdminWorkspace({ user, onLogout }) {
  const [isMenuOpen, setIsMenuOpen] = useState(true);
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);
  const [activeItem, setActiveItem] = useState(
    window.location.pathname.includes('/registrar-incidente')
      ? 'Registrar incidente'
      : 'Inicio',
  );
  const [complaints, setComplaints] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [dateFilter, setDateFilter] = useState('');
  const [districtFilter, setDistrictFilter] = useState('Todos');
  const [incidentSearch, setIncidentSearch] = useState('');
  const [recurrentPatterns, setRecurrentPatterns] = useState([]);
  const [isPatternsLoading, setIsPatternsLoading] = useState(true);
  const [patternsError, setPatternsError] = useState('');
  const [candidateClusters, setCandidateClusters] = useState([]);
  const [isClustersLoading, setIsClustersLoading] = useState(true);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [recalculationMessage, setRecalculationMessage] = useState('');

  async function refreshComplaints() {
    setIsLoading(true);
    setLoadError('');
    try {
      setComplaints(await apiRequest('/complaints'));
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : 'Ocurrió un error inesperado al cargar los incidentes.',
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshRecurrentPatterns() {
    setIsPatternsLoading(true);
    setPatternsError('');
    try {
      setRecurrentPatterns(await apiRequest('/v1/incidents/clusters/recurrent'));
    } catch (error) {
      setPatternsError(
        error instanceof Error
          ? error.message
          : 'Ocurrió un error al cargar los patrones recurrentes.',
      );
    } finally {
      setIsPatternsLoading(false);
    }
  }

  async function refreshCandidateClusters() {
    setIsClustersLoading(true);
    try {
      setCandidateClusters(await apiRequest('/v1/incidents/clusters/candidates'));
    } catch (error) {
      setPatternsError(
        error instanceof Error
          ? error.message
          : 'Ocurrió un error al cargar los clusters candidatos.',
      );
    } finally {
      setIsClustersLoading(false);
    }
  }

  useEffect(() => {
    refreshComplaints();
    refreshRecurrentPatterns();
    refreshCandidateClusters();
  }, []);

  async function recalculateSemanticIndex() {
    setIsRecalculating(true);
    setRecalculationMessage('');
    setPatternsError('');
    try {
      const result = await apiRequest('/v1/incidents/clusters/recalculate', { method: 'POST' });
      setRecalculationMessage(
        result.embeddings_failed
          ? 'El cálculo terminó con algunos embeddings pendientes.'
          : result.embeddings_updated + ' embeddings y ' + result.clusters_rebuilt + ' clusters actualizados.',
      );
      await Promise.all([
        refreshComplaints(),
        refreshRecurrentPatterns(),
        refreshCandidateClusters(),
      ]);
    } catch (error) {
      setPatternsError(
        error instanceof Error ? error.message : 'No se pudo recalcular la agrupación semántica.',
      );
    } finally {
      setIsRecalculating(false);
    }
  }

  const filteredComplaints = useMemo(
    () =>
      complaints.filter((complaint) => {
        const complaintDate = toDateKey(new Date(complaint.created_at));
        const complaintDistrict = complaint.ai_extracted_data?.distrito;
        const matchesDate = !dateFilter || complaintDate === dateFilter;
        const matchesDistrict = districtFilter === 'Todos' || complaintDistrict === districtFilter;
        const matchesIncident = !incidentSearch || String(complaint.id).includes(incidentSearch);

        return matchesDate && matchesDistrict && matchesIncident;
      }),
    [complaints, dateFilter, districtFilter, incidentSearch],
  );

  const activeFilterCount = [dateFilter, districtFilter !== 'Todos' ? districtFilter : '', incidentSearch]
    .filter(Boolean).length;

  useEffect(() => {
    function closeFiltersOnEscape(event) {
      if (event.key === 'Escape') setIsFiltersOpen(false);
    }
    document.addEventListener('keydown', closeFiltersOnEscape);
    return () => document.removeEventListener('keydown', closeFiltersOnEscape);
  }, []);

  const todayReports = useMemo(() => {
    const today = toDateKey(new Date());
    return complaints.filter((complaint) => toDateKey(new Date(complaint.created_at)) === today)
      .length;
  }, [complaints]);

  const mostCommonCategory = useMemo(() => {
    const categories = Object.entries(
      countBy(complaints, (complaint) => complaint.ai_extracted_data?.categoria_preliminar),
    ).sort(([, countA], [, countB]) => countB - countA);

    return categories.length > 0 ? normalizeValue(categories[0][0]) : 'Sin datos';
  }, [complaints]);

  const lastReportHour = useMemo(() => {
    if (complaints.length === 0) {
      return 'Sin datos';
    }

    const latest = [...complaints].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];

    return new Intl.DateTimeFormat('es-CR', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(latest.created_at));
  }, [complaints]);

  return (
    <div className={`adminShell ${isMenuOpen ? 'isOpen' : 'isCollapsed'}`}>
      <button
        className="adminToggle"
        type="button"
        aria-label={isMenuOpen ? 'Ocultar menú administrativo' : 'Mostrar menú administrativo'}
        onClick={() => setIsMenuOpen((open) => !open)}
      >
        {isMenuOpen ? '‹' : '☰'}
      </button>
      <aside className="adminNav" aria-label="Navegación administrativa">
        <div className="adminBrand">
          <img src={logoFlores} alt="Logo Municipalidad de Flores" />
          {isMenuOpen && <strong>Municipalidad de Flores</strong>}
        </div>

        <nav className="adminNavList">
          {NAV_ITEMS.map((item) => (
            <button
              className={activeItem === item.label ? 'active' : ''}
              key={item.label}
              type="button"
              onClick={() => setActiveItem(item.label)}
            >
              <span aria-hidden="true">{item.icon}</span>
              <strong>{item.label}</strong>
            </button>
          ))}
        </nav>
      </aside>

      <main className="adminContent">
        <header className="adminTop">
          <div className="adminTopHeading">
            <span className="eyebrow">Centro operativo municipal</span>
            <h1>Sistema de Gestión y Clasificación de Incidentes Urbanos</h1>
            <p>Convierte cada denuncia en contexto útil para actuar mejor en Flores.</p>
          </div>
          <div className="adminTopActions">
            <button
              className={`filterLauncher ${activeFilterCount > 0 ? 'hasActiveFilters' : ''}`}
              type="button"
              aria-expanded={isFiltersOpen}
              aria-controls="incident-filter-fields"
              onClick={() => setIsFiltersOpen(true)}
            >
              <span className="filterLauncherIcon" aria-hidden="true">⌕</span>
              <strong>Filtros</strong>
            </button>
            <div className="adminSessionActions">
              <span className="adminUserBadge">
                {user.role === 'police' ? 'Policía' : 'Administrativo'} · {user.username}
              </span>
              <button className="ghostButton" type="button" onClick={onLogout}>Cerrar sesión</button>
            </div>
          </div>
        </header>

        {activeItem === 'Agrupación recurrente' && (
          <section className="adminPanel recurrentPatternsPanel">
            <div className="adminPanelHeader">
              <div>
                <h2>Agrupación recurrente</h2>
                <p>Patrones proactivos detectados automáticamente en los últimos 30 días.</p>
              </div>
              <div className="panelActions">
                <button className="secondaryButton" type="button" onClick={refreshRecurrentPatterns}>
                  ↻ Actualizar
                </button>
                <button
                  className="primaryButton"
                  type="button"
                  onClick={recalculateSemanticIndex}
                  disabled={isRecalculating}
                >
                  {isRecalculating ? 'Calculando...' : 'Recalcular embeddings y clusters'}
                </button>
              </div>
            </div>
            {recalculationMessage && <p className="statusMessage success">{recalculationMessage}</p>}
            <RecurrentPatternsPanel
              patterns={recurrentPatterns}
              isLoading={isPatternsLoading}
              error={patternsError}
            />
            <div className="subPanel">
              <div className="subPanelHeader">
                <div>
                  <span className="eyebrow">Vista técnica</span>
                  <h3>Clusters candidatos</h3>
                  <p>Consulta las agrupaciones calculadas antes de que formen un patrón recurrente.</p>
                </div>
              </div>
              <CandidateClustersPanel
                clusters={candidateClusters}
                isLoading={isClustersLoading}
                error={patternsError}
              />
            </div>
          </section>
        )}

        {activeItem === 'Registrar incidente' && (
          <section className="adminPanel internalIncidentPanel">
            <div className="adminPanelHeader">
              <div>
                <h2>Registrar incidente interno</h2>
                <p>Utilice este formulario para denuncias recibidas presencialmente o por vía verbal.</p>
              </div>
              <span>Registro administrativo</span>
            </div>
            <InternalIncidentForm onSaved={refreshComplaints} />
          </section>
        )}

        {activeItem === 'Incidentes' && (
          <IncidentsPanel
            incidents={filteredComplaints}
            onRefresh={refreshComplaints}
            isLoading={isLoading}
          />
        )}

        {activeItem === 'Analítica' && <AnalyticsPanel incidents={filteredComplaints} />}

        {activeItem === 'Asistente de Políticas' && <PolicyAssistantPanel />}

        {loadError && <p className="statusMessage error">{loadError}</p>}

        {activeItem === 'Inicio' && (
          <>
        <section className="adminStats" aria-label="Indicadores principales">
          <StatCard label="Número reportes de hoy" value={isLoading ? '...' : todayReports} />
          <StatCard label="Categoría más común" value={isLoading ? '...' : mostCommonCategory} />
          <StatCard label="Hora de último reporte" value={isLoading ? '...' : lastReportHour} />
        </section>

        <section className="adminCharts">
          <article className="adminPanel">
            <h2>Incidentes reportados en los últimos 7 días</h2>
            <WeeklyReportsChart complaints={complaints} />
          </article>

          <article className="adminPanel">
            <h2>Incidentes por categorías últimos 7 días</h2>
            <CategoryChart complaints={complaints} />
          </article>
        </section>

        <section className="adminPanel">
          <div className="adminPanelHeader">
            <h2>Incidentes registrados</h2>
            <span>{filteredComplaints.length} resultados</span>
          </div>

          <div className="adminTableWrap">
            <table className="adminTable">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Fecha de reporte</th>
                  <th>Distrito</th>
                  <th>Categoría</th>
                  <th>Relación</th>
                  <th>Dirección</th>
                  <th>Origen</th>
                </tr>
              </thead>
              <tbody>
                {filteredComplaints.map((complaint) => (
                  <tr key={complaint.id}>
                    <td>
                      <span className="idBadge">#{complaint.id}</span>
                    </td>
                    <td>{formatDateTime(complaint.created_at)}</td>
                    <td>
                      <span className="tableBadge district">
                        {normalizeValue(complaint.ai_extracted_data?.distrito)}
                      </span>
                    </td>
                    <td>
                      <span className="tableBadge category">
                        {normalizeValue(complaint.ai_extracted_data?.categoria_preliminar)}
                      </span>
                    </td>
                    <td>{normalizeValue(complaint.ai_extracted_data?.relacion_incidente)}</td>
                    <td>{normalizeValue(complaint.ai_extracted_data?.direccion_exacta)}</td>
                    <td>
                      {complaint.police_input
                        ? `Personal · ${complaint.entered_by_badge || 'Badge no disponible'}`
                        : 'Ciudadano'}
                    </td>
                  </tr>
                ))}

                {!isLoading && filteredComplaints.length === 0 && (
                  <tr>
                    <td colSpan="7" className="adminEmptyTable">
                      No hay incidentes que coincidan con los filtros.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
          </>
        )}
      </main>
      <div
        className={`filterDrawerBackdrop ${isFiltersOpen ? 'isVisible' : ''}`}
        aria-hidden={!isFiltersOpen}
        onClick={() => setIsFiltersOpen(false)}
      />
      <IncidentFilters
        dateFilter={dateFilter}
        districtFilter={districtFilter}
        incidentSearch={incidentSearch}
        setDateFilter={setDateFilter}
        setDistrictFilter={setDistrictFilter}
        setIncidentSearch={setIncidentSearch}
        isOpen={isFiltersOpen}
        onClose={() => setIsFiltersOpen(false)}
      />
    </div>
  );
}

function AdminLogin({ onAuthenticated }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(event) {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setIsSubmitting(true);
    setError('');
    try {
      const session = await apiRequest('/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      sessionStorage.setItem(ADMIN_AUTH_STORAGE_KEY, JSON.stringify(session));
      onAuthenticated(session.user);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'No se pudo iniciar sesión.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="authShell">
      <section className="authCard" aria-labelledby="admin-login-title">
        <img src={logoFlores} alt="Logo Municipalidad de Flores" />
        <span className="eyebrow">Acceso institucional</span>
        <h1 id="admin-login-title">SGCIU</h1>
        <p>Inicie sesión para consultar y gestionar la información operativa.</p>
        <form onSubmit={handleSubmit}>
          <label className="field" htmlFor="admin-username">
            <span>Usuario</span>
            <input
              id="admin-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label className="field" htmlFor="admin-password">
            <span>Contraseña</span>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <p className="statusMessage error" role="alert">{error}</p>}
          <button className="primaryButton" type="submit" disabled={isSubmitting || !username.trim() || !password}>
            {isSubmitting ? 'Ingresando…' : 'Iniciar sesión'}
          </button>
        </form>
      </section>
    </main>
  );
}

function AdminDashboard() {
  const [user, setUser] = useState(null);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function validateSession() {
      try {
        const storedAuth = JSON.parse(sessionStorage.getItem(ADMIN_AUTH_STORAGE_KEY) || 'null');
        if (!storedAuth?.access_token) return;
        const currentUser = await apiRequest('/v1/auth/me');
        if (!cancelled) setUser(currentUser);
      } catch {
        sessionStorage.removeItem(ADMIN_AUTH_STORAGE_KEY);
      } finally {
        if (!cancelled) setIsChecking(false);
      }
    }
    validateSession();
    function handleExpiredSession() {
      setUser(null);
    }
    window.addEventListener('sgciu-auth-expired', handleExpiredSession);
    return () => {
      cancelled = true;
      window.removeEventListener('sgciu-auth-expired', handleExpiredSession);
    };
  }, []);

  async function logout() {
    try {
      await apiRequest('/v1/auth/logout', { method: 'POST' });
    } finally {
      sessionStorage.removeItem(ADMIN_AUTH_STORAGE_KEY);
      setUser(null);
    }
  }

  if (isChecking) {
    return <main className="authShell"><p className="authLoading">Validando sesión…</p></main>;
  }
  if (!user) {
    return <AdminLogin onAuthenticated={setUser} />;
  }
  return <AdminWorkspace user={user} onLogout={logout} />;
}

function CitizenComplaintForm() {
  const [registrationMode, setRegistrationMode] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [contactData, setContactData] = useState({
    name: '',
    email: '',
    phone: '',
  });
  const [messages, setMessages] = useState([]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [extractedData, setExtractedData] = useState(INITIAL_EXTRACTED_DATA);
  const [isAiComplete, setIsAiComplete] = useState(false);
  const [summaryText, setSummaryText] = useState('');
  const [truthConfirmation, setTruthConfirmation] = useState(false);
  const [dataUsageConsent, setDataUsageConsent] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [chatError, setChatError] = useState('');
  const [submissionError, setSubmissionError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [savedComplaint, setSavedComplaint] = useState(null);

  const canSubmit = useMemo(
    () =>
      Boolean(extractedData.descripcion_detallada) &&
      Boolean(sessionId) &&
      isAiComplete &&
      truthConfirmation &&
      dataUsageConsent &&
      !isSubmitting,
    [
      dataUsageConsent,
      extractedData.descripcion_detallada,
      isAiComplete,
      isSubmitting,
      sessionId,
      truthConfirmation,
    ],
  );

  function hydrateSession(data) {
    setSessionId(data.session_id);
    setRegistrationMode(data.registration_mode ?? 'complete');
    setMessages(data.messages ?? []);
    setExtractedData(data.extracted_data ?? INITIAL_EXTRACTED_DATA);
    setIsAiComplete(Boolean(data.is_complete));
    setSummaryText(data.summary_text ?? '');
  }

  useEffect(() => {
    let cancelled = false;
    async function restoreSession() {
      const storedSessionId = sessionStorage.getItem(CITIZEN_SESSION_STORAGE_KEY);
      if (!storedSessionId) return;
      try {
        const response = await fetch(`${API_BASE_URL}/v1/intake/sessions/${storedSessionId}`);
        if (!response.ok) throw new Error('La sesión ya no está disponible.');
        const data = await response.json();
        if (!cancelled) hydrateSession(data);
      } catch {
        sessionStorage.removeItem(CITIZEN_SESSION_STORAGE_KEY);
      }
    }
    restoreSession();
    return () => { cancelled = true; };
  }, []);

  async function startSession(mode) {
    if (!mode) {
      setRegistrationMode('');
      setSessionId('');
      setMessages([]);
      return;
    }
    setRegistrationMode(mode);
    setIsStarting(true);
    setChatError('');
    setSubmissionError('');
    try {
      const response = await fetch(`${API_BASE_URL}/v1/intake/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ registration_mode: mode }),
      });
      if (!response.ok) throw new Error((await response.text()) || 'No se pudo iniciar la sesión.');
      const data = await response.json();
      hydrateSession({
        ...data,
        messages: [{ role: 'assistant', content: data.assistant_message }],
        extracted_data: INITIAL_EXTRACTED_DATA,
        is_complete: false,
        summary_text: '',
      });
      sessionStorage.setItem(CITIZEN_SESSION_STORAGE_KEY, data.session_id);
    } catch (startError) {
      setSessionId('');
      setMessages([]);
      setRegistrationMode('');
      setChatError(startError instanceof Error ? startError.message : 'No se pudo iniciar la sesión.');
    } finally {
      setIsStarting(false);
    }
  }

  function handleContactChange(event) {
    const { name, value } = event.target;
    setContactData((current) => ({
      ...current,
      [name]: value,
    }));
  }

  async function handleSendMessage(event) {
    event.preventDefault();

    const trimmedMessage = currentMessage.trim();
    if (!trimmedMessage || !sessionId || isChatLoading || isStarting) {
      return;
    }

    const nextMessages = [...messages, { role: 'user', content: trimmedMessage }];
    setMessages(nextMessages);
    setCurrentMessage('');
    setChatError('');
    setIsChatLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/v1/intake/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content: trimmedMessage }),
      });

      if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(errorBody || 'No se pudo contactar al asistente IA.');
      }

      const aiResponse = await response.json();
      setMessages(aiResponse.messages ?? nextMessages);
      setExtractedData(aiResponse.extracted_data ?? extractedData);
      setIsAiComplete(Boolean(aiResponse.is_complete));
      setSummaryText(aiResponse.summary_text ?? '');
    } catch (error) {
      setChatError(
        error instanceof Error
          ? error.message
          : 'Ocurrió un error inesperado con el asistente IA.',
      );
    } finally {
      setIsChatLoading(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!sessionId) {
      setSubmissionError('Seleccione una modalidad e inicie la conversación antes de enviar.');
      return;
    }
    setSubmissionError('');
    setSuccessMessage('');
    setSavedComplaint(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE_URL}/v1/intake/sessions/${sessionId}/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: registrationMode === 'anonymous' ? null : (contactData.name || null),
          email: registrationMode === 'anonymous' ? null : (contactData.email || null),
          phone: registrationMode === 'anonymous' ? null : (contactData.phone || null),
          truth_confirmation: truthConfirmation,
          data_usage_consent: dataUsageConsent,
        }),
      });

      if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(errorBody || 'No se pudo guardar la denuncia.');
      }

      const saved = await response.json();
      setSavedComplaint(saved);
      setSuccessMessage('Denuncia guardada correctamente en la base de datos.');
      sessionStorage.removeItem(CITIZEN_SESSION_STORAGE_KEY);
      setRegistrationMode('');
      setSessionId('');
      setContactData({ name: '', email: '', phone: '' });
      setMessages([]);
      setCurrentMessage('');
      setExtractedData(INITIAL_EXTRACTED_DATA);
      setIsAiComplete(false);
      setSummaryText('');
      setTruthConfirmation(false);
      setDataUsageConsent(false);
    } catch (error) {
      setSubmissionError(
        error instanceof Error
          ? error.message
          : 'Ocurrió un error inesperado al guardar la denuncia.',
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="appShell">
      <section className="intro">
        <img
          className="municipalityLogo"
          src={logoFlores}
          alt="Logo Municipalidad de Flores"
        />
        <p className="eyebrow">Sistema de Gestión y Clasificación de Incidentes Urbanos</p>
        <h1>Formulario Denuncia Ciudadana</h1>
      </section>
      <p className="citizenEmergencyNotice">
        SGCIU no sustituye al 9-1-1. Si el incidente ocurre ahora, existe peligro o hay personas heridas, llame inmediatamente al 9-1-1.
      </p>

      <form className="formPanel" onSubmit={handleSubmit}>
        <section className="formSection">
          <div className="sectionHeader">
            <span>1</span>
            <div>
              <h2>¿Cómo desea registrar el incidente?</h2>
              <p>Puede identificarse o enviar la denuncia de forma anónima.</p>
            </div>
          </div>

          <label className="field modeField" htmlFor="registrationMode">
            <span>Modalidad de registro</span>
            <select
              id="registrationMode"
              value={registrationMode}
              onChange={(event) => startSession(event.target.value)}
              disabled={isStarting || isChatLoading}
            >
              <option value="">Seleccione una opción</option>
              <option value="complete">Registro con datos de contacto</option>
              <option value="anonymous">Registro anónimo</option>
            </select>
          </label>

          {registrationMode === 'anonymous' && (
            <p className="anonymousNotice">
              No solicitaremos nombre, correo ni teléfono. La información del incidente sí se conservará para su gestión municipal.
            </p>
          )}

          {registrationMode === 'complete' && <div className="fieldGrid">
            <label className="field" htmlFor="name">
              <span>Nombre completo <small>(opcional)</small></span>
              <input
                id="name"
                name="name"
                type="text"
                placeholder="Ej. Esmeralda Delgado"
                value={contactData.name}
                onChange={handleContactChange}
              />
            </label>

            <label className="field" htmlFor="email">
              <span>Correo electrónico <small>(opcional)</small></span>
              <input
                id="email"
                name="email"
                type="email"
                placeholder="nombre@dominio.com"
                value={contactData.email}
                onChange={handleContactChange}
              />
            </label>

            <label className="field" htmlFor="phone">
              <span>Número de teléfono <small>(opcional)</small></span>
              <input
                id="phone"
                name="phone"
                type="tel"
                placeholder="Ej. 8888-8888"
                value={contactData.phone}
                onChange={handleContactChange}
              />
            </label>
          </div>}
        </section>

        {registrationMode && <section className="formSection">
          <div className="sectionHeader">
            <span>2</span>
            <div>
              <h2>Asistente Inteligente</h2>
              <p>Escriba una descripción inicial lo más completa posible.</p>
            </div>
          </div>

          <ul className="guidanceList">
            <li>Qué ocurrió y qué comportamiento observó.</li>
            <li>Dónde ocurrió: distrito, dirección exacta o punto de referencia.</li>
            <li>Cuándo ocurrió: fecha y hora aproximada.</li>
            <li>Su relación con el incidente, si no queda clara por la descripción.</li>
            <li>Personas, vehículos u objetos relacionados, si aplica.</li>
            <li>Puede corregir al asistente si detecta algún dato incorrecto.</li>
          </ul>

          <div className="chatPanel">
            <ChatTranscript
              messages={messages}
              isLoading={isStarting || isChatLoading}
              loadingLabel={isStarting ? 'Preparando la sesión' : 'Extrayendo y verificando la información'}
            />

            <div className="chatInputRow">
              <textarea
                aria-label="Mensaje para el asistente IA"
                placeholder={isStarting ? 'Preparando el asistente…' : 'Escriba aquí…'}
                value={currentMessage}
                disabled={!sessionId || isStarting || isChatLoading}
                onChange={(event) => setCurrentMessage(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') handleSendMessage(event);
                }}
              />
              <button type="button" disabled={!sessionId || isStarting || isChatLoading} onClick={handleSendMessage}>
                {isChatLoading ? 'Procesando…' : 'Enviar'}
              </button>
            </div>

            {chatError && (
              <p className="statusMessage error" aria-live="polite">
                {chatError}
              </p>
            )}
          </div>
        </section>}

        <section className="formSection">
          <div className="sectionHeader">
            <span>3</span>
            <div>
              <h2>Resumen extraído</h2>
              <p>Revise la información recolectada antes de enviar la denuncia.</p>
            </div>
          </div>

          {isAiComplete ? (
            <div className="finalSummary">
              <ul>
                {buildDetailBullets(extractedData).map((item) => (
                  <li key={`${item.label ?? 'detalle'}-${item.value}`}>
                    {item.label ? <strong>{item.label}:</strong> : null} {item.value}
                  </li>
                ))}
              </ul>
              {summaryText && <p>{summaryText}</p>}
            </div>
          ) : (
            <p className="summaryPlaceholder">
              El resumen aparecerá cuando el asistente termine de recolectar la información.
            </p>
          )}
        </section>

        <section className="formSection">
          <div className="sectionHeader">
            <span>4</span>
            <div>
              <h2>Consentimiento sobre información y veracidad</h2>
              <p>Estas confirmaciones son obligatorias para enviar la denuncia.</p>
            </div>
          </div>

          <div className="consentGroup">
            <label className="checkField">
              <input
                type="checkbox"
                checked={truthConfirmation}
                onChange={(event) => setTruthConfirmation(event.target.checked)}
              />
              <span>Confirmo que la información proporcionada es veraz según mi conocimiento.</span>
            </label>

            <label className="checkField">
              <input
                type="checkbox"
                checked={dataUsageConsent}
                onChange={(event) => setDataUsageConsent(event.target.checked)}
              />
              <span>Acepto el uso institucional de los datos para la gestión de la denuncia.</span>
            </label>
          </div>
        </section>

        <div className="actions">
          <button type="submit" disabled={!canSubmit}>
            {isSubmitting ? 'Guardando...' : 'Guardar denuncia'}
          </button>
        </div>

        {!registrationMode && (
          <p className="statusMessage warning">
            Seleccione una modalidad de registro para iniciar la conversación.
          </p>
        )}

        {registrationMode && !extractedData.descripcion_detallada && (
          <p className="statusMessage warning">
            La descripción detallada es obligatoria. Converse con el asistente para completarla.
          </p>
        )}

        {extractedData.descripcion_detallada && !isAiComplete && (
          <p className="statusMessage warning">
            Termine la interacción con el asistente antes de guardar la denuncia.
          </p>
        )}

        {submissionError && (
          <p className="statusMessage error" aria-live="polite">
            {submissionError}
          </p>
        )}

        {successMessage && (
          <p className="statusMessage success" aria-live="polite">
            {successMessage}
          </p>
        )}
      </form>

      {savedComplaint && (
        <section className="resultPanel" aria-live="polite">
          <h2>Última denuncia guardada</h2>
          <pre>{JSON.stringify(savedComplaint, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}

export default function App() {
  return window.location.pathname.startsWith(ADMIN_ROUTE) ? (
    <AdminDashboard />
  ) : (
    <CitizenComplaintForm />
  );
}
