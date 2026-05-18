import { useMemo, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

const INITIAL_EXTRACTED_DATA = {
  descripcion_detallada: null,
  relacion_incidente: null,
  categoria_preliminar: null,
  distrito: null,
  direccion_exacta: null,
  tipo_lugar: null,
  fecha_hora_aproximada: null,
  es_recurrente: null,
};

const SUMMARY_LABELS = {
  descripcion_detallada: 'Descripción detallada',
  relacion_incidente: 'Relación con el incidente',
  categoria_preliminar: 'Categoría preliminar',
  distrito: 'Distrito',
  direccion_exacta: 'Dirección exacta',
  tipo_lugar: 'Tipo de lugar',
  fecha_hora_aproximada: 'Fecha y hora aproximada',
  es_recurrente: '¿Es recurrente?',
};

const INITIAL_AI_MESSAGE = {
  role: 'assistant',
  content:
    'Para iniciar, describa la denuncia con el mayor detalle posible. Incluya qué ocurrió, dónde ocurrió, cuándo ocurrió y quiénes estuvieron involucrados si lo sabe.',
};

function normalizeValue(value) {
  if (value === null || value === undefined || value === '') {
    return 'Pendiente';
  }

  return String(value).replaceAll('_', ' ');
}

function SummaryList({ extractedData }) {
  return (
    <dl className="summaryGrid">
      {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
        <div className="summaryItem" key={key}>
          <dt>{label}</dt>
          <dd className={!extractedData[key] ? 'pendingValue' : undefined}>
            {normalizeValue(extractedData[key])}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function App() {
  const [contactData, setContactData] = useState({
    name: '',
    email: '',
    phone: '',
  });
  const [messages, setMessages] = useState([INITIAL_AI_MESSAGE]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [extractedData, setExtractedData] = useState(INITIAL_EXTRACTED_DATA);
  const [missingFields, setMissingFields] = useState(Object.keys(INITIAL_EXTRACTED_DATA));
  const [isAiComplete, setIsAiComplete] = useState(false);
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
      truthConfirmation &&
      dataUsageConsent &&
      !isSubmitting,
    [dataUsageConsent, extractedData.descripcion_detallada, isSubmitting, truthConfirmation],
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
      setExtractedData(aiResponse.extracted_data ?? INITIAL_EXTRACTED_DATA);
      setMissingFields(aiResponse.missing_fields ?? []);
      setIsAiComplete(Boolean(aiResponse.is_complete));
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
      setMissingFields(Object.keys(INITIAL_EXTRACTED_DATA));
      setIsAiComplete(false);
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
        <p className="eyebrow">SGCIU</p>
        <h1>Formulario de denuncia ciudadana</h1>
        <p>
          Complete la información general, converse con el asistente para estructurar la
          denuncia y confirme la veracidad de los datos antes de enviarla.
        </p>
      </section>

      <form className="formPanel" onSubmit={handleSubmit}>
        <section className="formSection">
          <div className="sectionHeader">
            <span>01</span>
            <div>
              <h2>Información General</h2>
              <p>Estos datos son opcionales.</p>
            </div>
          </div>

          <div className="fieldGrid">
            <label className="field" htmlFor="name">
              <span>Nombre completo</span>
              <input
                id="name"
                name="name"
                type="text"
                placeholder="Ej. Ana Martínez"
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
            <span>02</span>
            <div>
              <h2>Asistente IA</h2>
              <p>El asistente hará preguntas para completar la descripción de la denuncia.</p>
            </div>
          </div>

          <div className="chatPanel" aria-live="polite">
            <div className="chatMessages">
              {messages.map((message, index) => (
                <div className={`chatBubble ${message.role}`} key={`${message.role}-${index}`}>
                  <strong>{message.role === 'assistant' ? 'Asistente' : 'Usuario'}</strong>
                  <p>{message.content}</p>
                </div>
              ))}
              {isChatLoading && (
                <div className="chatBubble assistant">
                  <strong>Asistente</strong>
                  <p>Analizando la información...</p>
                </div>
              )}
            </div>

            <div className="aiStatusRow">
              <span className={isAiComplete ? 'statusPill complete' : 'statusPill'}>
                {isAiComplete ? 'Información completa' : 'Información pendiente'}
              </span>
              {missingFields.length > 0 && (
                <span className="missingText">
                  Pendiente: {missingFields.map((field) => SUMMARY_LABELS[field] ?? field).join(', ')}
                </span>
              )}
            </div>

            <div className="chatInputRow">
              <textarea
                aria-label="Mensaje para el asistente IA"
                placeholder="Escriba su respuesta aquí..."
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
            <span>03</span>
            <div>
              <h2>Resumen extraído</h2>
              <p>Revise la información que el asistente estructuró antes de guardar.</p>
            </div>
          </div>

          <SummaryList extractedData={extractedData} />
        </section>

        <section className="formSection">
          <div className="sectionHeader">
            <span>04</span>
            <div>
              <h2>Consentimiento sobre información y veracidad legal</h2>
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
