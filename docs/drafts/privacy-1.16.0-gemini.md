# Política de Privacidad 1.16.0: borrador (Confío IA con Gemini)

**Estado:** publicado el 26 de noviembre de 2026 en `users/legal/documents.py` (1.16.0), con un cambio: las búsquedas en internet siguen en OpenAI, así que el párrafo de Google no las menciona.

**Contexto:** Confío IA pasa a responder con Gemini 4 Hydrogen (Google, mediante Google Cloud, nivel de pago). OpenAI sigue respondiendo cuando Gemini falla o tarda, coloca las tarjetas de pantallas junto a cada respuesta y transcribe los audios. Hoy la sección 3 nombra solo a OpenAI para Confío IA.

## Cambio en la sección 3 (Compartir Información)

Agregar después del párrafo de OpenAI:

> Con Google (Estados Unidos), mediante su servicio Gemini en Google Cloud, que procesa por cuenta de Confío los mensajes y fotos que usted envía a Confío IA para responderle, junto con los mensajes recientes de esa conversación, los datos de su cuenta que Confío IA consulta para contestar (por ejemplo, su saldo o sus movimientos) y, si está activada, su memoria. Cuando una respuesta necesita información actual de internet, Google recibe solo la búsqueda, sin datos de su cuenta. Google no usa estos datos para entrenar sus modelos y puede conservarlos por un tiempo limitado, según sus propias condiciones, para prevenir abusos. Si Google no responde a tiempo, la respuesta la da OpenAI, como se describe en el párrafo anterior.

Y en el párrafo de OpenAI, cambiar el final:

> …y que procesa los mensajes, audios y fotos que usted envía a Confio Assistant para responderle…

por:

> …y que transcribe los audios que usted envía a Confío IA, elige la pantalla de la app que se muestra junto a cada respuesta, responde cuando Gemini no lo hace y procesa, para esas tareas, sus mensajes y fotos, los mensajes recientes de esa conversación y, si está activada, su memoria, y elige qué mensajes suyos anteriores sirven de contexto…

## Por verificar antes de publicar

- Que la clave de Gemini (`prod/gemini-api-key`) pertenece a un proyecto de Google Cloud con facturación de pago (crédito de startup). En el nivel gratuito Google puede usar los datos para mejorar sus productos, y eso contradice este texto.
- El plazo de conservación de Google para prevenir abusos en la API de Gemini de pago (sus condiciones de uso adicionales).
- Si el contrato de procesamiento de datos de Google Cloud (CDPA) está aceptado en la consola para ese proyecto.
