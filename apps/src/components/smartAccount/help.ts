// The paragraph behind each screen's help circle. One line lives on the
// screen; the explanation lives here. No prices, rates or fees: those come
// from the server (the plan, the offer's own disclosures).
import type { HelpContent } from './kit';

/** The account's help; without the beneficiary feature it does not mention one. */
export function helpAccount(beneficiary: boolean): HelpContent {
  return {
    title: '¿Cómo funciona tu Cuenta inteligente?',
    paragraphs: [
      'Es una cuenta aparte dentro de Confío. Tú decides qué mueves a ella desde tu billetera, y puedes devolverlo cuando quieras.',
      ...(beneficiary
        ? ['Eliges a una persona que la recibirá si algún día dejas de usarla. Mientras la uses, sigue siendo solo tuya: si esa persona la pide, cualquier acción que firmes en tu Cuenta inteligente lo cancela.']
        : []),
      'Lo que está en la cuenta sigue las reglas que tú creas: enviarle a alguien, pagar a una cuenta bancaria guardada o invertir, con la frecuencia que elijas.',
      beneficiary
        ? 'Solo lo que está dentro de la cuenta se automatiza y pasa a tu beneficiario. Tu billetera personal no cambia.'
        : 'Solo lo que está dentro de la cuenta se automatiza. Tu billetera personal no cambia.',
      'El plan se cobra del dinero que tienes en la cuenta. Es una cuenta de autocustodia, no una cuenta bancaria: solo tu firma mueve tu dinero fuera de tus reglas.',
    ],
  };
}

export const HELP_ACCOUNT: HelpContent = helpAccount(true);

export const HELP_MOVE: HelpContent = {
  title: 'Mover entre tu billetera y tu cuenta',
  paragraphs: [
    'Mover dinero entre tu billetera y tu Cuenta inteligente es un traslado entre dos lugares tuyos: no es una conversión.',
    'Antes de firmar ves la lista exacta de lo que se mueve. Lo que la cuenta no admite se queda donde está y te decimos por qué.',
    'Si la lista es larga, se firma en varios pasos. Cada paso se completa por separado.',
  ],
};

export const HELP_RULES: HelpContent = {
  title: 'Reglas automáticas',
  paragraphs: [
    'Una regla repite una operación por ti: enviarle a alguien de Confío, pagar a una cuenta bancaria que ya guardaste o invertir.',
    'Tú firmas cada regla una vez, con su monto, su destino y su frecuencia. Confío solo puede ejecutar exactamente eso, y puedes detenerla cuando quieras.',
    'Si un día no hay saldo suficiente en la cuenta, te avisamos y lo reintentamos por un tiempo. Nunca se toma dinero de tu billetera personal.',
    'En los pagos a cuenta bancaria el monto en dólares es fijo. Lo que llega en moneda local depende del tipo de cambio de ese día.',
    'Con Confío IA+ puedes pedir por chat reglas de inversión o detener una regla: el asistente te deja el cambio listo y tú lo revisas y lo firmas aquí. Las reglas de envío y de pago a cuenta bancaria se crean y se cambian aquí. Detener una regla la borra; puedes crearla de nuevo cuando quieras.',
  ],
};

export const HELP_WATCHES: HelpContent = {
  title: 'Tus alertas',
  paragraphs: [
    'Una alerta te avisa cuando un precio o el tipo de cambio llega al nivel que tú elegiste. Las creas hablando con Confío IA+.',
    'Si pediste dejar lista una compra, al cumplirse te la mostramos para que la revises y la firmes. Se guarda como una regla que se repite hasta que la detengas. Si solo querías una compra, detenla después de la primera. Una alerta nunca compra ni vende sola.',
    'Cada alerta avisa como máximo una vez al día.',
  ],
};

export const HELP_BENEFICIARY: HelpContent = {
  title: 'Tu beneficiario',
  paragraphs: [
    'Eliges a una persona verificada en Confío. Ella debe aceptar. Solo cubre lo que está dentro de tu Cuenta inteligente.',
    'Si algún día esa persona pide la cuenta, empieza un plazo que tú elegiste. Durante todo el plazo te avisamos por todos los medios.',
    'Cualquier acción que firmes en tu Cuenta inteligente cancela el pedido, y Confío agrega una automáticamente a cada operación que firmas desde tu cuenta personal. Las operaciones de una cuenta de negocio no lo cancelan. Si el plazo termina sin ninguna de esas firmas, la cuenta pasa a esa persona.',
    'Puedes cambiar el plazo, retirar una invitación o quitar a tu beneficiario cuando quieras.',
  ],
};

export const HELP_DESIGNATED: HelpContent = {
  title: 'Ser beneficiario',
  paragraphs: [
    'Alguien te eligió para recibir su Cuenta inteligente si deja de usarla. Aceptar no te cuesta nada ni mueve dinero.',
    'Si llega ese momento, tú pides la cuenta y empieza un plazo fijo. Si su dueño firma una acción en su Cuenta inteligente o una operación desde su cuenta personal en ese plazo, el pedido se cancela.',
    'Al terminar el plazo puedes recibir la cuenta y mover lo que tenga a tu billetera.',
  ],
};

export const HELP_BILLING: HelpContent = {
  title: 'Tu plan y sus cobros',
  paragraphs: [
    'El plan se cobra del dinero que tienes dentro de la cuenta, al inicio de cada período. Se renueva al precio vigente en ese momento.',
    'Si no hay dólares suficientes, la automatización se pausa y te avisamos varios días. Al agregar dólares, todo vuelve a funcionar.',
    'Si pasan los avisos y sigue faltando, se vende de tus inversiones solo lo necesario para un período. Lo que sobra se queda en tu cuenta.',
    'Un cobro fallido nunca devuelve tu dinero a la billetera ni quita a tu beneficiario.',
  ],
};

export const HELP_INHERITED: HelpContent = {
  title: 'Cuenta heredada',
  paragraphs: [
    'Esta cuenta ahora es tuya. No tiene plan, reglas ni beneficiario: solo guarda lo que recibiste.',
    'Puedes mover todo a tu billetera o a tu propia Cuenta inteligente, cuando quieras y sin fecha límite.',
  ],
};
