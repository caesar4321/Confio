// What the Gmail screen says, decided here so it can be tested without a screen. Version MAIL_CONSENT_VERSION in
// api.ts: change both together, and the privacy draft (docs/drafts/privacy-1.15.0-gmail.md).

/** What anyone reads before connecting: three lines, in plain words. */
export const CONSENT_POINTS: { icon: string; text: string }[] = [
  { icon: 'bell', text: 'Te aviso de pagos, vencimientos, citas y correos que esperan tu respuesta.' },
  { icon: 'message-circle', text: 'Me pides escribir o responder en nuestra conversación. Nada sale sin tu OK.' },
  { icon: 'calendar', text: 'Si quieres, cuento lo que tienes hoy en tu Google Calendar.' },
];

/** Always in sight before connecting: what is read, by whom, for how long. */
export const CONSENT_DATA = 'Leemos los correos que recibes, salvo publicidad, redes, foros y spam, cada uno con su '
  + 'conversación (también lo que respondiste). Una IA de OpenAI marca lo importante; no guardamos tus correos. Lo que te cuento queda en nuestra conversación hasta que '
  + 'desconectes.';

/** Confío is not verified by Google yet: Google says so on its screen. */
export const CONSENT_RISK = 'Google te mostrará un aviso de que Confío aún no está verificado. Por ahora hay cupo para '
  + '100 personas.';

/** The whole text the person accepts, behind "Cómo funciona". */
export function consentText(): string[] {
  return [
    'Conectas tu Gmail en la pantalla de Google y eliges qué permisos das: ver tus correos (necesario), enviar '
      + 'correos en tu nombre (opcional) y ver los eventos de tus calendarios (opcional). Confío no puede borrar ni '
      + 'cambiar tus correos ni tus eventos, y nunca recibe tu contraseña de Google.',
    'Cada 15 minutos revisamos los correos que recibes, salvo la publicidad, las redes sociales, los foros, el spam '
      + 'y la papelera. Para entender cada uno en su contexto, como en WhatsApp, leemos su conversación completa (hasta '
      + 'los últimos 8 correos del hilo, también los que tú enviaste), y Confío envía a OpenAI (Estados Unidos) el '
      + 'remitente, el asunto, la fecha y el texto de esos correos. OpenAI no entrena modelos con ellos y puede conservarlos hasta 30 días para controlar '
      + 'abusos, o más si la ley o la seguridad lo exigen. Antes tapamos los códigos que detectamos y descartamos '
      + 'los correos de códigos o cambios de contraseña, pero esa detección puede fallar.',
    'Cuando un correo reciente parece importante (un pago, un vencimiento, un viaje, una cita, una entrega, dinero '
      + 'que recibes o alguien esperando tu respuesta), te lo cuento en nuestra conversación de Confío IA: quién te '
      + 'escribió, el asunto y un resumen de una línea, sin enlaces, direcciones ni números largos. Esos mensajes '
      + 'quedan en tu conversación, que el equipo de Confío puede leer si pides ayuda, hasta que desconectes. Si ya '
      + 'respondiste o se resolvió en el mismo hilo, no te aviso.',
    'Una vez al día te llega una notificación con cuántas cosas hay de cada tipo y cuántos eventos tienes hoy, y una '
      + 'más si después aparece algo que vence hoy. Cuando te cuento un correo entre las 7 y las 22 h, te aviso como '
      + 'máximo una vez por hora, solo con el tipo (por ejemplo, «Tu Gmail trae un pago pendiente»). Las '
      + 'notificaciones nunca dicen de quién son, montos ni títulos.',
    'Con cada correo importante te propongo 2 o 3 respuestas cortas pensadas para esa conversación. En nuestra '
      + 'conversación me puedes pedir que responda un correo o escriba uno nuevo. Lo que me pides y el hilo se envían a '
      + 'OpenAI para redactarlo, y el correo queda en una tarjeta con el destinatario, el asunto y el texto exactos. '
      + 'Solo sale cuando tocas Enviar. Nunca pago nada por ti.',
    'Si das el permiso de calendario, cada mañana cuento los eventos de hoy de tu Google Calendar para el aviso. '
      + 'Si me preguntas por tu correo o tu calendario («¿qué tengo mañana?»), lo leo en ese momento: OpenAI lee los correos '
      + 'para responder tu pregunta, y lo que encontré (quién te escribió, el asunto y la fecha, o el título, el día y la hora de los eventos) '
      + 'lo procesan los proveedores de IA de Confío (OpenAI, Anthropic y Google) para responderte, y mi respuesta '
      + 'queda en nuestra conversación hasta que desconectes. Tus eventos no se guardan aparte.',
    'Confío guarda cifrados tu acceso y tu dirección de Gmail hasta que desconectes; de cada aviso, el tipo, la '
      + 'fecha, el remitente y un resumen, hasta 30 días después; y los borradores sin enviar, hasta 24 horas. Para '
      + 'respetar el cupo de Google guardamos un código derivado de cada cuenta que conecta, sin tu dirección.',
    'El uso de los datos de Google sigue la Política de Datos de Usuario de los Servicios API de Google, incluido el '
      + 'uso limitado. Puedes desconectar cuando quieras aquí, y borramos tu acceso, los avisos, los borradores y lo '
      + 'que te conté de tu correo en nuestra conversación.',
  ];
}

/** Connected: the screen only manages the connection. What arrives is told, and answered, in the conversation. */
export const LINKED_POINTS: { icon: string; text: string }[] = [
  { icon: 'message-circle', text: 'Te aviso de lo importante en nuestra conversación.' },
  { icon: 'corner-up-left', text: 'Ahí mismo me pides responder o escribir: nada sale sin tu OK.' },
  { icon: 'bell', text: 'Notificaciones sin remitentes, montos ni títulos: solo qué tipo de cosa llegó.' },
];
