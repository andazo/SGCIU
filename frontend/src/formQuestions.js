export const formQuestions = [
  {
    id: 'registration_mode',
    label: 'Modalidad de registro',
    type: 'select',
    options: [
      { value: 'complete', label: 'Registro con datos de contacto' },
      { value: 'anonymous', label: 'Registro anónimo' },
    ],
    required: true,
  },
  {
    id: 'name',
    label: 'Nombre completo',
    type: 'text',
    placeholder: 'Ej. Ana Martinez',
    required: false,
  },
  {
    id: 'email',
    label: 'Correo electronico',
    type: 'email',
    placeholder: 'nombre@dominio.com',
    required: false,
  },
  {
    id: 'phone',
    label: 'Número de teléfono',
    type: 'tel',
    placeholder: 'Ej. 8888-8888',
    required: false,
  },
  {
    id: 'message',
    label: 'Mensaje',
    type: 'textarea',
    placeholder: 'Escribe cualquier observacion relevante',
  },
];
