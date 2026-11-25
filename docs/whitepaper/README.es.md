# Confío: el asistente de IA que paga en América Latina

**Dile a Confío lo que necesitas. Paga, compra e invierte con tus dólares, y tú mantienes el control.**

Confío es un asistente financiero no custodial, totalmente de código abierto y centrado en la IA, creado para la realidad del dólar en América Latina. Una persona le pide a Confío IA, con sus propias palabras, pagarle a una persona o a una tienda, comprar algo en línea, recargar o invertir; Confío lo prepara en el canal local de pago de ese país, muestra las condiciones exactas y actúa solo con la confirmación de la persona o dentro de límites que ella firmó. Por debajo hay una infraestructura verificable de dólares en BNB Smart Chain de la que Confío no puede retirar fondos.

**Referencia global · Versión 4.5 · Noviembre de 2026**<br>
Julian Moon · Fundador y CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Pídelo en palabras; Confío lo hace.*

**Original autoritativo:** el [documento en inglés](README.md) es la única versión autoritativa del whitepaper de Confío. Esta traducción al español se ofrece por conveniencia y puede quedar rezagada respecto del original; si difiere del texto en inglés, prevalece el texto en inglés. Traducción sincronizada con la versión 4.5 el 25 de noviembre de 2026.

Este documento es la referencia global actual sobre la arquitectura de producto, la estrategia, el modelo operativo y los riesgos materiales de Confío. Las condiciones detalladas de asignación y vesting de $CONFIO se mantienen en el documento separado de tokenomics.

<details>
<summary><strong>Contenido</strong></summary>

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Tesis de mercado](#2-tesis-de-mercado)
3. [Confío IA: el asistente que paga](#3-confío-ia-el-asistente-que-paga)
4. [Cuenta inteligente: una cuenta que el asistente puede operar](#4-cuenta-inteligente-una-cuenta-que-el-asistente-puede-operar)
5. [Por qué se puede confiar en que una IA pague: la base de BNB Smart Chain](#5-por-qué-se-puede-confiar-en-que-una-ia-pague-la-base-de-bnb-smart-chain)
6. [cUSD y cUSD+: dinero y ahorro](#6-cusd-y-cusd-dinero-y-ahorro)
7. [Pagos, nóminas, inversión y Comprar](#7-pagos-nóminas-inversión-y-comprar)
8. [$CONFIO en BNB Smart Chain](#8-confio-en-bnb-smart-chain)
9. [Billetera, seguridad y arquitectura de código abierto](#9-billetera-seguridad-y-arquitectura-de-código-abierto)
10. [Usuarios, distribución y entrada al mercado](#10-usuarios-distribución-y-entrada-al-mercado)
11. [Modelo de negocio](#11-modelo-de-negocio)
12. [Cumplimiento y modelo operativo](#12-cumplimiento-y-modelo-operativo)
13. [Riesgos y mitigaciones](#13-riesgos-y-mitigaciones)
14. [Hoja de ruta y estado actual](#14-hoja-de-ruta-y-estado-actual)
15. [Aviso legal](#15-aviso-legal)
16. [Notas](#notas)

</details>

---

## 1. Resumen ejecutivo

Confío es un asistente financiero centrado en la IA para América Latina. La conversación con **Confío IA** es la superficie del producto: en las versiones actuales de la app, la pantalla de inicio es el chat, la primera conversación es el proceso de alta y cada tarea de la app se puede alcanzar desde ahí. Una persona escribe lo que necesita con sus propias palabras —paga este QR, mándale dólares a mi hermana, compra esto en esa tienda y págalo, recarga, compra un poco de oro— y Confío lo hace con los dólares de la propia persona, en el canal local de ese país, tras una confirmación exacta. <sup>[3, 26]</sup>

> **Tesis de producto**
>
> En América Latina, lo difícil de pagar no es elegir un producto; es atravesar canales locales fragmentados, hábitos de pago informales y un déficit de confianza. La plataforma de consumo ganadora no les pedirá a las personas aprender cripto ni instalar diez apps. Les permitirá pedirlo en palabras y demostrará —en código que cualquiera puede leer y con límites on-chain que cualquiera puede comprobar— que el asistente solo puede hacer lo que la persona aprobó. Confío combina ese asistente con dólares no custodiales, canales locales de pago y un canal en español liderado por su fundador de aproximadamente 480,000 personas, con un gasto en medios pagados prácticamente nulo hasta la fecha.

Lo que Confío IA puede hacer hoy, con cada paso confirmado por la persona o acotado por límites que ella firmó:

| Tarea | Cómo funciona |
| --- | --- |
| Pagar a personas y códigos QR | El asistente prepara un envío o un pago por canal local como una tarjeta en el chat; el código, no el modelo, pregunta el monto y verifica al beneficiario; la persona confirma y firma en su propio teléfono. |
| Comprar en tiendas en línea | Un agente de compras busca en una o varias tiendas desde un navegador en la nube, arma el carrito, muestra el total real con envío y le paga a la tienda con el canal local de su país: SPEI en México, Pix en Brasil, Pago Móvil en Venezuela (limitado a tiendas que solo piden la referencia del pago); en Bolivia se hace el pedido y la persona paga el QR de la tienda. |
| Recargar y retirar | El chat lleva al formulario de recarga o retiro con los límites vigentes del proveedor en ese país. |
| Invertir | Las operaciones en Ondo Stocks, oro y bitcoin se proponen como tarjetas con precio. Para suscriptores de Cuenta inteligente, las operaciones del chat pueden ejecutarse dentro de un tope semanal firmado por el titular. |
| Automatizar | Cuenta inteligente ejecuta envíos programados, pagos a cuentas bancarias (CLABE, Pix, Pago Móvil) e inversión automática, y puede pasar a un beneficiario designado. |

La base es lo que hace seguro darle a un asistente acceso al dinero. La clave de la billetera del usuario se genera en su dispositivo y Confío no la conserva; los saldos son cUSD o cUSD+ en BNB Smart Chain; las comisiones de red están patrocinadas; y las acciones automáticas pasan por una cuenta de contrato inteligente propia de cada usuario cuyos límites se aplican on-chain. La clave del relayer de Confío, por sí sola, no puede retirar los fondos de un usuario.

| Componente | Función principal | Diseño |
| --- | --- | --- |
| Confío IA | El asistente y la superficie del producto. | Los modelos leen y proponen; el código verifica hechos, pregunta montos y aplica confirmaciones, topes e interruptores por país. |
| Cuenta inteligente | Una cuenta que el asistente puede operar dentro de límites. | Una cuenta de contrato inteligente inmutable por usuario, cuya propietaria es la billetera del usuario; US$149.99 al año (predeterminado) o US$14.99 al mes. |
| cUSD | Dólar universal para pagos. | Token BSC actualizable y respaldado 1:1 por USDT; el único perímetro de la comisión externa de conversión del 0.9%. |
| cUSD+ | Instrumento de ahorro en dólares para usuarios elegibles. | Participaciones acumulativas actualizables y respaldadas por USDY para usuarios elegibles según Ondo; la conversión interna cUSD↔cUSD+ no tiene comisión. |
| Ondo Stocks, oro, bitcoin, Futuros | Inversión. | Routers con código fuente verificado liquidan las operaciones directamente al usuario; Oro y Bitcoin y Futuros no se ofrecen en la versión para iOS. |
| $CONFIO | Token comunitario y del ecosistema. | BEP-20 de oferta fija con una preventa on-chain pagada en cUSD. No respalda los saldos en dólares de los usuarios. |

Al 25 de noviembre de 2026, Confío registra 10,233 usuarios que completaron la verificación telefónica y 3,407 dispositivos alcanzables mediante notificaciones push, de los cuales 3,402 se utilizaron en los últimos 30 días. Al 23 de julio de 2026 (la instantánea más reciente disponible con la misma definición), 177 usuarios habían completado la verificación de identidad de Didit presentando un documento de identidad oficial y tomando una selfie en vivo, con una tasa de finalización del 61.5% entre quienes la iniciaron. Son métricas operativas internas, no cifras auditadas independientemente, y no deben interpretarse como número de usuarios con fondos ni de usuarios activos mensuales. <sup>[14]</sup>

Los vaults de cUSD y cUSD+, los routers de Ondo Stocks y de swaps, el delegado de transacciones patrocinadas, la factory y las implementaciones de cuenta de Cuenta inteligente, el spender de compras, el escrow de Comprar, el token $CONFIO y sus vaults de preventa, recompensas y vesting, el contrato de pagos a comercios y el vault de nóminas están desplegados y tienen su código fuente verificado en BNB Smart Chain. <sup>[8, 9, 17, 27]</sup>

## 2. Tesis de mercado

### 2.1 Un problema de acceso al dólar, no de conocimiento de cripto

América Latina no atraviesa una única crisis monetaria homogénea. Algunos usuarios necesitan protección frente a la volatilidad de su moneda local; otros necesitan liquidación transfronteriza asequible, un lugar seguro para ahorrar en dólares o una forma práctica de pagar y cobrar. Lo que conecta estos mercados es la demanda de una unidad confiable en dólares y el descontento con las fricciones que la rodean. La adopción de stablecoins en la región muestra que este comportamiento ya existe on-chain y no es meramente teórico. <sup>[2]</sup>

| Mercado | Necesidad de dólares observada | Implicación para el producto |
| --- | --- | --- |
| Argentina | La inflación y los controles de capital recurrentes, junto con la memoria institucional del *corralito* de 2001 y la conversión forzosa de depósitos en dólares, enseñaron a los hogares a valorar el acceso y el control tanto como el rendimiento nominal. La mayoría de las restricciones cambiarias recientes se flexibilizaron, pero el déficit histórico de confianza sigue siendo relevante. <sup>[19]</sup> | Un producto en dólares debe dejar especialmente claros los límites de custodia, los derechos de retiro, los precios y los cambios de reglas. |
| Venezuela | La inflación extrema llevó al dólar estadounidense a cumplir funciones de reserva de valor y de pago cotidiano, creando una economía muy dolarizada pero operativamente fragmentada. <sup>[20]</sup> | El acceso al dólar y la utilidad de Pago Móvil son necesidades inmediatas, mientras que las sanciones, la disponibilidad de proveedores y el cumplimiento exigen controles más estrictos. |
| Bolivia | La evaluación del FMI de 2025 describió reservas de divisas utilizables cercanas a cero, una brecha creciente con el tipo de cambio paralelo y fuertes límites al acceso del sector privado a dólares al tipo oficial. <sup>[21]</sup> | Un acceso confiable, precios locales transparentes y canales QR interoperables pueden resolver un problema diario de liquidez, no un caso de uso especulativo. |
| Perú | Los hogares ya mantienen decenas de miles de millones de dólares en depósitos en moneda extranjera, mientras que Yape, PLIN y los sistemas QR interoperables han normalizado los pagos móviles. <sup>[22]</sup> | La oportunidad no es enseñar a los usuarios a querer dólares, sino ofrecer ahorro y pagos en dólares portátiles con puntos de entrada locales familiares. |
| México | Los depósitos bancarios en moneda extranjera y aproximadamente US$62.5 mil millones en remesas anuales demuestran demanda tanto de ahorro en dólares como de transferencias transfronterizas. <sup>[23]</sup> | El acceso a SPEI, los saldos en dólares, el rendimiento y las transferencias familiares pueden convivir en un solo producto de consumo. |
| Colombia | Estados Unidos origina más de la mitad de las remesas entrantes, mientras que Colombia acoge a aproximadamente 2.8 millones de venezolanos. <sup>[24, 25]</sup> | El acceso bancario local puede conectar las remesas internacionales con el corredor de transferencias familiares Colombia–Venezuela. |
| Estados Unidos y España | Son dos de los mercados de origen más importantes de las remesas latinoamericanas. Estados Unidos representa el 35.7% de las entradas a Sudamérica; Europa, el 36.2%, incluidos 19.7 puntos porcentuales de España. <sup>[24]</sup> | Los ingresos de la diáspora deberían llegar a los saldos en dólares de los destinatarios sin obligar a ambas partes a usar un producto de trading. |

El resultado es un **reflejo regional hacia el dólar**: las personas buscan exposición al USD incluso cuando el acceso es caro, informal u operativamente frágil.

### 2.2 Las remesas como oportunidad de balance

América Latina y el Caribe recibieron aproximadamente US$173.7 mil millones en remesas en 2025. <sup>[1]</sup> La mayoría de los productos trata una remesa como una transferencia aislada. Confío la trata como el inicio de una relación financiera: el destinatario puede conservar dólares, generar rendimiento variable mediante cUSD+, enviar a contactos, pagarle a un comercio o a una tienda en línea, o retirar por un canal local, simplemente pidiéndolo.

### 2.3 Por qué importa un enfoque centrado en la IA en América Latina

Cada país tiene su propio sistema de pagos. Brasil paga con Pix, el sistema de pagos instantáneos del banco central; México con transferencias SPEI a una CLABE de 18 dígitos; Colombia está pasando a las llaves y el QR de Bre-B; Perú con Yape, PLIN y QR interoperables; Venezuela con Pago Móvil; Bolivia con códigos QR bancarios. <sup>[22, 28, 29]</sup> Un checkout en un país rara vez acepta el canal de otro, y muchos pagos cotidianos —un vendedor por WhatsApp, un trabajador al que se le paga por QR, una tienda en línea que muestra datos bancarios en lugar de un formulario de tarjeta— ocurren fuera de las redes de tarjetas.

Para la persona, esto significa aprender una app, un formulario y un conjunto de identificadores distintos para cada tarea. Para un asistente es la oportunidad opuesta: el código puede elegir el canal a partir del país del beneficiario, mientras la persona solo dice lo que quiere. Los pagos de agentes basados en tarjetas, comunes en mercados donde todos tienen una tarjeta, no llegan a estos canales. Un asistente que mantiene un saldo en dólares en autocustodia y tiene acceso de pago a los canales nacionales puede pagar donde un asistente basado en tarjetas no puede seguirlo.

Los propios registros del asistente de Confío apuntan en la misma dirección: las personas ya le piden, con sus propias palabras, enviar dinero al exterior y pagar por QR. Confío informa esto de forma cualitativa; no publica el contenido de los chats.

### 2.4 El problema más profundo: *falta de confianza*

Los usuarios latinoamericanos han vivido congelamientos bancarios, controles cambiarios, fintechs fallidas, intermediarios informales, diferenciales ocultos y plataformas cripto diseñadas en torno a la especulación. Darle dinero a una IA plantea la misma pregunta con más fuerza: ¿qué le impide hacer algo indebido?

La respuesta de Confío tiene tres capas:

1. **Control verificable:** la clave de la billetera del usuario se genera en su dispositivo y Confío no la conserva.
2. **Autonomía acotada:** el asistente no puede inventar montos ni beneficiarios; cada pago es una confirmación exacta o cae dentro de un límite que la persona firmó on-chain.
3. **Confianza humana:** educación primero en español, precios claros, métodos de pago locales, liderazgo visible y un asistente que dice con claridad lo que no puede hacer.

*Lo tuyo, tuyo* es, por tanto, una promesa de marca y a la vez una restricción de arquitectura.

## 3. Confío IA: el asistente que paga

### 3.1 El chat es el producto

En las versiones actuales, Inicio es la conversación con Confío IA. Un usuario nuevo conoce a su asistente y se le pregunta, en palabras, para qué quiere Confío; la respuesta define los siguientes pasos. Cada pantalla que ofrece el menú —recarga, retiro, Cobrar, invitaciones, historial, inversiones, Comprar, Cuenta inteligente, herramientas para negocios y nóminas— tiene una puerta desde el chat, de modo que una persona que nunca abre un menú puede hacerlo todo igualmente. El asistente responde preguntas, lee los movimientos y el resumen mensual de la propia persona, acepta fotos y notas de voz, y puede buscar en la web para preguntas generales. <sup>[3, 26]</sup>

Confío IA responde y orienta a todos. Explica instrumentos, riesgos y los números de la propia persona, pero no le dice que compre, venda o mantenga un ticker concreto, ni predice precios.

### 3.2 Cómo una solicitud se convierte en un pago

| Paso | Quién lo hace | Qué se verifica |
| --- | --- | --- |
| 1. Entender | El modelo lee la solicitud y decide de qué tarea se trata. | La salida de herramientas y el texto de terceros se tratan como datos, nunca como instrucciones; después de una búsqueda web, ese turno pierde sus herramientas de dinero. |
| 2. Preguntar el monto | El código, no el modelo, escribe la pregunta (“¿Cuántos dólares? Escribe solo el número”). | Nunca se extrae un monto de una frase; el número escrito solo como siguiente mensaje es a la vez el monto y el sí. Un “no” retira las tarjetas pendientes. |
| 3. Resolver el beneficiario | El código interpreta y valida el destino: llaves Pix y códigos QR con su suma de verificación, dígitos de control de la CLABE, datos de Pago Móvil, contactos de Confío. | La tarjeta muestra solo lo que el código resolvió y el canal validó; un nombre que nadie verificó nunca se marca como verificado. |
| 4. Cotizar | El código calcula el precio del pago: monto local, total en dólares, tipo de cambio, comisión de Confío, vencimiento. | Un cobro con un monto local fijo se paga exactamente; la persona ve el total antes de confirmar. |
| 5. Confirmar | La persona revisa la tarjeta y firma en su propio dispositivo (o, para una acción automática de un suscriptor, la cuenta comprueba on-chain el tope que se firmó). | El modelo no puede dibujar la hoja de confirmación ni puede firmar. |
| 6. Liquidar e informar | El pago se ejecuta en el canal local; la tarjeta sigue el estado que reporta el proveedor. | Una tarjeta nunca dice “pagado” antes de que el canal reporte que se completó. |

Qué canales se ofrecen lo deciden interruptores en vivo por país y por proveedor, no el modelo. Cuando un corredor está pausado, el asistente lo dice en lugar de improvisar una ruta.

### 3.3 El agente de compras

Confío IA puede comprar en tiendas en línea. La persona nombra un producto (y, si quiere, una tienda); cuando no se nombra ninguna tienda, una sola búsqueda en varias tiendas devuelve una lista breve de ofertas. Luego, un agente de compras trabaja en un navegador en la nube que la persona puede ver en vivo: abre la tienda, agrega los artículos elegidos, llega al checkout y lee el total real con envío. <sup>[3]</sup>

- **Elegir es consentir.** Cada producto ofrecido muestra un total máximo (“hasta $X con envío”). Elegirlo aprueba ese artículo, esa cantidad y ese total máximo. Un total real más alto, un precio ilegible o un pagador distinto hacen que vuelva a aparecer una tarjeta de pedido ordinaria con el desglose real.
- **Los modelos deciden, el código verifica hechos.** Un modelo maneja el navegador y un juez separado —de una familia de modelos distinta— revisa cada clic; una revisión final lee la última página antes de hacer el pedido. El código verifica solo hechos: una aprobación genera un solo pedido; ambos modelos deben leer el mismo total, y ese total debe aparecer en la página; un identificador de pago debe ser uno válido que se muestre junto al monto aprobado en una página que apareció después del pedido, nunca uno tomado del título de un artículo ni visto antes del pedido.
- **Límites en el código.** Cada tarea tiene límites de pasos, tiempo y costo de modelo que aplica el servidor, nunca el modelo.
- **Canales locales según el país de la tienda.** El canal sigue al país de la tienda: datos bancarios SPEI leídos del propio checkout de la tienda en México (se paga el monto exacto en pesos; cualquier excedente de conversión queda en la cuenta local de la persona), QR Pix en Brasil y Pago Móvil en Venezuela, donde el pago se hace antes del pedido y la referencia se ingresa en el formulario de la tienda. En Bolivia, mientras los pagos QR mediante Confío estén desactivados, el agente hace el pedido y la persona paga el QR de la tienda desde su banco. Los demás países se rechazan en lugar de pagarse con una transferencia aproximada.
- **Quién paga.** La búsqueda, el carrito y la revisión con precio son gratuitos para todos. Comprar y pagarle a la tienda es un beneficio de Cuenta inteligente: la cuenta paga mediante una regla “Compras con Confío IA” firmada una sola vez con Confío Face (por defecto US$200 por período de 28 días, editable). Una compra nunca se paga directamente desde la billetera personal.

El agente de compras está en una etapa temprana. Las páginas de las tiendas cambian, algunos checkouts no ofrecen un canal local pagable a cuentas ordinarias y Confío todavía no ha demostrado que las compras se completen de forma confiable en muchas tiendas. Confío lo presenta como una capacidad que funciona, con límites honestos, no como un problema resuelto.

### 3.4 Ejecución automática dentro de límites firmados

Para los suscriptores de Cuenta inteligente, desde el 25 de noviembre de 2026, las operaciones desde el chat en Ondo Stocks, oro y bitcoin, las compras en Comprar y las compras en tiendas pueden ejecutarse por la cuenta de la persona sin una firma por acción, dentro de límites que el titular firmó:

- **Tope de operaciones.** Se elige en la primera operación automática y se firma una sola vez con Face (por ejemplo US$250, 1,000 o 2,500 por semana, u otro monto). Cuentan tanto las compras como las ventas. El tope funciona como un balde con fugas (*leaky bucket*): como máximo un tope en cualquier instante y un tope por semana en promedio (poco menos de dos topes dentro de una misma semana).
- **Los fondos se quedan en la cuenta.** Lo que el chat compra se mantiene en la cuenta. El relayer solo puede activar acciones con la forma de una regla: los swaps deben mantenerse dentro del 1.5% de un feed de precios de Chainlink, la comisión de acciones está acotada en 90 puntos básicos y las ventas deben devolver su valor a la cuenta dentro de esa banda.
- **Notificación e interruptor de emergencia.** Cada operación automática notifica al titular; una que no tenga detrás una propuesta del chat genera una alerta de seguridad. El Safe puede detener todas las vías automáticas a la vez (`tradePaused`).
- **Las pantallas de uso propio siguen siendo gratuitas.** Las pantallas Acciones, Oro y Bitcoin y Comprar siguen disponibles desde la billetera personal, firmadas por la persona.

### 3.5 Lo que Confío IA no hará

- Extraer un monto de una frase, o mover dinero ante un “sí” a una pregunta que el propio modelo escribió sin condiciones verificadas por el código.
- Pagarle a un beneficiario cuyos datos el código no pudo validar, o presentar como verificado un nombre no verificado.
- Pagar por encima de un total que la persona aprobó, o por encima de un tope que la persona firmó.
- Pagarle a una tienda en un país sin un canal que pague el monto local exacto de la tienda.
- Recomendar un ticker concreto o predecir precios.
- Ofrecer Oro y Bitcoin o Futuros a usuarios de iOS, ni ningún producto del que la persona quede excluida por su país o su elegibilidad.
- Traspasar la conversación en silencio: cuando no puede hacer algo, lo dice y, cuando es posible, abre la pantalla donde la persona puede hacerlo por sí misma.

### 3.6 Límites actuales por país

Las capacidades siguen los interruptores en vivo de los proveedores y cambian; este es el estado al 25 de noviembre de 2026. <sup>[13]</sup>

| País | Disponible hoy | No disponible o pausado |
| --- | --- | --- |
| México | Recarga y retiro; CLABE propia para recibir pesos; pagos SPEI a cualquier CLABE; pagos programados a CLABE con Cuenta inteligente; pagos SPEI del agente de compras. | — |
| Brasil | Pagos Pix por llave, QR o código; recepción por QR Pix; pagos programados por Pix con Cuenta inteligente; pagos Pix del agente de compras. | — |
| Venezuela | Recarga por Pago Móvil y envíos por Pago Móvil; pagos por Pago Móvil con Cuenta inteligente; agente de compras para tiendas que solo piden la referencia del pago. | Tiendas que requieren otros datos de pago. |
| Bolivia | Recarga y retiro bancario; marketplace Comprar; agente de compras con la persona pagando el QR de la tienda. | Pagar y recibir códigos QR bancarios mediante Confío (desactivado). |
| Argentina, Chile, Perú | Canales locales de recarga; retiros donde el proveedor los ofrece. | Pagos a CVU y QR argentinos desde una cuenta local de Confío (pendiente de que el proveedor esté listo). |
| Colombia | Retiros mediante la rampa existente. | Recarga, y conversión y pagos por Bre-B (pausados). |

## 4. Cuenta inteligente: una cuenta que el asistente puede operar

### 4.1 Qué es

Cuenta inteligente es una cuenta de pago dentro de Confío. Técnicamente es un contrato inteligente separado, uno por usuario, cuya propietaria es la billetera personal del usuario. El usuario mueve activos a ella; los activos que contiene pueden moverse según reglas que el usuario define y pueden pasar a un beneficiario designado. Los activos de la billetera personal no se ven afectados. <sup>[27]</sup>

| Incluye | Lo que obtiene el usuario |
| --- | --- |
| Pagos y transferencias automáticos | Envíos diarios, semanales, quincenales o mensuales a usuarios de Confío y pagos a un destino bancario guardado (CLABE, Pix, Pago Móvil; los pagos por Bre-B en Colombia están pausados). |
| Inversión automática | Compras periódicas de acciones, bitcoin y oro. |
| Confío IA+ | El asistente ejecuta sobre la cuenta del titular: propone los cambios de reglas que el titular pide, mantiene una distribución objetivo con nuevas compras, configura alertas, redacta una revisión mensual, hace operaciones automáticas dentro del tope semanal y compra en tiendas dentro del tope de compras. |
| Beneficiario (*Herencia Digital*) | Un beneficiario verificado por Didit puede tomar la titularidad tras un período de impugnación (por defecto 180 días, seleccionable entre 90 y 1,825) durante el cual cualquier acción firmada por el titular cancela el reclamo. |

**Precio:** US$149.99 al año (preseleccionado) o US$14.99 al mes, un solo nivel, sin reembolsos. La tarifa se cobra desde dentro de la cuenta: primero de los dólares y luego, tras los avisos, mediante la venta forzosa de otros activos por el monto de la tarifa de un período. La comisión de conversión del 0.9% no cambia y no se exime para los suscriptores. <sup>[27]</sup>

### 4.2 Diseño del contrato

- **Las cuentas son inmutables.** Cada cuenta es un clon EIP-1167 sin función de actualización, sin `DELEGATECALL` y sin `SELFDESTRUCT`. Cada límite del que depende la cuenta (tarifa máxima, mínimos de aviso, márgenes del período de impugnación) es una constante de la cuenta, y los valores leídos de la factory se acotan, de modo que una actualización de la factory no puede ampliarlos. `withdraw`, `withdrawAll`, `cancelClaim` y las funciones de reclamo funcionan aunque fallen todas las llamadas a la factory.
- **Factory por generación.** La factory UUPS, cuyo propietario es el Safe de 3 de 5, guarda la configuración global y crea una cuenta vigente por titular. Desde el 25 de noviembre de 2026 registra una implementación por generación: las cuentas v1 existentes conservan su bytecode, las cuentas nuevas usan `ConfioSmartAccountV2`, y pasar a v2 es un `migrate()` opcional que el titular firma en un solo lote.
- **Novedades de v2.** Tipos de regla Trade y Purchase, `relayTrade` y `relayPurchase` exclusivos del relayer, un balde con fugas por regla, un intervalo mínimo entre operaciones retransmitidas, bandas de feed de precios y el límite de comisión descrito en la sección 3.4.
- **Compras.** Una compra en tienda la retira `ConfioPurchaseSpender`: la propia verificación de reglas de la cuenta envía exactamente el USDT aprobado por la salida normal del 0.9%, y la misma transacción lo reenvía íntegro al depósito puente de ese pago; nada queda en el spender. Las compras en Comprar desde el chat entran al escrow de Comprar mediante `depositFrom`, que registra al titular como comprador y reembolsa a la cuenta que pagó.

### 4.3 El supuesto de confianza, dicho con claridad

Las operaciones y compras automáticas confían en `ConfioStockRouter`, `ConfioSwapRouter` y `ConfioMarketEscrow`, que el Safe puede actualizar, del mismo modo que las reglas de compra v1 ya confían en los routers. Una clave de relayer comprometida, por sí sola, no puede sacar valor de una cuenta. Una clave de relayer comprometida junto con una actualización maliciosa del router de acciones por parte del Safe sí podría vender acciones a un precio falsificado, porque la cuenta no puede verificar por sí misma la firma de cotización de Ondo. Una clave de operador de compras comprometida queda acotada por el tope de compras firmado por cada titular (en el peor caso, cerca del doble del tope alrededor del cambio de período), la lista de spenders permitidos del Safe y su pausa de tarjeta. El firmante de pedidos del escrow de Comprar tiene su propia clave, separada de la del árbitro y la del relayer.

Los cambios de v2 recibieron una revisión independiente interna el 25 de noviembre de 2026, antes de su puesta en marcha. Sus hallazgos se corrigieron y cada prueba de concepto se conserva como prueba de regresión en Foundry que comprueba que el ataque ya falla; entre ellas, las ventas ahora cuentan en el tope al valor del feed, y los dólares recibidos por una venta de acciones se ajustan al valor de la cotización incluso si se reemplazara el router. No fue una auditoría externa realizada por una firma de seguridad. <sup>[27]</sup>

## 5. Por qué se puede confiar en que una IA pague: la base de BNB Smart Chain

Un asistente es tan confiable como el sistema de dinero que tiene debajo. La base de Confío se construyó para que el asistente nunca necesite custodia: la clave del usuario permanece en su dispositivo, los activos viven en contratos con reglas públicas y el servidor solo puede preparar llamadas que el usuario —o la propia cuenta del usuario, dentro de límites firmados— ejecuta.

| Acción del usuario | Activo o contrato | Qué ocurre on-chain |
| --- | --- | --- |
| Agregar dólares | cUSD o cUSD+ | Un proveedor fiat o una billetera externa entrega BSC-USDT. La app lo convierte automáticamente en cUSD para un usuario no elegible según Ondo o en cUSD+ para un usuario elegible, cobrando la comisión de conversión de Confío del 0.9%. |
| Ahorrar | Frontera del wrapper cUSD↔cUSD+ | Los usuarios elegibles pueden pasar cUSD a cUSD+ respaldado por USDY sin comisión de conversión; la conversión interna inversa también es gratuita. Ambas rutas requieren una transacción patrocinada por Confío. |
| Enviar | cUSD o cUSD+ | Las transferencias entre el mismo activo se mantienen en el activo del remitente; las transferencias entre amigos con distinta elegibilidad se convierten internamente sin comisión. |
| Pagar por un canal local | cUSD o cUSD+ → USDT → moneda local | El dólar sale por la salida del 0.9% de cUSD y un proveedor paga el monto local exacto. |
| Pagar a un comercio | cUSD+, cUSD o $CONFIO | El contrato de pagos le paga al comercio, aplica la comisión independiente de Pay del 0.9% y registra on-chain las comisiones acumuladas. |
| Pagar nóminas | cUSD+ o cUSD | Las empresas fondean un escrow separado por activo; delegados autorizados firman los pagos. |
| Operar acciones, oro o bitcoin | Router de acciones o router de swaps | Una transacción patrocinada liquida y entrega el activo directamente a la billetera del usuario o a su Cuenta inteligente; las ventas vuelven al dólar del usuario. |
| Comprar en Comprar | Escrow de Comprar | Los dólares del comprador se retienen por pedido hasta que se confirma la entrega o se resuelve una disputa. |
| Automatizar o delegar | Cuenta inteligente | El contrato de la cuenta aplica las reglas y los topes que el titular firmó. |

### 5.1 Despliegues públicos en BNB Smart Chain

Todos los contratos que se listan abajo están activos en la red principal de BNB Smart Chain y tienen su código fuente verificado en BscScan (los proxies están vinculados a sus implementaciones verificadas). Los contratos actualizables son propiedad del Safe de 3 de 5 `0xF29A418744E793973BF4eEc676F8a30B2793b623`.

| Contrato | Dirección |
| --- | --- |
| Proxy del vault cUSD | [`0x6101cC370635cF2c7f2725EaB010aC407A8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| Proxy del vault cUSD+ | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Router de Ondo Stocks (proxy UUPS) | [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| Router de swaps de oro y bitcoin, `ConfioSwapRouter` (proxy) | [`0xA7C27684aB38eC369cB1F4474f279ea503dbF712`](https://bscscan.com/address/0xA7C27684aB38eC369cB1F4474f279ea503dbF712#code) |
| Delegado de lotes patrocinados | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| Factory de Cuenta inteligente (proxy UUPS) | [`0x339094A17605B842e0b2fc01441204E67020f953`](https://bscscan.com/address/0x339094A17605B842e0b2fc01441204E67020f953#code) |
| Implementación de cuenta v2 de Cuenta inteligente, `ConfioSmartAccountV2` | [`0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7`](https://bscscan.com/address/0x0b3DAf407AF2cF5bC7a1475bF44bD3952533cdF7#code) |
| Implementación de cuenta v1 de Cuenta inteligente | [`0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A`](https://bscscan.com/address/0x8a20a0B3d2C0c6BED8BeB00bB6Bc7AE3c7ace44A#code) |
| Recaudador de tarifas de Cuenta inteligente | [`0x1AE0ACB82bAb9F506188c49305953CB655A539CD`](https://bscscan.com/address/0x1AE0ACB82bAb9F506188c49305953CB655A539CD#code) |
| Spender de compras, `ConfioPurchaseSpender` | [`0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca`](https://bscscan.com/address/0xD0ea8Ec3a6F3AD49f13a18Ce801C9594311A32Ca#code) |
| Escrow de Comprar, `ConfioMarketEscrow` (proxy UUPS) | [`0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd`](https://bscscan.com/address/0x2DFDC1fB809322c12f54beFE8CC98E0d103a99Fd#code) |
| Heartbeat de salida de emergencia, `ConfioHeartbeat` (proxy) | [`0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF`](https://bscscan.com/address/0xAE49E3AD57531974CD2AEc2633b03770fF4a20FF#code) |
| Token $CONFIO | [`0xF5765933764562A51e179F6AF2b19b7a3d506101`](https://bscscan.com/token/0xF5765933764562A51e179F6AF2b19b7a3d506101) |
| Vault de preventa $CONFIO | [`0xB13Cda84348609c534aD1eFA9D4D39a62b2F18b4`](https://bscscan.com/address/0xB13Cda84348609c534aD1eFA9D4D39a62b2F18b4#code) |
| Vault de recompensas $CONFIO | [`0x3E022ADD4b3ae8618e431D83004e2aeb5F76AA49`](https://bscscan.com/address/0x3E022ADD4b3ae8618e431D83004e2aeb5F76AA49#code) |
| Vault de vesting $CONFIO | [`0x873A68182A384DD84385C7B610Df5D2A3746D75a`](https://bscscan.com/address/0x873A68182A384DD84385C7B610Df5D2A3746D75a#code) |
| Escrow de invitaciones | [`0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Contrato de pagos a comercios | [`0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Vault de nóminas | [`0x851e1a56De5c0ADBB75e904B2E7325e132692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |

**Cambios desde la versión 4.4.** Todos realizados a través del Safe y registrados en los registros públicos de despliegue: <sup>[8, 27]</sup>

- 9 de noviembre de 2026: el router v3 de Ondo Stocks eliminó la vía transitoria de comisión del 0.30% (sección 7.4).
- 21–22 de noviembre de 2026: se desplegaron la factory de Cuenta inteligente, la implementación de cuenta v1 y el recaudador de tarifas; se actualizó cUSD para que las cuentas de la factory puedan activar la comisión por referido; se habilitó la herencia (en un solo sentido).
- 25 de noviembre de 2026: se desplegó `ConfioSmartAccountV2`; se actualizó el proxy de la factory (implementación por generación, `migrate()`, `tradePaused`); se actualizó el proxy del escrow de Comprar (`depositFrom` con una firma vinculada al pagador, reembolsos a la cuenta que pagó; el firmante de pedidos pasó a tener su propia clave, mientras que el árbitro sigue siendo el patrocinador); se desplegó `ConfioPurchaseSpender` y se agregó a la lista permitida; se reanudaron las operaciones automáticas tras una migración canario de una cuenta del fundador.

### 5.2 Por qué importa una sola red

- no se necesita ningún puente entre el saldo principal en dólares, el ahorro, los pagos, las nóminas, Cuenta inteligente, la inversión y $CONFIO;
- una sola dirección EVM puede recibir el fondeo del usuario, los saldos de los productos y el token del ecosistema; y
- un solo sistema de transacciones patrocinadas puede pagar las comisiones de red en todo el producto, de modo que el asistente nunca tiene que pedirle a una persona que compre gas.

Los usuarios siguen sujetos a la elegibilidad de cada producto y a las reglas de cada proveedor. Una cadena unificada no hace que todos los activos sean económica o jurídicamente idénticos.

### 5.3 Por qué BNB Smart Chain

**El producto siguió la infraestructura de Ondo.** cUSD+ se diseñó en torno a USDY, y Ondo desplegó en BNB Smart Chain el token USDY de producción, InstantManager, el oráculo de precios, la ruta de suscripción y redención en USDT y la infraestructura de liquidación de Global Markets. Mantener el sistema de productos de Confío junto a esa infraestructura ofrece rutas directas al ahorro respaldado por USDY y al acceso elegible a Ondo Stocks. <sup>[7, 8, 10, 18]</sup>

**Economía y liquidez a escala de consumo.** BNB Smart Chain aporta amplia liquidez de USDT, bajos costos de transacción adecuados para actividad de consumo patrocinada, billeteras, proveedores RPC, exploradores y herramientas de desarrollo maduros, y un mismo entorno para todos los contratos de Confío. <sup>[5, 6, 12]</sup> El tamaño del ecosistema de una cadena no crea demanda de producto por sí solo.

**Contrapartidas.** BNB Smart Chain tiene características de descentralización y operación diferentes de las de otras redes. Siguen siendo posibles interrupciones de la red, coordinación de validadores, congestión, cambios en el precio del gas, fallas de RPC o cambios de políticas a nivel del ecosistema. Confío mitiga estos riesgos con transacciones patrocinadas, múltiples rutas RPC, salidas de emergencia explícitas, propiedad no custodial y estado público de los contratos, pero no puede eliminar el riesgo de la red base.

## 6. cUSD y cUSD+: dinero y ahorro

cUSD es el dólar universal para pagos, respaldado 1:1 por USDT en su vault UUPS desplegado. cUSD+ es una participación de ahorro acumulativa denominada en dólares, respaldada por USDY en el proxy cUSD+ existente y actualizado. La app selecciona cUSD para los usuarios que no son elegibles para exposición a USDY y cUSD+ para los usuarios elegibles, y cada usuario tiene uno u otro, nunca ambos, presentado como un único saldo en dólares.

### 6.1 Flujo de depósito y redención

| Entrada | Salida |
| --- | --- |
| 1. El USDT llega a la dirección BSC del usuario desde una rampa o una billetera externa. | 1. El usuario solicita un retiro en moneda local, un pago por canal local o un envío de USDT al exterior. |
| 2. Un lote patrocinado autorizado por el usuario llama a la ruta de acuñación con comisión que corresponda. | 2. Se quema cUSD directamente, o se quema cUSD+ y se redime USDY mediante InstantManager. |
| 3. El perímetro de comisiones de cUSD retiene el 0.9% y acuña cUSD, o devuelve el USDT neto a cUSD+ para suscribir USDY. | 3. El perímetro de comisiones de cUSD retiene el 0.9% del valor bruto de salida. |
| 4. El usuario recibe cUSD si no es elegible según Ondo, o cUSD+ si lo es. | 4. El USDT neto va a la billetera externa o a la dirección de la rampa designada. |

El vault cUSD es el único perímetro externo de comisión de conversión. Su comisión está limitada en el código a 90 puntos básicos. La acuñación siempre requiere un patrocinador autorizado; la redención sin comisión está restringida a la frontera de ahorro de cUSD+; la redención ordinaria con comisión sigue sin requerir permisos, para que un titular pueda salir sin el patrocinador de Confío. cUSD+ sigue el mismo principio de salida.

El comprador autorizado de USDY es el vault cUSD+, no el usuario final. Los usuarios tienen cUSD+, no USDY directamente. La conversión interna cUSD↔cUSD+ no tiene comisión solo porque el valor permanece dentro del sistema de dólares de Confío; no crea una ruta externa gratuita hacia USDT.

### 6.2 Valor acumulativo y participación en el rendimiento

El precio de referencia de USDY está diseñado para apreciarse a medida que se acumula el rendimiento subyacente. En cada interacción pertinente, el vault actualiza el valor de referencia de cUSD+: el 85% de la apreciación positiva del precio de referencia de USDY incrementa el valor de referencia para el titular de cUSD+, y el 15% se convierte en excedente del vault disponible para Confío. El número de participaciones no aumenta; lo que sube es el valor de referencia en dólares por participación. El rendimiento es variable, puede cambiar y no está garantizado. <sup>[7, 11]</sup>

### 6.3 Respaldo y controles del oráculo

El vault expone consultas públicas de obligaciones totales, ratio de respaldo y excedente. Su contabilidad redondea a favor del respaldo y restringe el cobro de comisiones al excedente demostrable. El propietario no puede retirar el USDY de respaldo. Si el oráculo de USDY baja o se mueve más allá de un umbral de protección configurado, las rutas que mueven valor se detienen, y la gobernanza multiparte debe registrar una decisión vinculada a evidencia antes de que se reanuden. Esto reduce el riesgo de precios erróneos automáticos, pero no puede eliminar los riesgos de oráculo, emisor o gobernanza.

## 7. Pagos, nóminas, inversión y Comprar

### 7.1 Transferencias entre personas

El servidor prepara las llamadas exactas, el usuario las firma y Confío patrocina el gas de la red. cUSD+ se transfiere directamente a un destinatario elegible, cUSD a un destinatario que debe tener cUSD, y una conversión sin comisión autorizada por el patrocinador cruza la frontera de elegibilidad. Confío no cobra comisión de plataforma en las transferencias entre personas; la comisión de conversión del 0.9% solo se aplica cuando el valor entra desde USDT o sale hacia USDT.

### 7.2 Pagos a comercios

Un comercio cobra en **dólares Confío** o en **$CONFIO**. El contrato de pagos calcula la comisión comercial del 0.9%, le paga directamente al comercio el monto neto y acumula solo las comisiones devengadas. El backend de Confío firma una autorización de corta vigencia sobre las condiciones exactas del pago; exactamente un pago puede liquidar una factura, y cada factura registra la única red permitida para liquidarla. El USDT sin convertir sigue siendo un token heredado de la lista permitida que el backend de producción no autoriza, de modo que Pay no puede convertirse en una ruta para eludir la comisión de conversión.

### 7.3 Nóminas y pagos masivos

Las empresas pueden mantener capital de trabajo en cUSD+ o cUSD en un escrow separado por activo y autorizar delegados para firmar pagos específicos. Los destinatarios elegibles pueden recibir cUSD+; los no elegibles reciben cUSD mediante la frontera de conversión interna sin comisión. La contabilidad de comisiones de nómina se mantiene separada del principal de la empresa.

### 7.4 Ondo Stocks

Confío integra el acceso elegible a Ondo Stocks mediante Ondo Global Markets en BNB Smart Chain a través del proxy UUPS `ConfioStockRouter`, cuya autoridad de actualización la tiene el Safe de 3 de 5 que es su propietario. Una compra redime el cUSD+ autorizado a USDT por la salida ordinaria de cUSD+ (donde cUSD cobra la comisión del 0.9%), liquida la compra certificada y entrega el token de la acción directamente a la billetera del usuario o a su Cuenta inteligente; una venta devuelve los ingresos efectivos en USDT al dólar del usuario por su entrada ordinaria. El router no cobra comisión propia. Desde el router v3 (9 de noviembre de 2026) no tiene ninguna otra vía de comisión, una intención firmada con una comisión menor que la vigente de cUSD se revierte, y cualquier exceso de USDT de la liquidación se devuelve en lugar de retenerse. El acceso sigue sujeto a la elegibilidad de Ondo, la jurisdicción, la disponibilidad de mercados y los términos del proveedor. <sup>[17, 18]</sup>

### 7.5 Oro y Bitcoin

`ConfioSwapRouter` permite a un usuario comprar y vender tokens del catálogo —incluidos bitcoin (BTCB) y oro (XAUt)— con cualquiera de los dos dólares Confío dentro de un lote patrocinado. Las compras salen por la salida del 0.9% de cUSD e intercambian todo el USDT neto en PancakeSwap; las ventas vuelven a intercambiar a USDT y reingresan por la entrada del 0.9%, y el resultado se acuña directamente al usuario. El router no tiene comisión propia, no guarda nada en reposo, construye él mismo la llamada de swap con un destinatario fijo y solo acepta operaciones originadas por el relay de Confío dentro de un deslizamiento máximo respecto de una recotización en vivo. Oro y Bitcoin no se ofrece en la versión para iOS y está bloqueado en ciertos países. <sup>[30]</sup>

### 7.6 Futuros

Futuros da a los usuarios elegibles de Android acceso a futuros perpetuos en Hyperliquid. El dinero se mueve entre el dólar del usuario y Hyperliquid mediante el puente de Relay; la comisión de perímetro del 0.9% se aplica en cada apertura, cierre o aporte de margen, y Confío no cobra una comisión de builder aparte. La app verifica cada orden de puente y cada firma que se le pide hacer, en lugar de confiar en el servidor. Futuros no se ofrece en la versión para iOS, está bloqueado en Estados Unidos, Canadá, el Reino Unido y Bélgica, y conlleva los altos riesgos del trading apalancado, incluida la pérdida rápida y total del margen. <sup>[3]</sup>

### 7.7 Marketplace Comprar

Comprar es un marketplace dentro de la app para bienes físicos, que empieza por Bolivia, en el que tanto compradores como vendedores pasan la verificación de identidad de Didit. Las compras se liquidan mediante el `ConfioMarketEscrow` compartido: los dólares del comprador se retienen por pedido; el vendedor tiene un plazo para enviar; el comprador puede confirmar la entrega, abrir una disputa o recuperar los fondos cuando vence un plazo; las disputas las resuelve un árbitro. Los vendedores pagan una comisión de marketplace del 8%. Comprar está en un piloto temprano con muy pocas tiendas y pedidos. <sup>[3]</sup>

## 8. $CONFIO en BNB Smart Chain

$CONFIO es el token comunitario y del ecosistema de Confío. No es una stablecoin, no representa un depósito bancario y no respalda USDT, cUSD+ ni USDY.

### 8.1 Token de oferta fija

El contrato actual del token en BNB Smart Chain tiene una oferta inicial fija de 1,000,000,000 CONFIO. El contrato no tiene función de acuñación posterior al despliegue, ni pausa global, ni vía de actualización; toda la oferta inicial se creó una sola vez en el despliegue, a favor de la tesorería multiparte. La oferta total puede disminuir mediante quema voluntaria, pero no puede aumentar. La tesorería multiparte puede congelar una dirección durante un incidente de seguridad grave y, tras una espera pública de 7 días, devolver un saldo congelado a la parte a la que se le robó; esto no crea tokens. <sup>[17]</sup>

**Contrato BSC canónico:** [`0xF5765933764562A51e179F6AF2b19b7a3d506101`](https://bscscan.com/token/0xF5765933764562A51e179F6AF2b19b7a3d506101)

El nombre on-chain del token es deliberadamente el ASCII **“Confio”**, mientras que **“Confío”**, con tilde, sigue siendo el nombre del producto y de la marca. Los lectores deben usar únicamente la dirección canónica anterior. La asignación, la propiedad del fundador, el vesting, los derechos de preventa y los riesgos de concentración se divulgan en el documento autoritativo de tokenomics en inglés, que es independiente.

### 8.2 Preventa on-chain

El vault BSC de preventa de reemplazo acepta cUSD y calcula el precio de las compras con una curva lineal por tramos, inmutable y vinculada a los tokens vendidos acumulados:

| Asignación acumulada de preventa | Precio de la curva |
| --- | --- |
| 0–4 millones de CONFIO | US$0.20 → US$0.30 |
| 4–24 millones de CONFIO | US$0.30 → US$0.70 |
| 24–74 millones de CONFIO | US$0.70 → US$1.30 |

Los tramos de la curva no tienen ninguna función administrativa para cambiar precios. El contrato cobra la integral bajo la curva, registra la asignación, impide descuentos por dividir compras mediante su matemática de precios y abre los reclamos solo cuando hay suficiente fondeo de CONFIO. Se inicializó con el historial exacto de compras previo al despliegue y está fondeado para la obligación de reclamos migrada; el vault reemplazado está pausado. La participación sigue sujeta a elegibilidad, controles geográficos y los términos de la preventa. Los CONFIO de la preventa no pueden mantenerse en una Cuenta inteligente. <sup>[17]</sup>

### 8.3 Recompensas y reclamos bloqueados hasta el DEX

La acumulación de recompensas se registra en la base de datos de Confío y se convierte a CONFIO al precio vigente de la curva de preventa. Al reclamar, el firmante del backend emite una autorización EIP-712 de corta vigencia por el monto acumulado ganado por el usuario; el RewardVault paga solo la diferencia respecto de lo ya reclamado. Los reclamos están bloqueados hasta que la gobernanza llame a la función irreversible `unlockClaims()` en el lanzamiento en el DEX.

> **Pool de recompensas controlado por la tesorería**
>
> El RewardVault no es un escrow sin necesidad de confianza. Su propietario de gobernanza puede rotar el firmante, pausar los reclamos y retirar fondos, incluso después del desbloqueo en el DEX. Los usuarios dependen de que la tesorería concilie las obligaciones de la base de datos, fondee el pool y mantenga disponibles los reclamos válidos. Los plazos cortos de las firmas y un tope diario de reclamos limitan la exposición del firmante, pero no eliminan la confianza en la tesorería.

## 9. Billetera, seguridad y arquitectura de código abierto

### 9.1 Modelo de billetera no custodial

Confío genera la clave EVM del usuario en su dispositivo. El servidor de Confío no conserva esa clave privada. El material de recuperación cifrado está diseñado para la cuenta personal en la nube del usuario, de modo que la recuperación no requiere que Confío mantenga un repositorio central de claves de usuarios. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío nunca conserva la clave de la billetera del usuario, así que ni Confío ni su asistente pueden firmar una transacción ordinaria de la billetera como si fueran ese usuario. Lo que el asistente puede hacer sin una firma por acción se limita a una Cuenta inteligente que el usuario fondeó, bajo reglas y topes que el usuario firmó. Los contratos de producto y los activos emitidos siguen teniendo sus propios controles divulgados de elegibilidad, pausa, congelamiento, actualización o gobernanza. Claves no custodiales no significan productos financieros sin controles.

### 9.2 Transacciones patrocinadas

Los usuarios no necesitan adquirir BNB. Confío utiliza autorizaciones de usuario EIP-7702 y un delegado de lotes desplegado y sin propietario, de modo que el usuario firma las llamadas previstas mientras el patrocinador de Confío paga el gas. Las aprobaciones y las acciones se ejecutan de forma atómica, lo que reduce el riesgo de autorizaciones de gasto permanentes. La política del servidor restringe destinos, selectores, montos, destinatarios, vencimientos y límites diarios antes de transmitir. Las vías alternativas de emergencia y las salidas directas siguen siendo importantes porque el patrocinio es un servicio de la aplicación, no una garantía de la blockchain. <sup>[8, 17]</sup>

### 9.3 Salvaguardas del asistente en el código

La seguridad del asistente no descansa en un prompt. Las herramientas de dinero se delimitan por la sesión autenticada, nunca por un identificador de cuenta que aporte el modelo; los empleados de negocios no reciben herramientas de dinero; los montos provienen solo de una pregunta escrita por el código; los beneficiarios se validan con intérpretes específicos de cada canal; las confirmaciones las dibuja la app, no el modelo; la salida de herramientas y el contenido de las páginas se tratan como datos; el gasto, los pasos y el costo de modelo del agente de compras están limitados por el servidor; y los canales de cada país se activan o desactivan con interruptores que el modelo no puede cambiar. Los cambios en el asistente y en el agente de compras se prueban con conversaciones grabadas de varios turnos y con páginas reales de tiendas grabadas.

### 9.4 Código abierto y verificabilidad pública

La aplicación móvil, el backend, el asistente, el agente de compras, los contratos inteligentes, los registros de despliegue y las pruebas están disponibles públicamente. Los contratos desplegados tienen su código fuente verificado, lo que permite a los revisores comparar el código público con el bytecode activo. La seguridad se busca mediante pruebas unitarias, de fork, de invariantes/fuzz, adversariales y ensayos de actualización; registros públicos de despliegue; gobernanza multiparte; cobro acotado de comisiones y respaldo que no puede retirarse; protecciones de oráculo, pausas, protección contra reutilización y límites de deslizamiento; e indicadores de funcionalidad para el despliegue en producción. Ningún método de revisión elimina el riesgo de los contratos inteligentes ni el riesgo operativo. <sup>[3, 8, 9, 17, 27]</sup>

### 9.5 Actualización y gobernanza

| Componente | ¿Actualizable? | Por quién |
| --- | --- | --- |
| Vaults cUSD y cUSD+ | Sí (UUPS) | Safe de 3 de 5, con implementaciones públicas y verificaciones de disposición de almacenamiento |
| Router de acciones, router de swaps | Sí (proxies) | Safe de 3 de 5 |
| Factory de Cuenta inteligente | Sí (UUPS) | Safe de 3 de 5; puede agregar una nueva implementación de cuenta para cuentas nuevas o que migran y pausar las vías automáticas o de tarjeta, pero no puede cambiar una cuenta existente |
| Cuentas de Cuenta inteligente | No (clones inmutables) | Pasar a una nueva versión es un `migrate()` firmado por el titular |
| Escrow de Comprar, heartbeat | Sí (UUPS / proxy) | Safe de 3 de 5 |
| Spender de compras, recaudador de tarifas, delegado de lotes | No | Un nuevo operador implica un nuevo despliegue agregado a la lista permitida por el Safe |
| Token $CONFIO, curva de precios de la preventa | No | — |

Los vaults siguen siendo actualizables porque cUSD+ depende permanentemente de contratos externos de Ondo que pueden migrar o cambiar, y cUSD es el perímetro de comisiones compartido entre los contratos de producto. La consecuencia aceptada es el supuesto de confianza de la sección 4.3: las acciones automáticas confían en que el Safe no instale un router ni un escrow maliciosos.

## 10. Usuarios, distribución y entrada al mercado

### 10.1 Métricas operativas actuales

| Métrica | Instantánea | Fecha | Definición |
| --- | ---: | --- | --- |
| Usuarios con teléfono verificado | 10,233 | 25 nov 2026 | Usuarios que completaron la verificación telefónica. |
| Dispositivos alcanzables por push | 3,407 | 25 nov 2026 | Dispositivos actualmente accesibles mediante notificaciones push. |
| Utilizados en los últimos 30 días | 3,402 | 25 nov 2026 | Dispositivos alcanzables por push registrados como usados en los 30 días previos; no se presenta como una cifra estandarizada de MAU. |
| Usuarios verificados por Didit | 177 | 23 jul 2026 | Usuarios que presentaron un documento de identidad oficial y completaron la prueba de presencia real con selfie en vivo y la coincidencia facial. |
| Finalización de la verificación de identidad | 61.5% | 23 jul 2026 | Proporción de usuarios que completaron el flujo de Didit entre quienes lo iniciaron. |

Estas métricas internas no están auditadas. Desde finales de octubre de 2026, el registro ya no requiere un número de teléfono, por lo que el conteo de usuarios con teléfono verificado no incluye a todos los usuarios que terminaron el registro. Las métricas no implican que todos los usuarios tengan fondos, estén activos, sean elegibles para todos los productos o sean únicos entre todas las mediciones de dispositivos. <sup>[14]</sup>

### 10.2 La confianza es el canal de distribución

La audiencia en español liderada por el fundador de Confío suma aproximadamente 480,000 personas entre plataformas sociales. La ventaja estratégica no es solo la cifra de seguidores; es la capacidad de explicar productos financieros —y ahora un asistente que paga— de forma reiterada, pública y en el lenguaje cultural del usuario objetivo. <sup>[15]</sup>

> **Distribución + confianza + adaptación local**
>
> Confío no planea ganar superando permanentemente a sus competidores en cashback. Busca convertir una audiencia que confía en personas que dejan que el asistente pague por ellas una vez, y luego otra vez. La medida de éxito acordada para el asistente es la proporción de personas que le dejan pagar una vez y le dejan volver a pagar dentro de 30 días.

### 10.3 Despliegue país por país

Confío no ofrece todas las funciones en todos los países. Los métodos fiat, los requisitos de identidad, la elegibilidad para USDY, los controles de sanciones, las opciones de retiro, los canales del agente de compras y los procedimientos de soporte varían según el mercado, y los corredores se pausan cuando un proveedor o una señal de fraude lo exigen. El despliegue sigue las capacidades verificadas de los proveedores y la preparación jurídica y operativa, no una bandera de país en una página promocional.

## 11. Modelo de negocio

Confío vincula sus ingresos con actividad financiera útil, no con trading especulativo. El asistente que actúa por una persona se paga con Cuenta inteligente; mover dinero hacia dentro y hacia fuera del sistema de dólares se paga con la comisión de perímetro del 0.9%.

| Fuente de ingresos | Política actual |
| --- | --- |
| Cuenta inteligente | US$149.99 al año (predeterminado) o US$14.99 al mes, cobrados desde dentro de la cuenta; sin reembolsos. Incluye la automatización, el beneficiario y Confío IA+ (el asistente ejecutando sobre la cuenta, operaciones automáticas dentro del tope semanal y compras en tiendas dentro del tope de compras). |
| Entrada al sistema de dólares Confío | 0.9% cuando el USDT se convierte en cUSD o cUSD+, desde una rampa fiat o una transferencia on-chain. |
| Salida del sistema de dólares Confío | 0.9% cuando cUSD o cUSD+ se convierte en USDT externo, incluidos los pagos por canal local y las compras del asistente pagadas desde una Cuenta inteligente. |
| Transferencias y conversión interna de ahorro | 0% de comisión de Confío; las comisiones de red están patrocinadas. |
| Pagos a comercios y nóminas | Comisión plana de plataforma de Confío del 0.9%, aplicada on-chain. |
| Comprar | Comisión de marketplace del 8% pagada por el vendedor. |
| Participación en el rendimiento de cUSD+ | 15% de la apreciación positiva del precio de referencia de USDY para Confío y 85% para los titulares. Variable y no garantizada. |
| Ondo Stocks, Oro y Bitcoin, Futuros | La comisión uniforme de perímetro del 0.9% cuando el valor sale del dólar o vuelve a entrar; sin comisión aparte de trading ni de builder. Pueden aplicarse por separado diferenciales de terceros y costos de puente, de la plataforma de ejecución y de la red. |
| Economía de los canales fiat | Los precios del proveedor y cualquier tarifa de cuenta local se muestran en la cotización en vivo. |

La regla de precios es la misma que se muestra en el sitio web público: **0.9% para entrar, 0% para moverse dentro y 0.9% para salir**. Confío Pay tiene una comisión de servicio independiente del 0.9%. Cuenta inteligente no exime ni descuenta la comisión del 0.9%. La búsqueda, los carritos y las revisiones con precio del agente de compras, así como las respuestas de Confío IA, son gratuitos. El patrocinio de la red y el uso de modelos son costos del producto, no prueba de que toda acción sea económicamente gratuita.

## 12. Cumplimiento y modelo operativo

La arquitectura de Confío separa la custodia de las claves de la billetera de las obligaciones de producto y de proveedor. Una billetera no custodial puede igualmente integrar activos con permisos, verificación de identidad, controles de sanciones, proveedores fiat y controles contractuales.

**Conoce a tu cliente (KYC, Know Your Customer)** comprende las verificaciones utilizadas para establecer quién es un usuario y, cuando se requiere, dónde reside. **Prevención del lavado de dinero (AML, Anti-Money Laundering)** comprende los controles de proveedores y de transacciones destinados a detectar o prevenir infracciones de sanciones, fraude, lavado de dinero, financiamiento del terrorismo y otras actividades prohibidas.

> **Arquitectura integrada con proveedores**
>
> La custodia fiat, la conversión de moneda, la verificación de identidad y el acceso a activos con permisos los realizan los proveedores correspondientes, no el software de billetera de Confío. Esto describe el diseño operativo; no afirma que Confío carezca de obligaciones legales o de cumplimiento.

- Didit respalda el flujo de verificación de identidad: un documento oficial y una selfie en vivo, con comprobaciones del documento, de presencia real y de coincidencia facial. Los usuarios menores de 18 años son rechazados.
- Los proveedores fiat aplican sus propios controles de identidad, domicilio, elegibilidad, sanciones y transacciones; completar la verificación de Didit no garantiza por sí solo la aprobación de un proveedor.
- La acuñación de USDY y el acceso a Ondo Stocks están limitados por los requisitos de elegibilidad, geográficos y de cumplimiento de Ondo. <sup>[7, 10, 18]</sup>
- El beneficiario de una Cuenta inteligente debe ser un usuario de Confío verificado por Didit, designado solo a través del control del patrocinador de Confío, y debe aceptar; los beneficiarios residentes en Estados Unidos están bloqueados.
- Comprar requiere la verificación de Didit tanto para compradores como para vendedores.
- El agente de compras nunca elude un bloqueo de un sitio y rechaza los países sin un canal que pague el monto exacto del pedido.
- Los países y canales adicionales se lanzan solo después de las verificaciones legales, operativas y de proveedor correspondientes.

## 13. Riesgos y mitigaciones

Ningún producto financiero blockchain, y ningún agente de IA, está libre de riesgos. Esta tabla no es exhaustiva.

| Riesgo | Mitigación actual | Exposición residual |
| --- | --- | --- |
| **Malentendido o error del modelo de IA** | Los modelos proponen; el código pregunta los montos, valida a los beneficiarios, calcula precios y dibuja la confirmación; el texto de herramientas y páginas son datos, no instrucciones; el comportamiento se prueba con conversaciones grabadas. | Un modelo todavía puede interpretar mal una solicitud, elegir el producto equivocado o dar una respuesta incorrecta; una persona puede confirmar una tarjeta sin leerla. |
| **Compra en tienda equivocada o fallida** | Elegir aprueba un total máximo; un total real más alto hace volver la tarjeta de pedido; dos modelos deben leer el mismo total, que debe aparecer en la página; una aprobación genera un solo pedido; límites del servidor en pasos, tiempo y costo; compras pagadas desde una regla de cuenta con tope. | Las tiendas cambian sus páginas, cancelan pedidos, envían mal o retrasan reembolsos; una falla del lado de la tienda puede obligar a la persona a tratar con la tienda. El agente está en una etapa temprana y todavía no está probado en muchas tiendas. |
| **Errores en pagos por canal local** | Identificadores validados con suma de verificación, cotizaciones por monto exacto, seguimiento del estado del proveedor, ningún “pagado” antes de que el canal lo confirme. | Los proveedores pueden fallar, retrasarse, revertir o pausar; un beneficiario de tienda no verificado leído de un checkout todavía puede ser incorrecto. |
| **Confianza en la ejecución automática y en la cuenta inteligente** | Cuentas inmutables; topes firmados por el titular aplicados on-chain; compras y ventas contabilizadas; bandas de feed de precios; límite de comisión; notificaciones y alertas; interruptores de emergencia del Safe; clave separada para el firmante de pedidos del escrow; revisión independiente interna con pruebas de regresión. | Las acciones automáticas confían en routers y en un escrow actualizables por el Safe; un relayer comprometido junto con una actualización maliciosa del Safe podría vender acciones a un precio falsificado; un operador de compras comprometido queda acotado por el tope de cada titular. Las reglas se ejecutan tal como se firmaron, aunque el titular después se arrepienta. |
| **Activos subyacentes y emisores** | cUSD está respaldado por USDT; cUSD+ mantiene USDY; divulgación de estructura, contabilidad y elegibilidad. | Persisten riesgos de pérdida de paridad, emisor, custodia, legales, de reservas y de redención para USDY y USDT. |
| **Contratos inteligentes** | Código abierto, despliegues verificados, pruebas por capas, controles acotados y estado público. | Siguen siendo posibles defectos, fallas de integración y errores de actualización. |
| **Oráculo** | La protección por umbral detiene las rutas de valor a la espera de una respuesta de gobernanza vinculada a evidencia. | Datos incorrectos o no disponibles pueden retrasar depósitos y redenciones. |
| **Liquidez y redención** | Redención a USDT con comisión y sin permisos; Emergency Exit puede transmitir directamente a través de nodos BSC públicos. | La liquidez de InstantManager, la disponibilidad de proveedores, las condiciones de la red o medidas de cumplimiento pueden retrasar las salidas. |
| **Inversión y apalancamiento** | Routers con código fuente verificado, entrega directa al usuario, límites de comisión, límites de deslizamiento, filtros de elegibilidad y de país; Futuros no se ofrece en iOS y está bloqueado en varios países. | Persisten riesgos de mercado, deslizamiento, emisor, plataforma de ejecución, puente, liquidación y pérdida total, especialmente en Futuros apalancados. |
| **Recuperación de claves** | Las claves generadas en el dispositivo y la recuperación en la nube personal evitan un repositorio central de claves. | La pérdida de acceso al dispositivo o a la nube, cambios de plataforma o defectos de recuperación pueden afectar el acceso. |
| **Gobernanza de actualizaciones** | Control multiparte mediante el Safe, registros públicos de actualizaciones, verificación de código fuente, verificaciones de disposición de almacenamiento. | Los firmantes autorizados podrían hacer un cambio perjudicial o no responder durante un incidente. |
| **Dependencia de BNB Smart Chain** | La arquitectura de una sola red elimina el riesgo de puente dentro del producto principal; múltiples rutas RPC y de salida de emergencia. | Interrupciones de la red, congestión, fallas de RPC, cambios de gas o cambios de políticas del ecosistema pueden afectar a todo el producto. |
| **Canales fiat y corredores pausados** | Interruptores en vivo por país y por proveedor; corredores pausados ante incidentes del proveedor o señales de fraude (la recarga en Colombia y Bre-B están pausados a la fecha de esta versión). | La cobertura, los métodos de pago, las dependencias bancarias, los precios y la disponibilidad de proveedores pueden cambiar sin previo aviso. |
| **Regulación y delitos financieros** | Verificaciones con documento oficial y selfie en vivo, controles de los proveedores, restricciones geográficas de productos, revisión jurídica y bloqueo de cuentas abusivas. | Los proveedores o las autoridades pueden rechazar, retrasar, reportar o restringir actividad; las reglas para agentes de IA que actúan sobre pagos todavía están en desarrollo. |
| **Concentración del token y recompensas** | Oferta fija, contratos públicos, curva de preventa inmutable, tokenomics separado; reclamos de recompensas EIP-712 acumulativos con bloqueo hasta el DEX. | Concentración del fundador, vesting, liquidez y volatilidad del precio del token; las recompensas dependen del fondeo de la tesorería. |
| **Métricas y concentración** | Se divulgan definiciones, fechas de las instantáneas y su carácter no auditado. | El uso y los ingresos iniciales pueden estar concentrados y no predecir una adopción amplia. |

## 14. Hoja de ruta y estado actual

| Área de trabajo | Completado / actual | Próximo hito verificable |
| --- | --- | --- |
| Confío IA | Inicio y alta centrados en el chat; tarjetas de pago, operación y recarga en el chat con montos preguntados por el código; puertas a cada tarea de la app; memoria y compactación de conversaciones. | Medir quiénes repiten pagos con el asistente; completar la revisión independiente pendiente de los pagos por chat. |
| Agente de compras | Compras desde navegador en la nube con modelos jueces y hechos verificados por el código; búsqueda en varias tiendas; pagos por SPEI, Pix y Pago Móvil; Bolivia con la persona pagando el QR de la tienda. | Compras completadas de forma confiable en más tiendas; pagos por monto exacto para el QR fijo de Argentina. |
| Cuenta inteligente | Factory, cuentas v1 y v2, recaudador de tarifas y spender de compras desplegados y verificados; herencia habilitada; operaciones automáticas, Comprar y compras en tiendas activas desde el 25 de noviembre de 2026. | Trasladar las reglas de envío, de pago y de tarjeta a través de la migración; aumentar los suscriptores de pago. |
| Sistema de comisiones cUSD/cUSD+ | Perímetro externo de 90 puntos básicos y frontera interna sin comisión activos. | Supervisar la conciliación de comisiones, el respaldo, el enrutamiento por elegibilidad y las salidas sin permisos. |
| Transacciones patrocinadas | Delegado de lotes EIP-7702 sin propietario, política del servidor y registros contables activos. | Supervisar la fiabilidad, el costo del patrocinador y las alternativas de emergencia. |
| Pagos y nóminas | Transferencias, pagos a comercios, escrow de invitaciones y vault de nóminas activos. | Medir el uso repetido de pagos a comercios y nóminas. |
| Inversión | Router v3 de Ondo Stocks, router de swaps para oro y bitcoin, Futuros en Android. | Se necesita revisión jurídica para ofrecer Oro y Bitcoin y Futuros en una versión para iOS. |
| Comprar | Escrow actualizado para compras desde la cuenta; piloto abierto. | Vendedores y compradores recurrentes en las ciudades del piloto. |
| Acceso fiat | Canales locales activos en México, Brasil, Venezuela, Bolivia, Argentina, Chile y Perú según se describe en la sección 3.6; Colombia pausada. | Reabrir Colombia cuando los proveedores lo permitan; pagos QR en Bolivia; proveedores verificados adicionales. |
| $CONFIO | Token de oferta fija, preventa de reemplazo y vaults de recompensas y vesting activos. | Mantener el tokenomics sincronizado con el estado on-chain; abrir los reclamos solo bajo los controles divulgados. |
| Distribución | 10,233 usuarios con teléfono verificado; audiencia del fundador de aproximadamente 480,000 personas; gasto en medios pagados prácticamente nulo hasta la fecha. | Convertir la distribución en usuarios con fondos, pagos repetidos con el asistente y cohortes por país. |

### 14.1 Principios de medición

Confío distingue registros, usuarios que completaron el alta, usuarios verificados, usuarios con fondos, dispositivos alcanzables, usuarios activos y saldos retenidos. Las medidas operativas centrales incluyen usuarios con fondos, personas que repiten pagos con el asistente, compras del agente completadas y fallidas, suscriptores de Cuenta inteligente, obligaciones de cUSD y cUSD+, respaldo, comisiones de conversión, entrada neta, retención de saldos, volumen de pagos a comercios y de nóminas, y cohortes por país. La adquisición orgánica se separa de las campañas pagadas, y los ingresos se reportan excluyendo las cuentas bloqueadas y las del fundador.

### 14.2 La siguiente prueba

> **De un asistente que puede pagar a uno en el que la gente confía para volver a pagar**
>
> La siguiente prueba es el uso repetido: personas que dejan que Confío IA le pague a una persona, un QR o una tienda una vez y lo vuelven a hacer dentro de 30 días, con saldos fondeados y suscriptores de pago de Cuenta inteligente en varios mercados latinoamericanos.

## 15. Aviso legal

Este documento se ofrece únicamente con fines informativos y de referencia técnica. No constituye asesoría de inversión, jurídica, fiscal, contable ni financiera; no es un prospecto, una oferta, una solicitud, una recomendación ni una promesa de rendimientos. Las descripciones de los productos reflejan el diseño y el estado actuales al 25 de noviembre de 2026 y pueden cambiar.

Confío IA es un asistente automatizado. Sus respuestas pueden ser incompletas o incorrectas y no constituyen asesoría financiera personalizada. Las compras realizadas por el agente de compras son contratos entre la persona y la tienda; Confío no garantiza los productos, la entrega, las devoluciones ni los reembolsos de una tienda. Las acciones ejecutadas por una Cuenta inteligente siguen las reglas y los topes que firmó su titular.

USDT, cUSD y cUSD+ no son depósitos bancarios y no están cubiertos por un seguro de depósitos. Las stablecoins, los títulos tokenizados, los contratos inteligentes, las blockchains, los oráculos, los proveedores fiat, los creadores de mercado, los custodios y otras infraestructuras pueden fallar, suspenderse, perder valor o quedar sujetos a nuevas reglas.

Cualquier rendimiento de cUSD+ es variable, depende de USDY y del vault, y no está garantizado. El acceso a USDY y la acuñación de cUSD+ están sujetos a la elegibilidad de Ondo, a condiciones de cumplimiento, a la disponibilidad de proveedores y a la ley aplicable.

Ondo Stocks son instrumentos financieros tokenizados y no son depósitos bancarios ni productos de ahorro asegurados. Los tokens de oro y bitcoin y los futuros perpetuos apalancados pueden perder valor rápidamente, y en Futuros se puede perder todo el margen. El acceso y la negociación dependen de la elegibilidad, la jurisdicción, la disponibilidad de mercados, plataformas de terceros y los términos y leyes aplicables.

$CONFIO es independiente de USDT, cUSD, cUSD+ y USDY. No otorga ningún derecho sobre el respaldo, los ingresos, el capital social, los activos o los beneficios de Confío, salvo que términos definitivos dispongan expresamente lo contrario.

Antes de usar cualquier servicio, los lectores deben revisar los términos definitivos de los productos, las divulgaciones de riesgos, los contratos inteligentes, los términos de los proveedores y la legislación local.

## Notas

1. Banco Interamericano de Desarrollo, “Remittances to Latin America and the Caribbean Ease After 2025 Surge”, 16 de junio de 2026: remesas regionales estimadas en US$173.7 mil millones en 2025, 7.3% más que en 2024. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth”, 2 de octubre de 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

3. Repositorio público de Confío en GitHub: aplicación móvil, backend, asistente (`assistant/`), agente de compras (`agent_tasks/`), marketplace, contratos BSC, modelo de billetera, pagos, nóminas, token y preventa. https://github.com/caesar4321/Confio

4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa”, fuente del proyecto, consultada en julio de 2026.

5. Documentación para desarrolladores de BNB Chain: introducción a BNB Smart Chain y finalidad. https://docs.bnbchain.org/bnb-smart-chain/introduction/

6. Documentación para desarrolladores de BNB Chain: comisiones de transacción y conceptos de red. https://docs.bnbchain.org/bnb-smart-chain/

7. Documentación de Ondo Finance, “USDY Basics”, consultada en julio de 2026. https://docs.ondo.finance/general-access-products/usdy/basics

8. Confío, “cUSD+ deployment record - BSC mainnet”, actualizado en noviembre de 2026: despliegues de cUSD, cUSD+, el router de acciones, Cuenta inteligente, el heartbeat y el escrow de Comprar. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

9. BscScan, proxy ERC1967 de Confío Dollar+, dirección `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

10. Documentación para desarrolladores de Ondo Finance, “Integrating with the USDY InstantManager contract”. https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

11. Confío, `CusdPlusVault.sol`: contabilidad desplegada, redención, protección del oráculo y lógica de participación de Confío del 15% en el rendimiento. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

12. Documentación del ecosistema y para desarrolladores de BNB Chain, consultada en julio de 2026. https://www.bnbchain.org/en/developers

13. Registros de socios y configuración de producción de Confío, 25 de noviembre de 2026: canales locales de recarga, retiro y pago a través de Koywe, Infinia, Pago ASAP y VEXPay, con interruptores y pausas por país. Las condiciones comerciales se rigen por los respectivos acuerdos.

14. Instantáneas de analítica interna de producto de Confío: 25 de noviembre de 2026 para usuarios con teléfono verificado y dispositivos alcanzables por push mediante FCM (tokens de dispositivo activos; usados dentro de 30 días según el último uso registrado); 23 de julio de 2026 para la verificación de identidad de Didit con documento oficial y selfie en vivo y su tasa de finalización. No auditadas.

15. Instantánea de analítica interna del canal del fundador de Confío, 23 de julio de 2026. La cifra de audiencia es aproximada y cambia con el tiempo.

16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps”, *Forbes Technology Council*, 6 de julio de 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/

17. Contratos BSC y registros de despliegue de Confío: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol` y direcciones de despliegue verificadas. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus y https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks

18. Ondo Finance, “Ondo Stocks” y documentación de la API de Global Markets, consultadas en julio de 2026. https://ondo.finance/ondo-stocks y https://docs.ondo.finance/api-reference/quickstart

19. Oficina de Evaluación Independiente del Fondo Monetario Internacional: documentación histórica del congelamiento parcial de depósitos, los controles de capital y la conversión forzosa en Argentina en 2001; y revisión del FMI sobre la flexibilización de la mayoría de las restricciones cambiarias bajo el programa de estabilización de 2025. https://www.imf.org/External/NP/ieo/2003/arg/ y https://www.imf.org/es/news/articles/2025/07/31/pr25272-argentina-imf-completes-first-review-of-the-extended-arrangement-under-the-eff

20. Fondo Monetario Internacional, “Digital Money and Central Banks Balance Sheet”, documento de trabajo n.º 2022/206: Venezuela como caso de dolarización real. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml

21. Fondo Monetario Internacional, “Bolivia: 2025 Article IV Consultation”, informe de país n.º 2025/116. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384

22. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, febrero de 2026, depósitos por moneda. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

23. Banco de México, agregados monetarios de 2024; y Banco Interamericano de Desarrollo, estimación de remesas de México para 2025. https://www.banxico.org.mx/TablasWeb/informe-anual/compilacion-2024/7EF1402E-1443-4070-9C0A-6B352272C3B9.html y https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

24. Banco Interamericano de Desarrollo, *Remittances to Latin America and the Caribbean in 2025: Adaptations in a Context of Uncertainty*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

25. ACNUR, *Global Report 2025 — Situation Overview: Colombia*: Colombia acogía aproximadamente 2.8 millones de venezolanos en 2025. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

26. Confío, registros de diseño del asistente: `docs/designs/ai-assistant-first-redesign.md`, `docs/designs/confio-assistant.md` y `docs/designs/confio-assistant-three-jobs.md`. https://github.com/caesar4321/Confio/tree/main/docs/designs

27. Confío, especificación de Cuenta inteligente, diseño de la cuenta automática y registro de despliegue de la v2 automática (direcciones de contratos, lotes del Safe, hashes de transacciones y las pruebas de regresión de la revisión de v2): `docs/designs/cuenta-inteligente-spec.md`, `docs/designs/hands-off-account.md`, `docs/deploy/hands-off-v2-deploy.md` y `contracts/smart_account/`. https://github.com/caesar4321/Confio/tree/main/contracts/smart_account

28. Banco Central do Brasil, “Pix”. https://www.bcb.gov.br/en/financialstability/pix_en

29. Banco de la República (Colombia), “Bre-B”. https://www.banrep.gov.co/es/bre-b

30. Confío, código fuente y notas de `ConfioSwapRouter`. https://github.com/caesar4321/Confio/tree/main/contracts/crypto_swap

### Procedencia del documento

La versión 4.5 (25 de noviembre de 2026) reestructura el documento en torno a Confío IA como un asistente centrado en la IA que paga; agrega Cuenta inteligente, el agente de compras, Oro y Bitcoin, Futuros y Comprar; actualiza la tabla de contratos según la verificación de código fuente en BscScan y el estado on-chain; y actualiza las métricas operativas a partir de consultas de solo lectura en producción con las definiciones de la versión 4.4. Se preparó a partir del whitepaper anterior en inglés, los registros de diseño y despliegue de Confío en el repositorio público, la configuración de producción, los registros de socios, la documentación oficial de BNB Chain, Ondo y bancos centrales, y la literatura de mercado citada.
