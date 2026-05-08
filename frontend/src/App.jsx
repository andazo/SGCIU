import { useMemo, useState } from 'react';
import { formQuestions } from './formQuestions.js';

function buildInitialAnswers(questions) {
  return questions.reduce((answers, question) => {
    answers[question.id] = question.type === 'range' ? String(question.min ?? 1) : '';
    return answers;
  }, {});
}

function QuestionField({ question, value, onChange }) {
  const inputId = `field-${question.id}`;

  if (question.type === 'textarea') {
    return (
      <label className="field" htmlFor={inputId}>
        <span>{question.label}</span>
        <textarea
          id={inputId}
          name={question.id}
          placeholder={question.placeholder}
          value={value}
          required={question.required}
          onChange={(event) => onChange(question.id, event.target.value)}
        />
      </label>
    );
  }

  if (question.type === 'select') {
    return (
      <label className="field" htmlFor={inputId}>
        <span>{question.label}</span>
        <select
          id={inputId}
          name={question.id}
          value={value}
          required={question.required}
          onChange={(event) => onChange(question.id, event.target.value)}
        >
          <option value="">{question.placeholder ?? 'Selecciona una opcion'}</option>
          {question.options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (question.type === 'radio') {
    return (
      <fieldset className="field">
        <legend>{question.label}</legend>
        <div className="optionGrid">
          {question.options.map((option) => (
            <label className="option" key={option.value}>
              <input
                type="radio"
                name={question.id}
                value={option.value}
                checked={value === option.value}
                required={question.required}
                onChange={(event) => onChange(question.id, event.target.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (question.type === 'range') {
    return (
      <label className="field" htmlFor={inputId}>
        <span>{question.label}</span>
        <div className="rangeRow">
          <input
            id={inputId}
            type="range"
            name={question.id}
            min={question.min}
            max={question.max}
            step={question.step}
            value={value}
            required={question.required}
            onChange={(event) => onChange(question.id, event.target.value)}
          />
          <strong>{value}</strong>
        </div>
      </label>
    );
  }

  return (
    <label className="field" htmlFor={inputId}>
      <span>{question.label}</span>
      <input
        id={inputId}
        type={question.type}
        name={question.id}
        placeholder={question.placeholder}
        value={value}
        required={question.required}
        onChange={(event) => onChange(question.id, event.target.value)}
      />
    </label>
  );
}

export default function App() {
  const initialAnswers = useMemo(() => buildInitialAnswers(formQuestions), []);
  const [answers, setAnswers] = useState(initialAnswers);
  const [submittedAnswers, setSubmittedAnswers] = useState(null);

  function handleAnswerChange(questionId, value) {
    setAnswers((currentAnswers) => ({
      ...currentAnswers,
      [questionId]: value,
    }));
  }

  function handleSubmit(event) {
    event.preventDefault();
    setSubmittedAnswers(answers);
  }

  return (
    <main className="appShell">
      <section className="intro">
        <p className="eyebrow">SGCIU</p>
        <h1>Formulario de captura</h1>
        <p>
          Edita las preguntas desde <code>src/formQuestions.js</code> para adaptar
          este formulario a tu investigacion.
        </p>
      </section>

      <form className="formPanel" onSubmit={handleSubmit}>
        {formQuestions.map((question) => (
          <QuestionField
            key={question.id}
            question={question}
            value={answers[question.id]}
            onChange={handleAnswerChange}
          />
        ))}

        <div className="actions">
          <button type="submit">Guardar respuestas</button>
          <button type="button" className="secondary" onClick={() => setAnswers(initialAnswers)}>
            Limpiar
          </button>
        </div>
      </form>

      {submittedAnswers && (
        <section className="resultPanel" aria-live="polite">
          <h2>Ultimas respuestas</h2>
          <pre>{JSON.stringify(submittedAnswers, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}
