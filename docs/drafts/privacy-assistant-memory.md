# Política de Privacidad: borrador para revisión legal (memoria de Confío IA)

**Estado:** borrador al 22 de noviembre de 2026. No publicado. Requiere la decisión del fundador y revisión legal.
La versión vigente es 1.13.1. Si el borrador de Gmail (1.14.0) se publica antes, este toma el número siguiente.
Diseño: `docs/designs/assistant-memory.md`.

No activar el resumen ni la memoria antes de publicar este texto.

---

## Sección 1, "support_and_content": punto a agregar

<!-- collect:start -->
- Memoria de Confío IA, separada por usuario y por cuenta: las preferencias que usted le pide recordar, elegidas de una lista cerrada (idioma, forma de las respuestas, trato, metas, ocupación, país donde tiene familia y gustos); qué mensajes suyos anteriores se usan como contexto, del que guardamos solo su identificador y no una copia ni un texto redactado; y sus ajustes de memoria.
<!-- collect:end -->

## Sección 2: punto a agregar

<!-- use:start -->
- Si la memoria de Confío IA está disponible para usted, adaptar sus respuestas a sus preferencias y tener presentes mensajes suyos anteriores de la misma cuenta. La memoria no se usa para decidir montos, destinatarios ni autorizaciones de pagos, para evaluar su riesgo ni para publicidad.
<!-- use:end -->

## Sección 3, punto de OpenAI: frase que reemplaza "y que procesa los mensajes, audios y fotos que usted envía a Confio Assistant para responderle"

<!-- share:start -->
y que procesa los mensajes, audios y fotos que usted envía a Confio Assistant para responderle, junto con los mensajes recientes de esa conversación y, si la usa, su memoria, y para elegir qué mensajes suyos anteriores sirven de contexto
<!-- share:end -->

## Sección 5: punto a agregar

<!-- rights:start -->
- Ver, borrar o apagar la memoria de Confío IA en «✨ Tu asistente» → «Memoria», o escribirle «olvida que…». Borrarla hace que Confío IA deje de usar esa información; no elimina los mensajes de su conversación de soporte, que se conservan según la sección 6.
<!-- rights:end -->

## Sección 6: punto a agregar

<!-- retention:start -->
- Una preferencia se conserva hasta que usted la borra o se elimina el mensaje con que la pidió; al borrarla eliminamos su contenido y conservamos solo la fecha del borrado. Las referencias a mensajes anteriores se reemplazan a medida que la conversación avanza y dejan de usarse si usted las borra o si se elimina el mensaje. Filtramos de forma automática claves, documentos, direcciones, montos y temas sensibles como salud, política o religión; ese filtro puede fallar. Las copias de seguridad automáticas se eliminan a los 7 días.
<!-- retention:end -->

## Eliminación de Datos, "2. Datos que se Eliminarán": punto a agregar

<!-- deletion:start -->
- Su memoria de Confío IA (preferencias y referencias a mensajes anteriores) se vacía al eliminarse su cuenta, aunque deban conservarse otros registros.
<!-- deletion:end -->

---

## Para decidir antes de publicar

1. Activada por defecto o con su consentimiento. El código viene con consentimiento (apagada) para las dos partes, preferencias y mensajes anteriores, cada una con su interruptor.
2. Ocupación, familia en otro país y gustos: ¿alguno es sensible en alguna jurisdicción?
3. Confirmar que el uso de datos para entrenamiento sigue desactivado en la cuenta de OpenAI.
4. El texto nombra solo a OpenAI. Si el asistente pasa a otro proveedor, hay que nombrarlo antes.
