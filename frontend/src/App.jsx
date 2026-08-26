import { useEffect, useMemo, useState } from 'react';
import logoFlores from '../branding/logoFlores.png';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const ADMIN_ROUTE = '/admin';
const NAV_ITEMS = [
  { label: 'Inicio', icon: '⌂' },
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

const INITIAL_AI_MESSAGE = {
  role: 'assistant',
  content:
    'Describa la denuncia cuando esté listo. Le haré preguntas solo si falta algún dato importante. Si detecto información incorrecta, puede indicármelo para corregirla.',
};

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

function mergeExtractedData(currentData, nextData) {
  return Object.fromEntries(
    Object.keys(INITIAL_EXTRACTED_DATA).map((key) => [
      key,
      nextData?.[key] ?? currentData[key] ?? null,
    ]),
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

function AdminDashboard() {
  const [isMenuOpen, setIsMenuOpen] = useState(true);
  const [activeItem, setActiveItem] = useState('Inicio');
  const [complaints, setComplaints] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [dateFilter, setDateFilter] = useState('');
  const [districtFilter, setDistrictFilter] = useState('Todos');
  const [incidentSearch, setIncidentSearch] = useState('');
  const [recurrentPatterns, setRecurrentPatterns] = useState([]);
  const [isPatternsLoading, setIsPatternsLoading] = useState(true);
  const [patternsError, setPatternsError] = useState('');

  useEffect(() => {
    async function loadComplaints() {
      setIsLoading(true);
      setLoadError('');

      try {
        const response = await fetch(`${API_BASE_URL}/complaints`);
        if (!response.ok) {
          throw new Error('No se pudieron cargar los incidentes.');
        }

        setComplaints(await response.json());
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

    loadComplaints();
  }, []);

  useEffect(() => {
    async function loadRecurrentPatterns() {
      setIsPatternsLoading(true);
      setPatternsError('');
      try {
        const response = await fetch(`${API_BASE_URL}/v1/incidents/clusters/recurrent`);
        if (!response.ok) {
          throw new Error('No se pudieron cargar los patrones recurrentes.');
        }
        setRecurrentPatterns(await response.json());
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

    loadRecurrentPatterns();
  }, []);

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
      <aside className="adminNav" aria-label="Navegación administrativa">
        <div className="adminBrand">
          <img src={logoFlores} alt="Logo Municipalidad de Flores" />
          {isMenuOpen && <strong>Municipalidad de Flores</strong>}
        </div>

        <button
          className="adminToggle"
          type="button"
          aria-label={isMenuOpen ? 'Ocultar menú administrativo' : 'Mostrar menú administrativo'}
          onClick={() => setIsMenuOpen((open) => !open)}
        >
          {isMenuOpen ? '‹' : '☰'}
        </button>

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
          <h1>Sistema de Gestión y Clasificación de Incidentes Urbanos</h1>
          <div className="adminFilters">
            <label>
              <span>Fecha</span>
              <input
                type="date"
                value={dateFilter}
                onChange={(event) => setDateFilter(event.target.value)}
              />
            </label>

            <label>
              <span>Distrito</span>
              <select
                value={districtFilter}
                onChange={(event) => setDistrictFilter(event.target.value)}
              >
                {DISTRICTS.map((district) => (
                  <option key={district} value={district}>
                    {district}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>ID incidente</span>
              <input
                type="search"
                placeholder="Ej. 24"
                value={incidentSearch}
                onChange={(event) => setIncidentSearch(event.target.value)}
              />
            </label>
          </div>
        </header>

        {activeItem === 'Agrupación recurrente' && (
          <section className="adminPanel recurrentPatternsPanel">
            <div className="adminPanelHeader">
              <div>
                <h2>Agrupación recurrente</h2>
                <p>Patrones proactivos detectados automáticamente en los últimos 30 días.</p>
              </div>
              <span>Sin confirmación manual</span>
            </div>
            <RecurrentPatternsPanel
              patterns={recurrentPatterns}
              isLoading={isPatternsLoading}
              error={patternsError}
            />
          </section>
        )}

        {activeItem !== 'Inicio' && activeItem !== 'Agrupación recurrente' && (
          <p className="adminNotice">
            {activeItem} ya está disponible en el menú. La pantalla individual se implementará después.
          </p>
        )}

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
                  </tr>
                ))}

                {!isLoading && filteredComplaints.length === 0 && (
                  <tr>
                    <td colSpan="6" className="adminEmptyTable">
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
    </div>
  );
}

function CitizenComplaintForm() {
  const [contactData, setContactData] = useState({
    name: '',
    email: '',
    phone: '',
  });
  const [messages, setMessages] = useState([INITIAL_AI_MESSAGE]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [extractedData, setExtractedData] = useState(INITIAL_EXTRACTED_DATA);
  const [isAiComplete, setIsAiComplete] = useState(false);
  const [summaryText, setSummaryText] = useState('');
  const [truthConfirmation, setTruthConfirmation] = useState(false);
  const [dataUsageConsent, setDataUsageConsent] = useState(false);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [chatError, setChatError] = useState('');
  const [submissionError, setSubmissionError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [savedComplaint, setSavedComplaint] = useState(null);

  const canSubmit = useMemo(
    () =>
      Boolean(extractedData.descripcion_detallada) &&
      isAiComplete &&
      truthConfirmation &&
      dataUsageConsent &&
      !isSubmitting,
    [
      dataUsageConsent,
      extractedData.descripcion_detallada,
      isAiComplete,
      isSubmitting,
      truthConfirmation,
    ],
  );

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
    if (!trimmedMessage || isChatLoading) {
      return;
    }

    const nextMessages = [...messages, { role: 'user', content: trimmedMessage }];
    setMessages(nextMessages);
    setCurrentMessage('');
    setChatError('');
    setIsChatLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/ai/intake/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: nextMessages.filter((message) => message.role !== 'system'),
          current_extracted_data: extractedData,
        }),
      });

      if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(errorBody || 'No se pudo contactar al asistente IA.');
      }

      const aiResponse = await response.json();
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: aiResponse.assistant_message },
      ]);
      setExtractedData((currentData) =>
        mergeExtractedData(currentData, aiResponse.extracted_data),
      );
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
    setSubmissionError('');
    setSuccessMessage('');
    setSavedComplaint(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE_URL}/complaints`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: contactData.name || null,
          email: contactData.email || null,
          phone: contactData.phone || null,
          ai_extracted_data: extractedData,
          ai_summary_text: summaryText || null,
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
      setContactData({ name: '', email: '', phone: '' });
      setMessages([INITIAL_AI_MESSAGE]);
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

      <form className="formPanel" onSubmit={handleSubmit}>
        <section className="formSection">
          <div className="sectionHeader">
            <span>1</span>
            <div>
              <h2>Información General - Usuario</h2>
              <p>Datos opcionales</p>
            </div>
          </div>

          <div className="fieldGrid">
            <label className="field" htmlFor="name">
              <span>Nombre completo</span>
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
              <span>Correo electrónico</span>
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
              <span>Número de teléfono</span>
              <input
                id="phone"
                name="phone"
                type="tel"
                placeholder="Ej. 8888-8888"
                value={contactData.phone}
                onChange={handleContactChange}
              />
            </label>
          </div>
        </section>

        <section className="formSection">
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

          <div className="chatPanel" aria-live="polite">
            <div className="chatMessages">
              {messages.map((message, index) => (
                <div className={`chatBubble ${message.role}`} key={`${message.role}-${index}`}>
                  <p>{message.content}</p>
                </div>
              ))}
              {isChatLoading && (
                <div className="chatBubble assistant">
                  <p>Analizando la información...</p>
                </div>
              )}
            </div>

            <div className="chatInputRow">
              <textarea
                aria-label="Mensaje para el asistente IA"
                placeholder="Escriba aquí..."
                value={currentMessage}
                onChange={(event) => setCurrentMessage(event.target.value)}
              />
              <button type="button" disabled={isChatLoading} onClick={handleSendMessage}>
                {isChatLoading ? 'Enviando...' : 'Enviar'}
              </button>
            </div>

            {chatError && (
              <p className="statusMessage error" aria-live="polite">
                {chatError}
              </p>
            )}
          </div>
        </section>

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

        {!extractedData.descripcion_detallada && (
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
