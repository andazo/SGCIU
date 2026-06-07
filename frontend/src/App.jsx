import { useMemo, useState } from 'react';
import logoFlores from '../branding/logoFlores.png';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

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

export default function App() {
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
