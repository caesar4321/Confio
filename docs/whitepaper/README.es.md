# Confío: el asistente personal que paga en América Latina

**Pídele a Confío que lo resuelva. Hace el encargo y lo termina pagando, por los canales de pago de tu país, con dólares que solo tú controlas.**

Confío es un asistente personal de consumo para América Latina. Como los agentes personales de IA que están llegando en todo el mundo, Confío IA le quita a una persona encargos cotidianos de las manos: buscar y comprar cosas, hacer pedidos, llevar la cuenta de lo que hay que pagar. A diferencia de ellos, termina el trabajo pagando. Paga por el canal local de cada país (Pix, SPEI, Pago Móvil, QR bancario), desde los dólares en autocustodia de la propia persona, tras una confirmación exacta o dentro de límites que la persona firmó on-chain. Confío es totalmente de código abierto y no custodial.

**Referencia global · Versión 4.5 · Noviembre de 2026**<br>
Julian Moon · Fundador y CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*La confianza ya existe. Falta un sistema que la merezca. · Confío en vos.*

**Original autoritativo:** el [documento en inglés](README.md) es la única versión autoritativa del whitepaper de Confío. Esta traducción al español (también hay una [en coreano](README.ko.md)) se ofrece por conveniencia y puede quedar rezagada respecto del original; si difiere del texto en inglés, prevalece el texto en inglés. Traducción sincronizada con la versión 4.5 el 25 de noviembre de 2026.

Este documento es la referencia global actual sobre el producto, la estrategia, el modelo operativo y los riesgos materiales de Confío. Las condiciones detalladas de asignación y vesting de $CONFIO se mantienen en el documento separado de tokenomics.

<details>
<summary><strong>Contenido</strong></summary>

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [La tesis: asistentes que no pueden pagar](#2-la-tesis-asistentes-que-no-pueden-pagar)
3. [Panorama competitivo](#3-panorama-competitivo)
4. [Confío IA: el asistente que hace encargos y paga](#4-confío-ia-el-asistente-que-hace-encargos-y-paga)
5. [Cuenta inteligente: ejecución pagada dentro de límites firmados](#5-cuenta-inteligente-ejecución-pagada-dentro-de-límites-firmados)
6. [Por qué se puede confiar en que una IA pague: la base](#6-por-qué-se-puede-confiar-en-que-una-ia-pague-la-base)
7. [Billetera, seguridad y gobernanza](#7-billetera-seguridad-y-gobernanza)
8. [Usuarios y distribución](#8-usuarios-y-distribución)
9. [Modelo de negocio](#9-modelo-de-negocio)
10. [Cumplimiento y modelo operativo](#10-cumplimiento-y-modelo-operativo)
11. [Riesgos y mitigaciones](#11-riesgos-y-mitigaciones)
12. [Hoja de ruta y estado actual](#12-hoja-de-ruta-y-estado-actual)
13. [Aviso legal](#13-aviso-legal)
14. [Notas](#notas)

</details>

---

## 1. Resumen ejecutivo

Están llegando los asistentes personales de IA que actúan en nombre de una persona: Muse de Meta y dots de OpenAI en Estados Unidos, Pickle en Corea y, creado para América Latina, Zapia. <sup>[1–5]</sup> Conversan, buscan, recuerdan, contactan a negocios y arman carritos. Cuando llegan a pagar, pagan con tarjeta. En América Latina, ahí es donde el encargo se detiene, porque el dinero de todos los días se mueve por canales nacionales —Pix en Brasil, SPEI en México, Pago Móvil en Venezuela, códigos QR bancarios en Bolivia, Bre-B en Colombia— a los que no llegan los pagos de agentes basados en tarjetas. <sup>[7, 8]</sup>

> **Tesis**
>
> Confío es el asistente personal para América Latina que termina el trabajo pagando. Hace el encargo como otros asistentes y luego le paga a la tienda, al comercio o a la persona por el propio canal de ese país, desde un saldo en dólares que la persona controla, con una confirmación exacta o dentro de un límite on-chain que la persona firmó. El encargo es el gancho; los canales, el saldo en autocustodia y los límites que se hacen cumplir son la barrera de protección. Confío no conoce ninguna otra app de consumo en la región que ofrezca esa combinación como un solo producto. En Brasil, las personas ya pueden pedirle al asistente de su propio banco que envíe un Pix; el espacio que cubre Confío es más amplio en la América Latina de habla hispana y en los pagos entre países.

Lo que Confío IA hace hoy, con cada pago confirmado por la persona o acotado por límites que ella firmó:

| Tarea | Cómo funciona |
| --- | --- |
| Comprar en tiendas en línea | Un agente de compras busca en una o varias tiendas desde un navegador en la nube, arma el carrito, muestra el total real con envío y le paga a la tienda por el canal de su país: SPEI en México, Pix en Brasil, Pago Móvil en Venezuela (tiendas que solo piden la referencia del pago). En Bolivia hace el pedido y la persona paga el QR de la tienda. |
| Pagar a personas, códigos QR y comercios | El asistente prepara un envío o un pago por canal local como una tarjeta en el chat; el código, no el modelo, pregunta el monto y valida al beneficiario; la persona confirma y firma en su propio teléfono. |
| Comprar en comercios locales | Comprar, un mercado dentro de la app con pagos retenidos en garantía y protección al comprador, en piloto en Bolivia. |
| Seguir los mensajes y lo pendiente | La vinculación del WhatsApp, el Gmail y el calendario de la propia persona, para que el asistente le diga qué requiere atención y redacte respuestas, se está habilitando con nuevas versiones de la app (sección 4.1). |
| Recargar y retirar | El chat abre el formulario de recarga o retiro, con los límites vigentes del proveedor en ese país. |
| Invertir y automatizar | Acciones, oro y bitcoin como tarjetas con precio; con Cuenta inteligente, pagos y transferencias programados, inversión automática y operaciones automáticas dentro de un tope semanal. |

Al 25 de noviembre de 2026, Confío registra 10,886 usuarios que completaron el registro (14,440 cuentas registradas) y 3,407 dispositivos alcanzables por push, 3,402 de ellos usados en los últimos 30 días. Al 23 de julio de 2026 (la instantánea más reciente disponible con la misma definición), 177 usuarios habían completado la verificación de identidad de Didit con un documento oficial y una selfie en vivo, una tasa de finalización del 61.5% entre los usuarios que la iniciaron. Son métricas internas no auditadas, no cifras de usuarios con fondos ni de usuarios activos mensuales. <sup>[31]</sup>

## 2. La tesis: asistentes que no pueden pagar

### 2.1 Llegan los asistentes personales

En 2026, las grandes empresas de IA pasaron de los asistentes que solo conversan a agentes que hacen encargos. Meta lanzó Muse en Estados Unidos en septiembre de 2026 como un agente que envía correos, reserva viajes, llena formularios y sigue trabajando después de cerrar la app; su pago pasa por Link de Stripe, que emite una tarjeta de un solo uso. <sup>[1]</sup> OpenAI lanzó dots, un asistente siempre activo que se conecta con miles de apps, <sup>[3]</sup> y en noviembre de 2026 agregó ChatGPT Wallet para que dots pueda comprar por el usuario con una tarjeta tokenizada, desarrollada con American Express, Chase, Mastercard y Visa e inicialmente limitada a tarjetas elegibles emitidas en Estados Unidos. <sup>[2]</sup> En Corea, Pickle se encarga de tareas cotidianas de principio a fin en servicios como KakaoTalk y Coupang, y se ha informado que hace llamadas telefónicas por sus usuarios. <sup>[4]</sup>

América Latina tiene los suyos. Zapia se describe como un agente personal de IA creado para latinoamericanos, disponible en WhatsApp, como app y en la web; busca en la web, contacta a negocios por WhatsApp, agenda reuniones, responde en nombre del usuario y sigue precios. <sup>[5]</sup> Luzia comenzó como un asistente gratuito dentro de WhatsApp que responde preguntas y transcribe notas de voz. <sup>[6]</sup> Sus descripciones públicas no incluyen pagarle a un comercio desde un saldo por un canal local.

### 2.2 En América Latina, el dinero se mueve por canales nacionales

Cada país tiene su propio sistema de pagos, y esos sistemas no son interoperables entre sí:

| País | Cómo se mueve el dinero de todos los días | Lo que debe manejar un asistente |
| --- | --- | --- |
| Brasil | Pix, el sistema de pagos instantáneos del banco central: llaves, códigos QR y códigos para copiar y pegar. <sup>[7]</sup> | Interpretar y validar el código Pix y pagar su monto exacto. |
| México | Transferencias SPEI a una CLABE de 18 dígitos; muchas tiendas en línea muestran datos bancarios y una referencia en la página de pago en lugar de un formulario de tarjeta. | Leer la CLABE, el monto y la referencia de la página de pago y pagar exactamente eso. |
| Colombia | Llaves y códigos QR de Bre-B, el nuevo sistema instantáneo interoperable. <sup>[8]</sup> | Resolver la llave y pagar en pesos. |
| Venezuela | Pago Móvil: número de teléfono, banco y cédula de identidad; luego quien paga le reporta la referencia al vendedor. | Pagar primero y luego entregarle la referencia a la tienda. |
| Bolivia | Códigos QR bancarios. | Pagar el monto del QR en bolivianos. |
| Perú | Yape, PLIN y QR interoperable. <sup>[9]</sup> | — (Confío todavía no lo admite). |
| Argentina | Transferencias por alias/CVU y QR interoperable. | — (pagos de Confío pendientes de que el proveedor esté listo). |

Un agente basado en tarjetas no puede completar una compra que pide una transferencia SPEI, un código Pix o una referencia de Pago Móvil, y muchos pagos cotidianos —un vendedor en WhatsApp, un trabajador al que se le paga por QR— ocurren por completo fuera de las redes de tarjetas. Para una persona, cada canal significa otra app, otro formulario y otro identificador. Para un asistente, es una oportunidad: el código puede elegir el canal según el país del beneficiario mientras la persona solo dice lo que quiere. Como el canal sigue al beneficiario y no al banco de quien paga, el mismo diseño puede, donde los proveedores lo permitan, dejar que una persona en un país le pague a una tienda o a su familia en otro.

### 2.3 Por qué el saldo está en dólares

Las personas de toda la región tienen y reciben dólares: mediante remesas, estimadas en US$173.7 mil millones hacia América Latina y el Caribe en 2025, y mediante stablecoins que ya tienen un uso amplio. <sup>[10, 11]</sup> Un saldo en dólares que se puede pagar en pesos, reales o bolívares permite que un solo asistente pague en cualquier país admitido sin que la persona tenga que convertir primero.

### 2.4 La confianza decide a quién se le deja pagar

Darle dinero a una IA plantea la pregunta que todo usuario latinoamericano ya le hace a una app financiera: ¿qué le impide hacer algo indebido? La respuesta de Confío tiene tres capas: **control verificable** (la clave de la billetera se genera en el dispositivo de la persona y Confío no la conserva), **autonomía acotada** (el asistente no puede inventar montos ni beneficiarios; cada pago es una confirmación exacta o cae dentro de un límite firmado on-chain) y **confianza humana** (explicaciones primero en español, precios claros, un liderazgo visible y un asistente que dice con claridad lo que no puede hacer). *La confianza ya existe; falta un sistema que la merezca*: la gente ya confía en otras personas con su dinero, y estos límites son la forma en que Confío se gana esa confianza. La promesa es también una restricción de arquitectura.

## 3. Panorama competitivo

| Categoría | Ejemplos (fuentes públicas) | Qué hacen | Qué les falta para esta tarea |
| --- | --- | --- | --- |
| Asistentes personales de IA | Muse, dots, Pickle, Zapia, Luzia <sup>[1–6]</sup> | Encargos, mensajes, búsqueda, agenda; Muse y dots compran con tarjetas tokenizadas en Estados Unidos. | No le pagan a comercios desde el saldo de la persona por Pix, SPEI, Pago Móvil ni QR bancario. |
| IA dentro de apps de bancos y billeteras | El Pix por voz, texto o imagen de Nubank en su app y en WhatsApp (Brasil, desde diciembre de 2024); Mago de Mercado Pago, que prepara transferencias a partir de una conversación para que la persona las confirme (Argentina). <sup>[12, 13]</sup> | Ejecutan pagos por el canal de su propio país para sus propios clientes. | Solo finanzas y un solo país; no son asistentes personales para encargos fuera de la app. |
| Infraestructura de pagos para agentes | El conjunto de herramientas de pagos con agentes de Iniciador permite que los agentes de bancos y fintechs propongan pagos Pix que el usuario aprueba con biometría mediante Open Finance (Brasil, mayo de 2026). <sup>[14]</sup> | Componentes para instituciones reguladas. | No es un producto de consumo; posibles proveedores más que competidores. |

La posición de Confío es la intersección: un asistente de consumo para encargos, acceso para pagar y cobrar por los canales de varios países, y un saldo en dólares en autocustodia con límites on-chain. Es una afirmación acotada, no la de ser “el primero en combinar IA y pagos”. En Brasil, una persona ya puede pedirle al asistente de su banco que envíe un Pix. El espacio es más claro en la América Latina de habla hispana, donde Confío no tiene a su alcance una infraestructura comparable de iniciación de pagos para agentes, y en los pagos entre países, adonde no llega ningún asistente de un banco nacional.

## 4. Confío IA: el asistente que hace encargos y paga

### 4.1 El chat es el producto

En las versiones actuales, Inicio es la conversación con Confío IA. Un usuario nuevo conoce a su asistente y se le pregunta, en palabras, para qué quiere Confío; la respuesta define los siguientes pasos. Cada tarea que ofrece el menú —recarga, retiro, Cobrar, invitaciones, historial, inversiones, Comprar, Cuenta inteligente, herramientas para negocios y nóminas— tiene una puerta desde el chat. El asistente lee los movimientos y el resumen mensual de la propia persona, acepta fotos y notas de voz, y busca en la web para preguntas generales. <sup>[15, 16]</sup>

Se están habilitando conexiones que amplían los encargos: vincular el propio WhatsApp de la persona como dispositivo para que el asistente le diga qué requiere atención y la ayude a responder; Gmail, abierto a un número limitado de personas mientras la verificación de Google está pendiente; y el calendario del teléfono. Están desplegadas en el servidor y llegan a las personas a medida que se publican nuevas versiones de la app. Confío IA explica instrumentos y riesgos, pero no le dice a una persona que compre, venda o mantenga un ticker concreto, ni predice precios.

### 4.2 Cómo una solicitud se convierte en un pago

| Paso | Quién lo hace | Qué se verifica |
| --- | --- | --- |
| 1. Entender | El modelo lee la solicitud, escrita o dicha en una nota de voz, y decide de qué tarea se trata. | La salida de herramientas y el texto de terceros son datos, nunca instrucciones; después de una búsqueda web, ese turno pierde sus herramientas de dinero. Una nota de voz puede nombrar qué comprar, vender o pagar; nunca fija un monto ni confirma. |
| 2. Preguntar el monto | El código, no el modelo, escribe la pregunta (“¿Cuántos dólares? Escribe solo el número”). | Nunca se extrae un monto de una frase; el número escrito solo como siguiente mensaje es a la vez el monto y el sí, y solo cuenta una respuesta escrita. Un “no” retira las tarjetas pendientes. |
| 3. Resolver el beneficiario | El código interpreta y valida el destino: llaves y códigos Pix con su suma de verificación, dígitos de control de la CLABE, datos de Pago Móvil, contactos de Confío. | La tarjeta muestra solo lo que el código resolvió; un nombre no verificado nunca se marca como verificado. |
| 4. Cotizar | El código calcula el precio: monto local, total en dólares, tipo de cambio, comisión de Confío, vencimiento. | Un cobro con un monto local fijo se paga exactamente. |
| 5. Confirmar | La persona revisa la tarjeta y firma en su propio dispositivo o, para una acción automática de un suscriptor, la cuenta comprueba on-chain su tope firmado. | El modelo no puede dibujar la hoja de confirmación ni puede firmar. |
| 6. Liquidar | El pago se ejecuta en el canal local; la tarjeta sigue el estado del proveedor. | Una tarjeta nunca dice “pagado” antes de que el canal informe que se completó. |

Qué canales se ofrecen lo deciden interruptores en vivo por país y por proveedor, no el modelo. Cuando un corredor está pausado, el asistente lo dice en lugar de improvisar una ruta.

### 4.3 El agente de compras

La persona nombra un producto y, si quiere, una tienda; cuando no se nombra ninguna tienda, una sola búsqueda en varias tiendas devuelve una lista breve de ofertas. Luego el agente trabaja en un navegador en la nube que la persona puede ver en vivo: abre la tienda, agrega los artículos, llega a la página de pago y lee el total real con envío. <sup>[15]</sup>

- **Elegir es consentir.** Cada oferta muestra un total máximo (“hasta $X con envío”); elegirla aprueba ese artículo, esa cantidad y ese total. Un total real más alto, un precio ilegible o un pagador distinto hacen que vuelva una tarjeta de pedido con el desglose real.
- **Los modelos deciden, el código verifica hechos.** Un modelo conduce; un juez de otra familia de modelos revisa cada clic; una revisión final lee la última página antes de hacer el pedido. El código verifica solo hechos: una aprobación genera un solo pedido; ambos modelos deben leer el mismo total, que debe aparecer en la página; un identificador de pago debe ser válido y mostrarse junto al monto aprobado, en una página que apareció después del pedido.
- **Límites en el código.** El servidor limita los pasos, el tiempo y el costo de modelo de cada tarea.
- **Canal según el país de la tienda.** Datos bancarios SPEI leídos de la propia página de pago de la tienda en México (se paga el monto exacto en pesos; cualquier excedente de la conversión queda en la cuenta local de la persona), QR Pix en Brasil y Pago Móvil en Venezuela, que se paga antes del pedido ingresando la referencia en el formulario de la tienda. En Bolivia, mientras los pagos QR de Confío estén desactivados, el agente hace el pedido y la persona paga el QR de la tienda. Los demás países se rechazan en lugar de pagarse con una transferencia aproximada.
- **Quién paga.** La búsqueda, el carrito y la revisión con precio son gratuitos. Comprar y pagar es un beneficio de Cuenta inteligente: la cuenta paga mediante una regla “Compras con Confío IA” firmada una sola vez con Confío Face (por defecto US$200 cada 28 días, editable), nunca directamente desde la billetera personal.

El agente de compras está en una etapa temprana. Las páginas de las tiendas cambian, algunos procesos de pago no ofrecen a las cuentas ordinarias un canal local con el que se pueda pagar y Confío todavía no ha demostrado que las compras se completen de forma confiable en muchas tiendas.

### 4.4 Lo que Confío IA no hará

- Extraer un monto de una frase, o pagar ante un “sí” sin condiciones verificadas por el código.
- Pagarle a un beneficiario cuyos datos el código no pudo validar, o presentar como verificado un nombre no verificado.
- Pagar por encima de un total que la persona aprobó o de un tope que la persona firmó.
- Pagarle a una tienda en un país sin un canal que pague el monto local exacto.
- Recomendar un ticker concreto o predecir precios.
- Ofrecer Oro y Bitcoin o Futuros a usuarios de iOS, ni ningún producto del que la persona quede excluida por su país o su elegibilidad.
- Quedarse en silencio: cuando no puede hacer algo, lo dice y, cuando es posible, abre la pantalla donde la persona puede hacerlo.

### 4.5 Canales por país

Las capacidades siguen los interruptores en vivo de los proveedores y cambian; este es el estado al 25 de noviembre de 2026. <sup>[17]</sup>

| País | Disponible hoy | No disponible o pausado |
| --- | --- | --- |
| México | Recarga y retiro; CLABE propia para recibir pesos; pagos SPEI a cualquier CLABE; pagos programados a CLABE; pagos SPEI del agente de compras. | — |
| Brasil | Pagos Pix por llave, QR o código; recepción por QR Pix; pagos Pix programados; pagos Pix del agente de compras. | — |
| Venezuela | Recarga y envíos por Pago Móvil; pagos programados por Pago Móvil; agente de compras para tiendas que solo piden la referencia. | Tiendas que requieren otros datos de pago. |
| Bolivia | Recarga y retiro bancario; Comprar; agente de compras con la persona pagando el QR de la tienda. | Pagar y recibir QR bancarios mediante Confío (desactivado). |
| Argentina, Chile, Perú | Canales locales de recarga; retiros donde el proveedor los ofrece. | Pagos a CVU y QR argentinos (pendientes de que el proveedor esté listo). |
| Colombia | Retiros mediante la rampa existente. | Recarga, y conversión y pagos por Bre-B (pausados). |

## 5. Cuenta inteligente: ejecución pagada dentro de límites firmados

### 5.1 Qué es

Cuenta inteligente es la forma en que funciona la ejecución pagada del asistente. Es un contrato inteligente separado, uno por usuario, cuya propietaria es la billetera personal del usuario. El usuario mueve dinero a ella; dentro de ella, el asistente puede actuar según reglas y topes que el titular firmó, y la cuenta puede pasar a un beneficiario designado. La billetera personal no se ve afectada. <sup>[18]</sup>

| Incluye | Lo que obtiene el usuario |
| --- | --- |
| Confío IA+ | El asistente ejecuta sobre la cuenta: compras en tiendas dentro del tope de compras, operaciones automáticas dentro del tope semanal, los cambios de reglas que pide el titular, una distribución objetivo de la inversión que se mantiene con nuevas compras, alertas y una revisión mensual. |
| Pagos automáticos | Envíos diarios, semanales, quincenales o mensuales a usuarios de Confío y pagos a un destino CLABE, Pix o Pago Móvil guardado. |
| Inversión automática | Compras periódicas de acciones, bitcoin y oro. |
| Beneficiario (*Herencia Digital*) | Un beneficiario verificado por Didit puede tomar la titularidad tras un período de impugnación (por defecto 180 días, entre 90 y 1,825) durante el cual cualquier acción firmada por el titular cancela el reclamo. |

**Precio:** US$149.99 al año (preseleccionado) o US$14.99 al mes, un solo nivel, sin reembolsos, cobrado desde dentro de la cuenta (primero de los dólares y luego, tras los avisos, mediante una venta forzosa por el monto de la tarifa de un período). La comisión de conversión del 0.9% no se exime. <sup>[18]</sup>

### 5.2 Ejecución automática (activa desde el 25 de noviembre de 2026)

Las operaciones desde el chat en acciones, oro y bitcoin, las compras en Comprar y las compras en tiendas pueden ejecutarse desde la cuenta sin una firma por acción:

- **Topes firmados una sola vez con Face.** Un tope semanal de operaciones (por ejemplo US$250, 1,000 o 2,500) en el que cuentan tanto las compras como las ventas, que funciona como un balde con fugas (*leaky bucket*): como máximo un tope en cualquier instante y uno por semana en promedio (poco menos de dos dentro de una misma semana). Las compras en tiendas tienen su propio tope.
- **Los fondos se quedan en la cuenta.** Los intercambios deben mantenerse dentro del 1.5% de una fuente de precios de Chainlink, la comisión de acciones está acotada en 90 puntos básicos y las ventas deben devolver su valor a la cuenta dentro de esa banda.
- **Alertas e interruptor de emergencia.** Cada operación automática notifica al titular; una que no tenga detrás una propuesta del chat genera una alerta de seguridad. El Safe puede detener todas las vías automáticas a la vez (`tradePaused`).
- **Resultados en el chat.** El resultado (qué se compró o vendió y por cuánto) se publica en la conversación en el idioma de la persona y se muestra en la tarjeta de la operación. La operación cuenta en el portafolio de la persona junto con las tenencias de la billetera personal, y se puede compartir en Comunidad como cualquier operación firmada, con su resultado frente al costo propio de la cuenta.

### 5.3 Diseño del contrato y supuesto de confianza

- **Cuentas inmutables.** Cada cuenta es un clon EIP-1167 sin función de actualización, sin `DELEGATECALL` y sin `SELFDESTRUCT`. Sus límites son constantes; los valores leídos de la factory se acotan; `withdraw`, `withdrawAll`, `cancelClaim` y las funciones de reclamo funcionan aunque fallen todas las llamadas a la factory.
- **Factory por generación.** La factory UUPS, cuyo propietario es el Safe de 3 de 5, crea una cuenta vigente por titular. Desde el 25 de noviembre de 2026 registra una implementación por generación: las cuentas v1 conservan su bytecode, las cuentas nuevas usan `ConfioSmartAccountV2` (reglas Trade y Purchase, `relayTrade` y `relayPurchase` exclusivos del relayer, baldes por regla, bandas de precio), y pasar a v2 es un `migrate()` opcional firmado por el titular.
- **Compras.** `ConfioPurchaseSpender` retira exactamente el USDT aprobado por la salida normal del 0.9% y, en la misma transacción, lo reenvía íntegro al depósito puente de ese pago; nada queda en él. Las compras en Comprar entran al escrow mediante `depositFrom`, que registra al titular como comprador y reembolsa a la cuenta que pagó.

Las acciones automáticas confían en `ConfioStockRouter`, `ConfioSwapRouter` y `ConfioMarketEscrow`, que el Safe puede actualizar. Una clave de relayer comprometida, por sí sola, no puede sacar valor de una cuenta. Una clave de relayer comprometida junto con una actualización maliciosa del router de acciones por parte del Safe sí podría vender acciones a un precio falsificado, porque la cuenta no puede verificar por sí misma la firma de cotización de Ondo. Una clave de operador de compras comprometida queda acotada por el tope de compras de cada titular (en el peor caso, cerca del doble del tope alrededor del cambio de período), la lista de spenders permitidos del Safe y su pausa de tarjeta. El firmante de pedidos del escrow tiene su propia clave, separada de la del árbitro y la del relayer.

Los cambios de v2 recibieron una revisión independiente interna el 25 de noviembre de 2026, antes de su puesta en marcha; sus hallazgos se corrigieron y cada prueba de concepto se conserva como prueba de regresión en Foundry que comprueba que el ataque ya falla; por ejemplo, las ventas ahora cuentan en el tope al valor de la fuente de precios, y lo obtenido por una venta de acciones debe corresponder al valor de la cotización incluso si se reemplazara el router. No fue una auditoría externa realizada por una firma de seguridad. <sup>[18]</sup>

## 6. Por qué se puede confiar en que una IA pague: la base

Un asistente es tan confiable como el sistema de dinero que tiene debajo. El de Confío se construyó para que el asistente nunca necesite custodia: la clave se queda en el dispositivo de la persona, los saldos viven en contratos con reglas públicas en BNB Smart Chain, las comisiones de red están patrocinadas y el servidor solo puede preparar llamadas que la persona —o la propia cuenta de la persona, dentro de límites firmados— ejecuta.

### 6.1 Despliegues públicos en BNB Smart Chain

Todos los contratos que se listan abajo están activos en la red principal de BNB Smart Chain y tienen su código fuente verificado en BscScan (los proxies están vinculados a sus implementaciones verificadas). Los contratos actualizables son propiedad del Safe de 3 de 5 `0xF29A418744E793973BF4eEc676F8a30B2793b623`. <sup>[19, 20]</sup>

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

**Cambios desde la versión 4.4**, todos realizados a través del Safe y anotados en los registros públicos de despliegue: <sup>[18, 19]</sup>

- 9 de noviembre de 2026: el router v3 de Ondo Stocks eliminó la vía transitoria de comisión del 0.30%.
- 21–22 de noviembre de 2026: se desplegaron la factory de Cuenta inteligente, la implementación de cuenta v1 y el recaudador de tarifas; se actualizó cUSD para que las cuentas de la factory puedan activar la comisión por referido; se habilitó la herencia (en un solo sentido).
- 25 de noviembre de 2026: se desplegó `ConfioSmartAccountV2`; se actualizó el proxy de la factory (implementación por generación, `migrate()`, `tradePaused`); se actualizó el proxy del escrow de Comprar (`depositFrom` con una firma vinculada al pagador, reembolsos a la cuenta que pagó; el firmante de pedidos pasó a tener su propia clave, y el árbitro sigue siendo el patrocinador); se desplegó `ConfioPurchaseSpender` y se agregó a la lista permitida; se reanudaron las operaciones automáticas tras una migración de prueba (canario) de una cuenta del fundador.

### 6.2 El saldo en dólares: cUSD y cUSD+

Una persona tiene un solo dólar Confío, que se muestra como un solo saldo. **cUSD** es el dólar universal para pagos, respaldado 1:1 por USDT en un vault actualizable y único perímetro externo de comisión de conversión. **cUSD+** es una participación acumulativa en dólares respaldada por USDY, para usuarios elegibles según Ondo. <sup>[22, 24]</sup>

- **Entrada y salida.** El USDT que llega desde una rampa o una billetera externa se convierte en cUSD o cUSD+ con una comisión del 0.9%; salir a USDT —incluido todo pago por canal local— paga 0.9%. La comisión está limitada en el código a 90 puntos básicos. La acuñación requiere un patrocinador autorizado; la redención con comisión no requiere permisos, de modo que un titular puede salir sin el patrocinador de Confío. La conversión interna cUSD↔cUSD+ no tiene comisión porque el valor permanece dentro del sistema.
- **Participación en el rendimiento.** El 85% de la apreciación positiva del precio de referencia de USDY se acumula para los titulares de cUSD+ y el 15% para Confío como excedente del vault. El rendimiento es variable y no está garantizado.
- **Respaldo y oráculo.** Las consultas públicas muestran las obligaciones, el ratio de respaldo y el excedente; la contabilidad redondea a favor del respaldo; el USDY de respaldo no se puede retirar. Si el oráculo de USDY se mueve más allá de un umbral de protección, las rutas que mueven valor se detienen hasta que la gobernanza multiparte registre una decisión vinculada a evidencia.
- **Permisos.** El comprador autorizado de USDY es el vault cUSD+, no el usuario; la acuñación está sujeta a la elegibilidad de Ondo. <sup>[21, 23]</sup>

### 6.3 Pagos, nóminas y Comprar

- **Transferencias.** El servidor prepara las llamadas exactas, el usuario firma y Confío patrocina el gas; no hay comisión de plataforma, y una conversión interna sin comisión conecta a destinatarios de cUSD y de cUSD+.
- **Pagos a comercios.** El contrato de pagos le paga al comercio el neto de la comisión de Pay del 0.9%; una autorización del backend de corta vigencia fija las condiciones exactas; exactamente un pago puede liquidar una factura, en una sola red. El USDT sin convertir no está autorizado, así que Pay no puede eludir la comisión de conversión.
- **Nóminas.** Las empresas fondean un escrow separado por activo y autorizan a delegados para firmar pagos; la contabilidad de comisiones se mantiene separada del principal.
- **Comprar.** Un mercado dentro de la app para bienes físicos, en piloto en Bolivia, donde compradores y vendedores pasan la verificación de Didit. El `ConfioMarketEscrow` compartido retiene los dólares del comprador por pedido; el comprador puede confirmar la entrega, abrir una disputa o recuperar los fondos tras un plazo; un árbitro resuelve las disputas; los vendedores pagan una comisión del 8%. El piloto tiene muy pocas tiendas y pedidos.

### 6.4 Inversión

- **Ondo Stocks.** Mediante Ondo Global Markets, a través del `ConfioStockRouter` UUPS (propiedad del Safe). Una compra sale de cUSD+ por la salida ordinaria del 0.9% y entrega el token de la acción a la billetera o a la Cuenta inteligente; una venta devuelve lo obtenido por la entrada del 0.9%. El router no cobra comisión propia; desde la v3 no tiene ninguna otra vía de comisión y devuelve el excedente de la liquidación. Sujeto a la elegibilidad de Ondo y a la disponibilidad de mercados. <sup>[20, 25]</sup>
- **Oro y Bitcoin.** `ConfioSwapRouter` compra y vende tokens del catálogo como BTCB y XAUt en PancakeSwap con la misma salida y entrada del 0.9%, sin comisión propia, sin guardar nada en reposo, con un destinatario fijo y solo con operaciones del relay dentro de un límite de deslizamiento. No se ofrece en iOS; está bloqueado en algunos países. <sup>[26]</sup>
- **Futuros.** Futuros perpetuos en Hyperliquid para usuarios elegibles de Android, conectados mediante el puente de Relay, con la comisión del 0.9% en cada apertura, cierre o aporte de margen y sin comisión de builder; la app verifica cada orden de puente y cada firma. No se ofrece en iOS; está bloqueado en Estados Unidos, Canadá, el Reino Unido y Bélgica. Con apalancamiento se puede perder todo el margen. <sup>[15]</sup>

### 6.5 $CONFIO

$CONFIO es el token comunitario. No es una stablecoin y no respalda ningún saldo en dólares. El contrato BEP-20 tiene una oferta fija de 1,000,000,000 CONFIO, sin acuñación posterior al despliegue, sin pausa global y sin vía de actualización; la oferta solo puede disminuir mediante quemas voluntarias. La tesorería multiparte puede congelar una dirección durante un incidente de seguridad grave y, tras una espera pública de 7 días, devolver un saldo congelado a la parte a la que se le robó. El nombre on-chain es el ASCII “Confio”; usa únicamente la dirección canónica indicada arriba. <sup>[20]</sup>

El vault de preventa de reemplazo acepta cUSD con una curva lineal por tramos e inmutable: US$0.20→0.30 para los primeros 4 millones de CONFIO, US$0.30→0.70 hasta 24 millones y US$0.70→1.30 hasta 74 millones. Cobra la integral bajo la curva, se inicializó con el historial de compras previo, está fondeado para los reclamos migrados y no tiene ninguna función para cambiar precios. Las recompensas se acumulan en la base de datos de Confío al precio vigente de la curva y se pueden reclamar mediante firmas EIP-712 acumulativas después de la llamada irreversible a `unlockClaims()` en el lanzamiento en el DEX. El RewardVault está controlado por la tesorería: su propietario puede rotar el firmante, pausar los reclamos y retirar fondos. La asignación, el vesting y la concentración se divulgan en el documento de tokenomics separado.

### 6.6 Por qué BNB Smart Chain

El producto siguió a Ondo: USDY, InstantManager, el oráculo de precios y la liquidación de Global Markets están desplegados en BNB Smart Chain, y mantener todos los contratos de Confío junto a ellos significa que no hay ningún puente entre el saldo, los pagos, Cuenta inteligente, la inversión y $CONFIO; que hay una sola dirección para todo; y que hay un solo sistema de transacciones patrocinadas, de modo que el asistente nunca tiene que pedirle a nadie que compre gas. BNB Smart Chain también ofrece amplia liquidez de USDT y comisiones bajas para la actividad de consumo patrocinada. <sup>[21, 25, 27–29]</sup> Tiene sus propias contrapartidas en materia de descentralización: una interrupción de la red, congestión, fallas de RPC o cambios de políticas del ecosistema podrían afectar a todo el producto, riesgos que mitigan, sin eliminarlos, múltiples rutas RPC y una salida de emergencia.

## 7. Billetera, seguridad y gobernanza

### 7.1 Billetera no custodial

Confío genera la clave EVM del usuario en su dispositivo; el servidor nunca la conserva. El material de recuperación cifrado está diseñado para la cuenta personal en la nube del usuario, de modo que no existe un repositorio central de claves de usuarios. <sup>[15, 30]</sup>

> **Ni siquiera nosotros**
>
> Confío nunca conserva la clave de la billetera del usuario, así que ni Confío ni su asistente pueden firmar una transacción ordinaria de la billetera como si fueran ese usuario. Lo que el asistente puede hacer sin una firma por acción se limita a una Cuenta inteligente que el usuario fondeó, bajo reglas y topes que el usuario firmó. Los contratos de producto siguen teniendo sus propios controles divulgados de elegibilidad, pausa, congelamiento, actualización o gobernanza.

### 7.2 Transacciones patrocinadas

Los usuarios nunca necesitan BNB. Las autorizaciones EIP-7702 y un delegado de lotes sin propietario permiten que el usuario firme las llamadas previstas mientras el patrocinador de Confío paga el gas; las aprobaciones y las acciones se ejecutan de forma atómica. La política del servidor restringe destinos, selectores, montos, destinatarios, vencimientos y límites diarios. Se mantienen las vías alternativas de emergencia y las salidas directas porque el patrocinio es un servicio, no una garantía de la blockchain.

### 7.3 Salvaguardas del asistente en el código

La seguridad del asistente no depende de las instrucciones que se le dan al modelo. Las herramientas de dinero se delimitan por la sesión autenticada, nunca por un identificador que aporte el modelo; los empleados de negocios no reciben herramientas de dinero; los montos provienen solo de una pregunta escrita por el código; los beneficiarios se validan con intérpretes específicos de cada canal; las confirmaciones las dibuja la app; la salida de herramientas y el contenido de las páginas son datos; el servidor limita el gasto, los pasos y el costo de modelo del agente de compras; y los canales se activan por país con ajustes que el modelo no puede cambiar. Los cambios se prueban con conversaciones grabadas de varios turnos y con páginas reales de tiendas grabadas.

### 7.4 Código abierto y capacidad de actualización

La app, el backend, el asistente, el agente de compras, los contratos, los registros de despliegue y las pruebas son públicos, y los contratos desplegados tienen su código fuente verificado. La seguridad se apoya en pruebas unitarias, de fork, de invariantes, adversariales y ensayos de actualización; gobernanza multiparte; comisiones acotadas; respaldo que no se puede retirar; protecciones del oráculo; pausas; protección contra reutilización; y despliegue escalonado. Ningún método de revisión elimina el riesgo de los contratos inteligentes ni el riesgo operativo. <sup>[15, 19, 20]</sup>

| Componente | ¿Actualizable? | Por quién |
| --- | --- | --- |
| Vaults cUSD y cUSD+ | Sí (UUPS) | Safe de 3 de 5, con implementaciones públicas y verificaciones de disposición de almacenamiento |
| Router de acciones, router de swaps, escrow de Comprar, heartbeat | Sí (proxies) | Safe de 3 de 5 |
| Factory de Cuenta inteligente | Sí (UUPS) | Safe de 3 de 5; puede agregar una implementación para cuentas nuevas o que migran y pausar las vías automáticas o de tarjeta, pero no puede cambiar una cuenta existente |
| Cuentas de Cuenta inteligente | No (clones inmutables) | Cambiar de versión es un `migrate()` firmado por el titular |
| Spender de compras, recaudador de tarifas, delegado de lotes, token $CONFIO, curva de la preventa | No | — |

Los vaults siguen siendo actualizables porque cUSD+ depende de contratos externos de Ondo que pueden cambiar y cUSD es el perímetro de comisiones compartido. La consecuencia aceptada es el supuesto de confianza de la sección 5.3.

## 8. Usuarios y distribución

| Métrica | Instantánea | Fecha | Definición |
| --- | ---: | --- | --- |
| Usuarios que completaron el registro | 10,886 | 25 nov 2026 | Cuentas activas, salvo las cuentas de prueba de la plataforma, que terminaron la incorporación con cualquier método de registro (14,440 cuentas registradas). |
| Dispositivos alcanzables por push | 3,407 | 25 nov 2026 | Dispositivos actualmente accesibles mediante notificaciones push. |
| Usados en los últimos 30 días | 3,402 | 25 nov 2026 | Dispositivos alcanzables por push registrados como usados en los 30 días previos; no es una cifra estandarizada de usuarios activos mensuales. |
| Usuarios verificados por Didit | 177 | 23 jul 2026 | Usuarios que presentaron un documento de identidad oficial y completaron la prueba de presencia real con selfie en vivo y la coincidencia facial. |
| Finalización de la verificación de identidad | 61.5% | 23 jul 2026 | Proporción de usuarios que completaron el flujo de Didit entre quienes lo iniciaron. |

Estas métricas internas no están auditadas. Desde finales de octubre de 2026, el registro ya no requiere un número de teléfono, por lo que los usuarios se cuentan por incorporación completada; la cifra del 23 de julio de 2026 (8,004) se contó por verificación telefónica y no es directamente comparable. Las métricas no implican que los usuarios tengan fondos, estén activos o sean elegibles para todos los productos. <sup>[31]</sup>

La audiencia en español liderada por el fundador de Confío suma aproximadamente 480,000 personas entre plataformas sociales, con un gasto en medios pagados prácticamente nulo hasta la fecha. <sup>[32]</sup> Ese canal es la forma de explicar un comportamiento nuevo —dejar que un asistente pague— de manera reiterada y pública, en el idioma del usuario. La medida de éxito acordada es la proporción de personas que dejan que Confío IA pague una vez y lo vuelven a dejar pagar dentro de 30 días. El despliegue es país por país y sigue las capacidades verificadas de los proveedores, no una bandera de país en una página promocional.

## 9. Modelo de negocio

La ejecución pagada del asistente y la red de canales son las fuentes de ingresos. Hablar con Confío IA, buscar, armar carritos y las revisiones con precio son gratuitos; ejecutar en nombre de la persona se paga con Cuenta inteligente; mover dinero a través del perímetro del dólar hacia un canal local paga la comisión del 0.9%.

| Fuente de ingresos | Política actual |
| --- | --- |
| Cuenta inteligente | US$149.99 al año (predeterminado) o US$14.99 al mes, cobrados desde dentro de la cuenta; sin reembolsos. Incluye Confío IA+ (compras en tiendas, operaciones automáticas, cambios de reglas por chat), la automatización y el beneficiario. |
| Salida del sistema de dólares Confío | 0.9% cuando cUSD o cUSD+ se convierte en USDT externo, incluidos todos los pagos por canal local y todas las compras del asistente. |
| Entrada al sistema de dólares Confío | 0.9% cuando el USDT se convierte en cUSD o cUSD+, desde una rampa o una transferencia on-chain. |
| Transferencias y conversión interna | 0%; las comisiones de red están patrocinadas. |
| Pagos a comercios y nóminas | Comisión plana de plataforma del 0.9%, aplicada on-chain. |
| Comprar | Comisión del 8% del mercado, pagada por el vendedor. |
| Participación en el rendimiento de cUSD+ | 15% de la apreciación positiva de USDY; variable, no garantizada. |
| Acciones, Oro y Bitcoin, Futuros | La misma comisión de perímetro del 0.9%; sin comisión aparte de negociación ni de builder. Pueden aplicarse diferenciales de terceros y costos de la plataforma de ejecución. |
| Economía de los canales fiat | Los precios del proveedor y cualquier tarifa de cuenta local se muestran en la cotización en vivo. |

La regla pública es **0.9% para entrar, 0% para moverse dentro, 0.9% para salir**; Cuenta inteligente no la exime. El patrocinio de la red y el uso de modelos son costos del producto.

## 10. Cumplimiento y modelo operativo

Confío separa la custodia de la clave de la billetera de las obligaciones de producto y de proveedor. La custodia fiat, la conversión de moneda, la verificación de identidad y el acceso a activos con permisos los realizan los proveedores correspondientes; esto describe el diseño operativo y no es una afirmación de que Confío carezca de obligaciones legales o de cumplimiento.

- Didit realiza la verificación de identidad (documento oficial, selfie en vivo, prueba de presencia real, coincidencia facial). Los usuarios menores de 18 años son rechazados.
- Los proveedores fiat aplican sus propios controles de identidad, domicilio, elegibilidad, sanciones y transacciones; la verificación de Didit por sí sola no garantiza la aprobación de un proveedor.
- La acuñación de USDY y el acceso a Ondo Stocks siguen los requisitos de elegibilidad y geográficos de Ondo. <sup>[21, 23, 25]</sup>
- El beneficiario de una Cuenta inteligente debe ser un usuario de Confío verificado por Didit, designado solo a través del control del patrocinador de Confío, y debe aceptar; los beneficiarios residentes en Estados Unidos están bloqueados.
- Comprar requiere la verificación de Didit para compradores y vendedores.
- El agente de compras nunca elude un bloqueo de un sitio y rechaza los países sin un canal que pague el monto exacto del pedido.
- Los nuevos países y canales se lanzan solo después de las verificaciones legales, operativas y de proveedor.

## 11. Riesgos y mitigaciones

Ningún producto financiero, y ningún agente de IA, está libre de riesgos. Esta tabla no es exhaustiva.

| Riesgo | Mitigación actual | Exposición residual |
| --- | --- | --- |
| **Malentendido o error del modelo de IA** | Los modelos proponen; el código pregunta los montos, valida a los beneficiarios, calcula precios y dibuja la confirmación; el texto de herramientas y páginas son datos; pruebas con conversaciones grabadas. | Un modelo puede interpretar mal una solicitud, elegir el producto equivocado o responder de forma incorrecta; una persona puede confirmar sin leer. |
| **Compra en tienda equivocada o fallida** | Elegir aprueba un total máximo; un total más alto hace volver la tarjeta de pedido; dos modelos deben leer el mismo total, que debe aparecer en la página; una aprobación, un pedido; límites del servidor; pago desde una regla de cuenta con tope. | Las tiendas cambian sus páginas, cancelan, envían mal o retrasan reembolsos; la persona puede tener que tratar con la tienda. El agente todavía no está probado en muchas tiendas. |
| **Errores en pagos por canal local** | Identificadores validados con suma de verificación, cotizaciones por monto exacto, seguimiento del estado del proveedor, ningún “pagado” antes de que el canal lo confirme. | Los proveedores pueden fallar, retrasarse, revertir o pausar; un beneficiario de tienda leído de una página de pago todavía puede ser incorrecto. |
| **Confianza en la ejecución automática y en la cuenta inteligente** | Cuentas inmutables; topes on-chain; compras y ventas contabilizadas; bandas de precio; límite de comisión; alertas; interruptores de emergencia del Safe; clave separada para el firmante de pedidos; revisión interna con pruebas de regresión. | Las acciones automáticas confían en routers y en un escrow actualizables por el Safe; un relayer comprometido junto con una actualización maliciosa podría vender acciones a un precio falsificado; un operador comprometido queda acotado por cada tope. Las reglas se ejecutan tal como se firmaron. |
| **Competencia** | La combinación de encargos, canales de varios países y límites en autocustodia; código abierto. | Asistentes globales o bancos regionales pueden agregar pagos por canales locales; los bancos brasileños ya ofrecen Pix mediante agentes a sus propios clientes. |
| **Canales fiat y corredores pausados** | Interruptores en vivo por país y por proveedor; pausas ante incidentes o señales de fraude (recarga y Bre-B en Colombia pausados). | La cobertura, los precios y la disponibilidad de proveedores pueden cambiar sin previo aviso. |
| **Activos subyacentes** | cUSD respaldado por USDT; cUSD+ mantiene USDY con contabilidad pública. | Riesgos de pérdida de paridad, emisor, custodia, reservas y redención de USDT y USDY. |
| **Contratos inteligentes y oráculo** | Código abierto, despliegues verificados, pruebas por capas, controles acotados, protección del oráculo. | Defectos, errores de integración o de actualización; datos incorrectos del oráculo pueden retrasar depósitos y redenciones. |
| **Liquidez y redención** | Redención con comisión y sin permisos; Emergency Exit transmite a través de nodos BSC públicos. | La liquidez de InstantManager, los proveedores, las condiciones de la red o medidas de cumplimiento pueden retrasar las salidas. |
| **Inversión y apalancamiento** | Routers verificados, entrega directa, límites de comisión y de deslizamiento, filtros de elegibilidad y de país. | Riesgos de mercado, emisor, plataforma de ejecución, puente, liquidación y pérdida total, especialmente en Futuros. |
| **Recuperación de claves** | Claves en el dispositivo y recuperación en la nube personal. | La pérdida del dispositivo o del acceso a la nube, o defectos de recuperación, pueden afectar el acceso. |
| **Gobernanza y BNB Smart Chain** | Safe de 3 de 5, registros públicos de actualizaciones, verificaciones de almacenamiento; múltiples rutas RPC. | Los firmantes podrían hacer un cambio perjudicial; una interrupción de la red o cambios de políticas afectan a todo el producto. |
| **Regulación y delitos financieros** | Verificaciones de identidad, controles de los proveedores, restricciones geográficas, revisión jurídica, bloqueo de cuentas abusivas. | Los proveedores o las autoridades pueden restringir actividad; las reglas para agentes de IA que pagan todavía están en desarrollo. |
| **Token y recompensas** | Oferta fija, curva inmutable, contratos públicos, tokenomics separado. | Concentración del fundador, liquidez, volatilidad; las recompensas dependen del fondeo de la tesorería. |
| **Métricas** | Se divulgan definiciones, fechas y su carácter no auditado. | El uso inicial puede estar concentrado y no predecir la adopción. |

## 12. Hoja de ruta y estado actual

| Área de trabajo | Completado / actual | Próximo hito verificable |
| --- | --- | --- |
| Confío IA | Inicio y alta centrados en el chat; tarjetas de pago, operación y recarga con montos preguntados por el código; puertas a cada tarea; memoria. | Personas que repiten pagos con el asistente; la revisión independiente pendiente de los pagos por chat. |
| Conexiones para encargos | WhatsApp, Gmail y calendario del teléfono desplegados en el servidor. | Publicación en versiones de la app; verificación de Google para Gmail más allá del grupo limitado. |
| Agente de compras | Compras desde navegador en la nube con modelos jueces y hechos verificados por el código; búsqueda en varias tiendas; SPEI, Pix y Pago Móvil; Bolivia con la persona pagando el QR. | Compras completadas de forma confiable en más tiendas; pagos por monto exacto para el QR fijo de Argentina. |
| Cuenta inteligente | Factory, cuentas v1 y v2, recaudador de tarifas y spender de compras verificados; herencia habilitada; operaciones automáticas, Comprar y compras en tiendas activas desde el 25 de noviembre de 2026. | Trasladar las reglas de envío, de pago y de tarjeta a través de la migración; suscriptores de pago. |
| Canales | Activos en México, Brasil, Venezuela, Bolivia, Argentina, Chile y Perú según la sección 4.5; Colombia pausada. | Reabrir Colombia; pagos QR en Bolivia; proveedores verificados adicionales. |
| Base | Perímetro cUSD/cUSD+, transacciones patrocinadas, pagos, nóminas, escrow de invitaciones, routers de acciones y de swaps, Futuros en Android, vaults de $CONFIO. | Supervisión de la conciliación y de las salidas; revisión jurídica para Oro y Bitcoin y Futuros en iOS. |
| Comprar | Escrow actualizado para compras desde la cuenta; piloto en Bolivia. | Vendedores y compradores recurrentes. |
| Distribución | 10,886 usuarios que completaron el registro; audiencia del fundador de ~480,000 personas; sin medios pagados. | Usuarios con fondos, pagos repetidos con el asistente, cohortes por país. |

Confío mide por separado registros, usuarios verificados, usuarios con fondos y usuarios activos, junto con las personas que repiten pagos con el asistente, las compras del agente completadas y fallidas, los suscriptores de Cuenta inteligente, las comisiones de conversión, la entrada neta y las cohortes por país; los ingresos se reportan excluyendo las cuentas bloqueadas y las del fundador.

> **La siguiente prueba**
>
> Personas que dejan que Confío IA haga un encargo y lo pague una vez, y lo vuelven a hacer dentro de 30 días, en varios países de América Latina.

## 13. Aviso legal

Este documento se ofrece únicamente con fines informativos y de referencia técnica. No constituye asesoría de inversión, jurídica, fiscal, contable ni financiera; no es un prospecto, una oferta, una solicitud, una recomendación ni una promesa de rendimientos. Las descripciones de los productos reflejan el estado al 25 de noviembre de 2026 y pueden cambiar. Las descripciones de productos de terceros se basan en las fuentes públicas citadas, a sus fechas de consulta, y pueden estar incompletas o desactualizadas.

Confío IA es un asistente automatizado. Sus respuestas pueden ser incompletas o incorrectas y no constituyen asesoría financiera personalizada. Las compras realizadas por el agente de compras son contratos entre la persona y la tienda; Confío no garantiza los productos, la entrega, las devoluciones ni los reembolsos de una tienda. Las acciones ejecutadas por una Cuenta inteligente siguen las reglas y los topes que firmó su titular.

USDT, cUSD y cUSD+ no son depósitos bancarios y no están cubiertos por un sistema de seguro de depósitos. Las stablecoins, los títulos tokenizados, los contratos inteligentes, las blockchains, los oráculos, los proveedores fiat, los creadores de mercado, los custodios y otras infraestructuras pueden fallar, suspenderse, perder valor o quedar sujetos a nuevas reglas. Cualquier rendimiento de cUSD+ es variable y no está garantizado; el acceso a USDY está sujeto a la elegibilidad de Ondo y a la ley aplicable.

Ondo Stocks son instrumentos financieros tokenizados, no depósitos bancarios. Los tokens de oro y bitcoin y los futuros perpetuos apalancados pueden perder valor rápidamente, y en Futuros se puede perder todo el margen. $CONFIO es independiente de USDT, cUSD, cUSD+ y USDY y no otorga ningún derecho sobre el respaldo, los ingresos, el capital social, los activos o los beneficios de Confío, salvo que términos definitivos dispongan expresamente lo contrario.

Antes de usar cualquier servicio, los lectores deben revisar los términos definitivos de los productos, las divulgaciones de riesgos, los contratos inteligentes, los términos de los proveedores y la legislación local.

## Notas

Fuentes de terceros consultadas el 25 de noviembre de 2026.

1. Meta, “Introducing Muse: The World’s First Personal AI Agent Built for Everyone”, 8 de septiembre de 2026: lanzamiento en Estados Unidos; correo, viajes, formularios; pago mediante Link de Stripe con tarjetas de un solo uso; aprobación antes de las compras. https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/

2. OpenAI, “Introducing ChatGPT Wallet”, 13 de noviembre de 2026: compras de agentes con tokens de pago de las redes, desarrollado con American Express, Chase, Mastercard y Visa; inicialmente a través de dots, solo tarjetas emitidas en Estados Unidos. https://openai.com/index/introducing-chatgpt-wallet/

3. Al Jazeera, “OpenAI launches ‘dots,’ personal AI assistant ‘built to handle everything’”, 30 de septiembre de 2026. https://www.aljazeera.com/economy/2026/9/30/openai-launches-dots-personal-ai-assistant-built-to-handle-everything

4. Asia Economy, “Privacy Control Concerns Become Reality Amid Craze for ‘Pickle,’ the AI That Acts on Its Own”, 9 de noviembre de 2026: agente coreano que se encarga de tareas cotidianas en KakaoTalk, Coupang, Government24 y Google; llamadas telefónicas reportadas. https://view.asiae.co.kr/en/article/2026110909414917294

5. Zapia, “Zapia: the AI agent built for Latin American life”, 18 de mayo de 2026: WhatsApp, app y web; contacto con negocios, agenda, respuestas, seguimiento de precios. https://zapia.com/blog/zapia-ai-agent-built-for-latin-american-life?lang=en

6. Xataka Colombia, “Luzia quiere ser la inteligencia artificial que todo el mundo sabe usar… y que te contesta por WhatsApp”, 10 de octubre de 2023. https://www.xataka.com.co/robotica-e-ia/luzia-quiere-ser-inteligencia-artificial-que-todo-mundo-sabe-usar-que-te-contesta-whatsapp

7. Banco Central do Brasil, “Pix”. https://www.bcb.gov.br/en/financialstability/pix_en

8. Banco de la República (Colombia), “Bre-B”. https://www.banrep.gov.co/es/bre-b

9. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, febrero de 2026. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

10. Banco Interamericano de Desarrollo, “Remittances to Latin America and the Caribbean Ease After 2025 Surge”, 16 de junio de 2026: US$173.7 mil millones en 2025. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

11. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth”, 2 de octubre de 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

12. Nubank, “Nubank leverages AI to scale Pix operations”, 10 de diciembre de 2024: Pix por voz, texto o imagen en la app y en WhatsApp. https://nu.com/en/newsroom/consumers/nubank-leverages-ai-to-scale-pix-operations

13. iProfesional, “Mercado Pago relanza Mago con IA para gestionar las finanzas”, 30 de septiembre de 2026: transferencias preparadas a partir de una conversación y confirmadas por el usuario (Argentina). https://www.iprofesional.com/finanzas/465587-mercado-pago-relanza-mago-con-ia-para-gestionar-las-finanzas

14. Iniciador, “Iniciador launches Brazil’s first agentic payments MCP on Pix”, 19 de mayo de 2026: para instituciones reguladas y fintechs; el agente propone y el usuario aprueba con biometría. https://iniciador.com.br/en/conteudos/iniciador-anuncia-pagamentos-agenticos-full-stack-ai-toolkit

15. Repositorio público de Confío en GitHub: app, backend, asistente (`assistant/`), agente de compras (`agent_tasks/`), vinculación de WhatsApp (`whatsapp_link/`), mercado, futuros perpetuos, contratos. https://github.com/caesar4321/Confio

16. Confío, registros de diseño del asistente: `docs/designs/confio-assistant.md`, `assistant-first-steps-guide.md`, `assistant-mail-calendar.md`. https://github.com/caesar4321/Confio/tree/main/docs/designs

17. Registros de socios y configuración de producción de Confío, 25 de noviembre de 2026: canales locales de recarga, retiro y pago a través de Koywe, Infinia, Pago ASAP y VEXPay, con interruptores y pausas por país.

18. Confío, especificación de Cuenta inteligente, diseño de la cuenta automática y registro de despliegue de la v2 automática (direcciones, lotes del Safe, hashes de transacciones, pruebas de regresión de la revisión): `docs/designs/cuenta-inteligente-spec.md`, `docs/designs/hands-off-account.md`, `docs/deploy/hands-off-v2-deploy.md`, `contracts/smart_account/`. https://github.com/caesar4321/Confio/tree/main/contracts/smart_account

19. Confío, “cUSD+ deployment record - BSC mainnet”, actualizado en noviembre de 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

20. Contratos BSC de Confío: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol`. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus y https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks

21. Ondo Finance, “USDY Basics”. https://docs.ondo.finance/general-access-products/usdy/basics

22. BscScan, proxy de Confío Dollar+ `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

23. Ondo Finance, “Integrating with the USDY InstantManager contract”. https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

24. Confío, `CusdPlusVault.sol`: contabilidad, redención, protección del oráculo y participación del 15% en el rendimiento. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

25. Ondo Finance, “Ondo Stocks” y documentación de la API de Global Markets. https://ondo.finance/ondo-stocks y https://docs.ondo.finance/api-reference/quickstart

26. Confío, código fuente y notas de `ConfioSwapRouter`. https://github.com/caesar4321/Confio/tree/main/contracts/crypto_swap

27. BNB Chain, introducción a BNB Smart Chain y finalidad. https://docs.bnbchain.org/bnb-smart-chain/introduction/

28. BNB Chain, comisiones de transacción y conceptos de red. https://docs.bnbchain.org/bnb-smart-chain/

29. BNB Chain, documentación del ecosistema y para desarrolladores. https://www.bnbchain.org/en/developers

30. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa”, fuente del proyecto.

31. Analítica interna de producto de Confío: 25 de noviembre de 2026 para usuarios que completaron el registro (incorporación terminada, con cualquier método; se excluyen las cuentas de prueba de la plataforma), cuentas registradas y dispositivos alcanzables por push mediante FCM (tokens de dispositivo activos; usados dentro de 30 días según el último uso registrado); 23 de julio de 2026 para la verificación de Didit y su tasa de finalización. No auditada.

32. Analítica interna del canal del fundador de Confío, 23 de julio de 2026. Aproximada; cambia con el tiempo.

### Procedencia del documento

La versión 4.5 (25 de noviembre de 2026; revisada el mismo día para incluir los resultados de las operaciones automáticas en el chat, la posibilidad de compartirlas en Comunidad y las solicitudes por voz) replantea Confío en torno a una sola tesis: un asistente personal para América Latina que termina los encargos pagando por canales locales, desde dólares en autocustodia y dentro de límites que se hacen cumplir. Agrega un panorama competitivo basado solo en fuentes públicas citadas, Cuenta inteligente, el agente de compras, Oro y Bitcoin, Futuros y Comprar; condensa la infraestructura del dólar, de inversión y del token en subsecciones de la base; actualiza la tabla de contratos según la verificación en BscScan y el estado on-chain; y actualiza las métricas operativas a partir de consultas de solo lectura en producción. Se eliminó el material anterior de la tesis de mercado sobre la dolarización, junto con sus notas.
