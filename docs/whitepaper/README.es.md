# Confío: la plataforma de dólares digitales de confianza para América Latina

**Finanzas en dólares para América Latina: dinero bajo el control del usuario, distribuido a través de la confianza.**

Confío es una aplicación financiera totalmente de código abierto y no custodial, creada para la realidad del dólar en América Latina. Combina acceso mediante moneda local, dólares que generan rendimiento, transferencias, pagos, nóminas y acceso a Ondo Stocks para usuarios elegibles en una experiencia móvil familiar, sin exigir conocimientos de cripto.

**Referencia global · Versión 4.3 · Agosto de 2026**<br>
Julian Moon · Fundador y CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Blockchain por dentro. Simple como PayPal.*

**Original autoritativo:** el [documento en inglés](README.md) es la única versión autoritativa del whitepaper de Confío. Esta traducción se ofrece por conveniencia; si difiere del inglés, prevalece el original. Traducción sincronizada con la versión 4.3 el 23 de septiembre de 2026; las fechas de los datos y del estado del producto se conservan tal como aparecen en el original.

Este documento es la referencia global actual sobre la arquitectura, estrategia, modelo operativo y riesgos materiales de Confío. Las condiciones detalladas de asignación y vesting de $CONFIO se encuentran en el documento separado de tokenomics.

<details>
<summary><strong>Contenido</strong></summary>

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Tesis de mercado](#2-tesis-de-mercado)
3. [El sistema de productos en BNB Smart Chain](#3-el-sistema-de-productos-en-bnb-smart-chain)
4. [Por qué BNB Smart Chain](#4-por-qué-bnb-smart-chain)
5. [cUSD y cUSD+: dinero y ahorro](#5-cusd-y-cusd-dinero-y-ahorro)
6. [Pagos, nóminas y Ondo Stocks](#6-pagos-nóminas-y-ondo-stocks)
7. [$CONFIO en BNB Smart Chain](#7-confio-en-bnb-smart-chain)
8. [Billetera, seguridad y arquitectura abierta](#8-billetera-seguridad-y-arquitectura-abierta)
9. [Usuarios, distribución y entrada al mercado](#9-usuarios-distribución-y-entrada-al-mercado)
10. [Modelo de negocio](#10-modelo-de-negocio)
11. [Cumplimiento y modelo operativo](#11-cumplimiento-y-modelo-operativo)
12. [Riesgos y mitigaciones](#12-riesgos-y-mitigaciones)
13. [Hoja de ruta y estado actual](#13-hoja-de-ruta-y-estado-actual)
14. [Aviso legal](#14-aviso-legal)
15. [Notas](#notas)

</details>

---

## 1. Resumen ejecutivo

Confío es una aplicación de dólares digitales totalmente de código abierto y no custodial para América Latina. Ofrece una interfaz móvil familiar para mantener, ahorrar, enviar y gastar, sin tener que gestionar tokens de gas, memorizar direcciones blockchain ni navegar pantallas de exchange. <sup>[3]</sup>

> **Tesis de producto**
>
> La plataforma de dólares para consumidores que triunfe en América Latina no exigirá convertirse en experto en cripto. Combinará propiedad verificable on-chain con la claridad, los mecanismos de recuperación, los métodos de pago locales y el soporte humano que se esperan de una fintech moderna. La competencia no se decidirá por tener las mismas funciones, sino por distribución, confianza y adaptación local. Confío parte de un canal en español liderado por su fundador con aproximadamente 480,000 personas, una relación pública de años con la región a la que sirve y un gasto en medios pagados prácticamente nulo hasta la fecha.

El sistema de productos de Confío se liquida ahora íntegramente en BNB Smart Chain:

| Componente | Función principal | Diseño |
| --- | --- | --- |
| USDT | Activo externo de fondeo, liquidez y salida. | Los BSC-USDT entrantes se convierten automáticamente mientras la aplicación está activa. La interfaz de consumo no presenta un saldo ordinario de USDT sin convertir. |
| cUSD | Dólar universal para pagos. | Token BSC actualizable y respaldado 1:1 por USDT, destinado a pagos y a usuarios no elegibles para exposición a USDY. Es el único perímetro de cobro de la comisión externa de conversión del 0.9%. |
| cUSD+ | Instrumento de ahorro en dólares para usuarios elegibles. | Participaciones acumulativas respaldadas por USDY, con contrato actualizable, para usuarios elegibles según Ondo. La conversión interna cUSD↔cUSD+ no tiene comisión y requiere patrocinio autorizado. |
| Ondo Stocks | Acceso elegible a mercados tokenizados. | Los usuarios compran desde cUSD+ y reciben los ingresos de sus ventas nuevamente en cUSD+ mediante un router dedicado cuyo código está verificado. Cada compra y venta completada tiene una comisión explícita de Confío del 0.30%. |
| $CONFIO | Token comunitario y del ecosistema. | BEP-20 de oferta fija en BNB Smart Chain, con preventa on-chain pagada en cUSD. No respalda los saldos en dólares de los usuarios. |

El diseño de una sola red no es una apuesta genérica por una blockchain. Sigue el centro económico del producto: Ondo Finance puso USDY, InstantManager, el oráculo de precios y la ruta de suscripción y redención en USDT a disposición de BNB Smart Chain. Confío consolidó después pagos, nóminas, transferencias y $CONFIO en esa misma red para eliminar los cambios de cadena y la fragmentación de liquidez. <sup>[7, 8, 10]</sup>

Al 23 de julio de 2026, Confío registra 8,004 usuarios con verificación telefónica completada y 177 que completaron la verificación de identidad de Didit presentando un documento oficial y una selfie en vivo para las comprobaciones de presencia real y coincidencia facial. El 61.5% de quienes iniciaron el flujo Didit lo completaron. También se registran 2,094 dispositivos alcanzables mediante notificaciones push, de los cuales 2,092 se utilizaron en los últimos 30 días. Son métricas operativas internas, no cifras auditadas independientemente, y no deben interpretarse como usuarios con fondos ni usuarios activos mensuales. <sup>[14]</sup>

Los vaults de cUSD y cUSD+, el router de Ondo Stocks, el delegado de transacciones patrocinadas, el token $CONFIO, el vault de preventa de reemplazo, el vault de recompensas, el contrato de pagos a comercios y el vault de nóminas están desplegados y tienen su código fuente verificado en BNB Smart Chain. Están conectados a la aplicación de producción, con controles de ejecución que regulan la exposición gradual a usuarios. El vault cUSD+ está registrado en la infraestructura con permisos de Ondo e integra los contratos de producción de USDY, USDT, InstantManager y el oráculo. <sup>[8, 9, 17, 18]</sup>

## 2. Tesis de mercado

### 2.1 Un problema de acceso al dólar, no de conocimiento de cripto

América Latina no atraviesa una única crisis monetaria homogénea. Algunos usuarios buscan protección frente a la volatilidad de su moneda; otros necesitan liquidación transfronteriza asequible, un lugar seguro para ahorrar en dólares o una forma práctica de pagar y cobrar. Los conecta la demanda de una unidad de cuenta confiable en dólares y el descontento con las fricciones de acceso. La adopción regional de stablecoins muestra que este comportamiento ya existe on-chain y no es meramente teórico. <sup>[2]</sup>

| Mercado | Necesidad observada | Implicación para el producto |
| --- | --- | --- |
| Argentina | La inflación y los controles de capital recurrentes, junto con la memoria del *corralito* de 2001 y la conversión forzosa de depósitos en dólares, enseñaron a valorar acceso y control tanto como rendimiento nominal. La mayoría de las restricciones cambiarias recientes se flexibilizaron, pero el déficit histórico de confianza sigue siendo relevante. <sup>[19]</sup> | Un producto en dólares debe explicar con especial claridad los límites de custodia, derechos de retiro, precios y cambios de reglas. |
| Venezuela | La inflación extrema convirtió al dólar en reserva de valor y medio de pago cotidiano, en una economía muy dolarizada pero operativamente fragmentada. <sup>[20]</sup> | El acceso y los pagos en dólares son necesidades inmediatas, mientras sanciones, disponibilidad de proveedores y cumplimiento exigen controles más estrictos. |
| Bolivia | La evaluación del FMI de 2025 describió reservas utilizables de divisas próximas a cero, una brecha cambiaria paralela creciente y fuertes límites al acceso privado a dólares al tipo oficial. <sup>[21]</sup> | Acceso confiable, precios locales transparentes y QR interoperables pueden resolver un problema diario de liquidez, no un uso especulativo. |
| Perú | Los hogares ya mantienen decenas de miles de millones de dólares en depósitos en moneda extranjera; Yape, PLIN y los sistemas QR interoperables han normalizado los pagos móviles. <sup>[22]</sup> | No se trata de enseñar a desear dólares, sino de ofrecer ahorro y pagos portátiles con entradas locales familiares. |
| México | Los depósitos bancarios en moneda extranjera y aproximadamente US$62.5 mil millones de remesas anuales demuestran demanda de ahorro en dólares y de transferencias internacionales. <sup>[23]</sup> | SPEI, saldos en dólares, rendimiento y transferencias familiares pueden convivir en un producto de consumo. |
| Colombia | Estados Unidos origina más de la mitad de las remesas entrantes; Colombia acoge a unos 2.8 millones de venezolanos. <sup>[24, 25]</sup> | PSE, Nequi y la banca local pueden conectar remesas internacionales con el corredor familiar Colombia–Venezuela. |
| Estados Unidos y España | Son dos de los mercados de origen más importantes de las remesas latinoamericanas. Estados Unidos representa el 35.7% de las entradas a Sudamérica; Europa, el 36.2%, incluidos 19.7 puntos porcentuales de España. <sup>[24]</sup> | Tarjetas y SEPA deben conectar los ingresos de la diáspora con los saldos en dólares de sus destinatarios sin obligar a ambas partes a usar un producto de trading. |

El resultado es un **reflejo hacia el dólar**: se busca exposición al USD incluso cuando el acceso es caro, informal u operativamente frágil.

### 2.2 Las remesas como oportunidad para mantener saldos

América Latina y el Caribe recibieron aproximadamente US$173.7 mil millones en remesas en 2025. <sup>[1]</sup> La mayoría de los productos trata cada remesa como una transferencia aislada. Confío la considera el inicio de una relación financiera: el destinatario puede conservar dólares, generar rendimiento variable mediante cUSD+, enviar a contactos, pagar a un comercio o retirar por un canal local.

El objetivo pasa de mover dinero una vez a mantener saldos de confianza a lo largo del tiempo.

### 2.3 La convergencia de las finanzas de consumo

Exchanges, fintechs, billeteras y empresas de stablecoins convergen hacia productos similares: saldos en dólares, rendimiento, tarjetas, transferencias y activos tokenizados. A medida que se asemejan sus funciones, muchos competidores recurren al cashback o a subsidios de adquisición para atraer a los mismos usuarios familiarizados con cripto. Confío compite mediante un canal de distribución y una relación de confianza local difíciles de replicar, junto con canales específicos por país en lugar de una interfaz global genérica. <sup>[15, 16]</sup>

### 2.4 El problema más profundo: falta de confianza

Los usuarios latinoamericanos han vivido congelamientos bancarios, controles cambiarios, fintechs fallidas, intermediarios informales, diferenciales ocultos y plataformas cripto orientadas a la especulación. El problema resultante no es solo el acceso financiero: es la falta de confianza.

La respuesta de Confío tiene dos capas:

1. **Control verificable:** la clave de la billetera se genera en el dispositivo del usuario y Confío no la conserva.
2. **Confianza humana:** educación primero en español, precios claros, métodos de pago locales, liderazgo visible y soporte que entiende el contexto del usuario.

*Lo tuyo, tuyo* es, por tanto, una promesa de marca y una restricción de arquitectura.

## 3. El sistema de productos en BNB Smart Chain

Confío presenta una experiencia unificada en dólares, utilizando activos distintos para funciones distintas dentro de la misma red.

| Acción | Activo o contrato | Qué ocurre on-chain |
| --- | --- | --- |
| Agregar dólares | cUSD o cUSD+ | Un proveedor fiat o una billetera externa entrega BSC-USDT. La aplicación los convierte automáticamente en cUSD para usuarios no elegibles según Ondo, o cUSD+ para elegibles, con la misma comisión de conversión de Confío del 0.9%. |
| Ahorrar | Conversión interna cUSD↔cUSD+ | Los usuarios elegibles pasan cUSD a cUSD+ respaldado por USDY sin comisión de conversión; la operación interna inversa también es gratuita. Ambas requieren una transacción patrocinada por Confío. |
| Enviar | cUSD o cUSD+ | Las transferencias entre usuarios con la misma elegibilidad conservan el activo del remitente. Si la elegibilidad difiere, se convierte internamente sin comisión para entregar el activo adecuado a la jurisdicción del destinatario. |
| Pagar a un comercio | cUSD+, cUSD o $CONFIO | El contrato paga al comercio, aplica la comisión independiente de Pay del 0.9% y registra las comisiones acumuladas on-chain. USDT sin convertir permanece en la lista permitida por compatibilidad heredada, pero el backend de producción no autoriza su uso. |
| Pagar nóminas | cUSD+ o cUSD | Las empresas fondean depósitos en garantía separados por activo; delegados autorizados firman los pagos y los destinatarios reciben cUSD+ o cUSD según elegibilidad. |
| Comprar o vender Ondo Stocks | cUSD+, token de Ondo Stocks y router | Una transacción patrocinada liquida mediante Ondo Global Markets. Las compras redimen el cUSD+ necesario a USDT y entregan el token al usuario; las ventas devuelven los ingresos netos a cUSD+. |
| Participar en la preventa $CONFIO | cUSD | Una transacción patrocinada compra una asignación sobre una curva inmutable on-chain sin obligar a una redención adicional cUSD/cUSD+→USDT. |
| Obtener y reclamar recompensas | RewardVault de $CONFIO | Las recompensas elegibles se registran acumulativamente fuera de la cadena y se reclaman mediante autorizaciones firmadas on-chain después del desbloqueo DEX. |

### 3.1 Despliegues públicos en BNB Smart Chain

Todos los contratos siguientes están activos en la red principal de BNB Smart Chain y tienen código fuente verificado. Las direcciones de reemplazo de preventa, recompensas, pagos a comercios y nóminas están configuradas en la aplicación de producción.

| Contrato | Dirección |
| --- | --- |
| Proxy del vault cUSD | [`0x6101cC370635cF2c7f2725EaB010aC407A8d543F`](https://bscscan.com/address/0x6101cC370635cF2c7f2725EaB010aC407A8d543F#code) |
| Proxy del vault cUSD+ | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Router Ondo Stocks (proxy UUPS) | [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code) |
| Delegado de lotes patrocinados | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| Token $CONFIO | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| Vault de preventa $CONFIO | [`0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358`](https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code) |
| Vault de recompensas $CONFIO | [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code) |
| Vault de vesting $CONFIO | [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| Escrow de invitaciones | [`0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59`](https://bscscan.com/address/0xe6c49CcEb57b86dfE2F597053f8f475F18AcDb59#code) |
| Contrato de pagos comerciales | [`0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA`](https://bscscan.com/address/0x942BF5F3C9079Ab29492324B9F1E501Db5B830bA#code) |
| Vault de nóminas | [`0x851e1a56De5c0ADBB75e904B2E7325e132692027`](https://bscscan.com/address/0x851e1a56De5c0ADBB75e904B2E7325e132692027#code) |

### 3.2 Por qué importa una sola red

La consolidación elimina tres fricciones recurrentes:

- no se necesita un puente entre el saldo principal en dólares, ahorro, pagos, nóminas y $CONFIO;
- una dirección EVM puede recibir el fondeo, los saldos de productos y el token del ecosistema; y
- un sistema de transacciones patrocinadas puede pagar las comisiones de red en todo el producto.

Siguen vigentes la elegibilidad y las reglas de cada proveedor. Una cadena unificada no hace que todos los activos sean económica o jurídicamente idénticos.

### 3.3 Acceso local e internacional

Koywe ofrece canales locales activos en siete mercados latinoamericanos, con combinaciones de transferencias bancarias, Alias/CVU, SPEI, QR interoperables, PSE/Nequi y PIX según país y método. Guardarian ofrece SEPA en la eurozona y compras en USD mediante Visa, Mastercard, Apple Pay y Google Pay. Los proveedores adicionales se integran solo tras confirmar capacidades comerciales y de producción. <sup>[13]</sup>

## 4. Por qué BNB Smart Chain

### 4.1 El producto siguió la infraestructura de Ondo

El motivo principal es Ondo Finance. Confío no eligió primero una red para después buscar productos financieros. cUSD+ se diseñó alrededor de USDY, y Ondo desplegó en BNB Smart Chain el token USDY de producción, InstantManager, el oráculo de precios, la ruta USDT de suscripción y redención y la infraestructura de liquidación de Global Markets. Situar el sistema de Confío junto a esa infraestructura ofrece rutas directas al ahorro respaldado por USDY y al acceso elegible a Ondo Stocks. <sup>[7, 8, 10, 18]</sup>

### 4.2 Economía y liquidez a escala de consumo

BNB Smart Chain aporta:

- amplia liquidez de USDT e infraestructura EVM familiar;
- bajos costos de transacción adecuados para actividad de consumo patrocinada;
- billeteras, proveedores RPC, exploradores, exchanges y herramientas maduras;
- acceso al ecosistema de pagos, billeteras, DeFi y activos del mundo real (RWA) de BNB Chain; y
- un entorno para cUSD, cUSD+, USDT, $CONFIO, pagos comerciales y nóminas. <sup>[5, 6, 12]</sup>

El tamaño del ecosistema no crea demanda por sí solo. El valor de Confío sigue dependiendo de usuarios, saldos retenidos, salidas confiables, distribución, seguridad y economía transparente.

### 4.3 Contrapartidas de red y gobernanza

BNB Smart Chain tiene características operativas y de descentralización diferentes de otras redes. Son posibles interrupciones, coordinación de validadores, congestión, cambios del precio del gas, fallas RPC y cambios de políticas del ecosistema. Confío mitiga estos riesgos mediante patrocinio, múltiples rutas RPC, salidas de emergencia explícitas, propiedad no custodial y estado público de contratos, pero no elimina el riesgo de la red base.

## 5. cUSD y cUSD+: dinero y ahorro

cUSD es el dólar universal para pagos, respaldado 1:1 por USDT en su vault UUPS desplegado. cUSD+ es una participación acumulativa de ahorro denominada en dólares, respaldada por USDY en el proxy cUSD+ existente y actualizado. La aplicación selecciona cUSD para quienes no son elegibles para exposición a USDY y cUSD+ para quienes sí lo son, mostrando una experiencia en dólares en lugar de participaciones, gas, aprobaciones o cálculos de oráculo.

### 5.1 Depósito y redención

| Entrada | Salida |
| --- | --- |
| 1. USDT llega a la dirección BSC del usuario desde un proveedor fiat o una billetera externa. | 1. El usuario solicita retirar a moneda local o enviar USDT al exterior. |
| 2. Un lote patrocinado autorizado por el usuario llama a la ruta de acuñación con comisión correspondiente. | 2. Se quema cUSD directamente, o se quema cUSD+ y se redime USDY mediante InstantManager. |
| 3. El perímetro de comisiones cUSD retiene el 0.9% y acuña cUSD, o devuelve USDT neto a cUSD+ para suscribir USDY. | 3. El perímetro cUSD retiene el 0.9% del valor bruto de salida. |
| 4. El usuario recibe cUSD si no es elegible según Ondo, o cUSD+ si lo es. | 4. El USDT neto se envía a la dirección designada de la billetera externa o del proveedor fiat. |

El vault cUSD es el único perímetro externo de comisión de conversión. El código limita la comisión a 90 puntos básicos. La acuñación siempre requiere un patrocinador autorizado; la redención sin comisión se restringe a la conversión con el ahorro cUSD+; la redención ordinaria con comisión no requiere permisos, para que el titular pueda salir sin el patrocinador de Confío. cUSD+ sigue el mismo principio: acuñación normal e intercambio interno gratuito requieren patrocinador, pero redimir a USDT pagando la comisión no requiere permisos.

El comprador autorizado de USDY es el vault cUSD+, no el usuario final. Los usuarios poseen cUSD+, no USDY directamente. La acuñación está sujeta a elegibilidad. La conversión interna cUSD↔cUSD+ es gratuita porque el valor permanece dentro del sistema de dólares de Confío; no crea una ruta externa gratuita hacia USDT.

### 5.2 Valor acumulativo y participación en el rendimiento

El precio de referencia de USDY está diseñado para aumentar al acumularse el rendimiento subyacente. En cada interacción pertinente, el vault actualiza el valor de referencia de cUSD+:

- el 85% de la apreciación positiva del precio de referencia de USDY incrementa el valor de referencia para el titular de cUSD+; y
- el 15% se convierte en excedente del vault disponible para Confío.

No aumenta el número de participaciones, sino el valor de referencia en dólares por participación cUSD+. El rendimiento es variable, puede cambiar y no está garantizado. <sup>[7, 11]</sup>

### 5.3 Respaldo y controles del oráculo

El vault permite consultar públicamente obligaciones totales, ratio de respaldo y excedente. Su contabilidad redondea a favor del respaldo y limita el cobro de comisiones al excedente demostrable. El propietario no puede retirar indiscriminadamente el USDY de respaldo.

Si el oráculo de USDY baja o se mueve más allá del umbral configurado, se detienen las rutas que mueven valor. La gobernanza multiparte debe registrar una decisión vinculada a evidencia para aceptar una apreciación verificada o restablecer la referencia tras una falla verificada del oráculo. Esto reduce el riesgo de precios erróneos automáticos, sin eliminar riesgos de oráculo, emisor o gobernanza.

### 5.4 Una experiencia de saldo según elegibilidad

cUSD+ es la representación preferida para usuarios elegibles porque puede seguir acumulando valor hasta gastarse. cUSD es la representación universal para quienes no pueden recibir exposición a USDY. Las transferencias entre amigos con igual elegibilidad son directas; si difiere, el flujo patrocinado convierte internamente entre cUSD y cUSD+ sin cobrar el 0.9% externo. USDT sin convertir es un intermediario de entrada/salida y un activo de emergencia, no un saldo ordinario seleccionable en la interfaz de consumo.

## 6. Pagos, nóminas y Ondo Stocks

### 6.1 Transferencias entre personas

El servidor prepara las llamadas exactas, el usuario las firma y Confío paga el gas. Según el saldo del remitente y la elegibilidad del destinatario:

- cUSD+ se transfiere directamente a un destinatario Confío elegible;
- cUSD se transfiere directamente a quien corresponda mantener cUSD; o
- una conversión cUSD↔cUSD+ autorizada por el patrocinador y sin comisión entrega la representación adecuada cuando difiere la elegibilidad.

Confío no cobra comisión de plataforma por transferencias entre personas. La comisión del 0.9% solo se aplica cuando el valor entra desde USDT o sale hacia USDT, independientemente de si ese USDT procede de un proveedor fiat o una billetera on-chain, o se dirige a ellos.

### 6.2 Pagos a comercios

Un comercio cobra en **dólares Confío** o **$CONFIO**, expresado como cantidad de tokens y no como importe en dólares. La liquidación en dólares utiliza cUSD+ o cUSD según la ruta del pagador y del comercio.

El contrato conserva USDT sin convertir únicamente por compatibilidad heredada. Una vez habilitado el perímetro de conversión, el backend no autoriza llamadas Pay en USDT sin convertir, impidiendo eludir la comisión obligatoria USDT↔cUSD a través de Pay.

El contrato calcula la comisión comercial del 0.9%, paga directamente el importe neto al comercio y acumula solo comisiones devengadas para su cobro transparente. El backend firma una autorización de corta vigencia con los términos exactos, y el contrato registra la liquidación contra el identificador de factura. Solo un pago puede liquidar cada factura; nadie sin autorización del backend puede consumir su identificador. Cada factura registra además la única red permitida para liquidarla, evitando pagos duplicados entre redes. Aprobación y pago se ejecutan atómicamente en un lote patrocinado.

### 6.3 Nóminas y pagos masivos

Las empresas pueden mantener capital de trabajo en cUSD+ o cUSD en depósitos en garantía separados por activo y autorizar delegados para firmar pagos específicos. Los destinatarios elegibles reciben cUSD+; los no elegibles reciben cUSD mediante la conversión interna gratuita. Un pool heredado de USDT sin convertir permanece solo para vaciar o migrar depósitos antiguos; la contabilidad de comisiones de nómina se mantiene separada del principal empresarial.

### 6.4 Ondo Stocks

Confío integra acceso elegible a Ondo Stocks mediante Ondo Global Markets en BNB Smart Chain. El proxy UUPS dedicado `ConfioStockRouter` está desplegado y verificado en [`0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`](https://bscscan.com/address/0x40c8e134BCAf44EEf9e7D184846F36c9862329c3#code). La autoridad de actualización corresponde al mismo Safe de 3 de 5 que lo posee, permitiendo migraciones de liquidación de Ondo sin cambiar la dirección del comprador autorizado. El acceso sigue sujeto a elegibilidad Ondo, jurisdicción, disponibilidad de mercados, términos del proveedor y controles de activación gradual de Confío. <sup>[17, 18]</sup>

El router conecta las operaciones directamente con el saldo cUSD+:

- **Compra:** redime la cantidad autorizada de cUSD+ a USDT, retiene la comisión explícita, liquida la compra certificada mediante Ondo Global Markets y entrega el token directamente a la billetera del usuario.
- **Venta:** vende el token autorizado mediante Ondo Global Markets, descuenta la comisión explícita de los ingresos efectivos en USDT y vuelve a suscribir el neto en cUSD+ para el usuario.

Cada compra y venta completada cobra **30 puntos básicos (0.30%)** fijos en USDT. La tasa es fija en la implementación actual; cambiar la implementación exige al Safe propietario. La transacción autorizada incluye un límite máximo de comisión, y cualquier exceso de USDT debido a movimientos del precio cUSD+ o conversiones de liquidación se devuelve, en lugar de retenerse como segunda comisión oculta. El router contabiliza por separado las comisiones devengadas y no conserva principal ni tokens de acciones tras una liquidación exitosa.

## 7. $CONFIO en BNB Smart Chain

$CONFIO es el token comunitario y del ecosistema Confío. No es una stablecoin, no representa un depósito bancario y no respalda USDT, cUSD+ ni USDY.

### 7.1 Token de oferta fija

El contrato actual tiene una oferta inicial fija de 1,000,000,000 CONFIO. No tiene propietario, función de emisión posterior al despliegue ni función de pausa; toda la oferta se creó una sola vez para la tesorería multiparte. Sus únicas extensiones son ERC-20 permit y quema voluntaria: la oferta puede disminuir, pero no aumentar. <sup>[17]</sup>

**Contrato BSC canónico:** [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8)

El nombre on-chain utiliza deliberadamente el ASCII **“Confio”**; **“Confío”**, con tilde, sigue siendo el nombre del producto y la marca. Así se evitan inconsistencias de escape HTML y presentación de metadatos no ASCII entre exploradores, billeteras y exchanges descentralizados. Debe utilizarse únicamente la dirección canónica anterior. <sup>[17]</sup>

Asignaciones, propiedad del fundador, vesting, derechos de preventa y concentración se divulgan en el documento autoritativo de tokenomics en inglés. La asignación del fundador sigue siendo su asignación; custodiarla en una tesorería de distribución no la convierte en una reserva indefinida del ecosistema.

### 7.2 Preventa on-chain

El vault BSC de reemplazo acepta cUSD y calcula las compras mediante una curva lineal por tramos, inmutable y vinculada a los tokens vendidos acumulados:

| Asignación acumulada de preventa | Precio de la curva |
| --- | --- |
| 0–4 millones de CONFIO | US$0.20 → US$0.30 |
| 4–24 millones de CONFIO | US$0.30 → US$0.70 |
| 24–74 millones de CONFIO | US$0.70 → US$1.30 |

Los tramos no admiten cambios administrativos de precio. El contrato cobra la integral bajo la curva, registra asignaciones, impide descuentos por dividir compras mediante su matemática y abre reclamos solo con suficiente fondeo CONFIO. Participar sigue sujeto a elegibilidad, controles geográficos y términos de preventa. <sup>[17]</sup>

El contrato de reemplazo se inicializó con el historial exacto previo al despliegue: las compras migradas mantienen la posición acumulada de la curva, sin reiniciar el precio. Está fondeado para las obligaciones migradas; el vault reemplazado está pausado.

**Contrato de preventa:** [`0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358`](https://bscscan.com/address/0x8c3A1fffcFfE1B07108486Be85C0dC42B4aC0358#code)

### 7.3 Recompensas y reclamos bloqueados hasta DEX

El sistema separa acumulación y distribución. Al habilitarse, la actividad elegible se registra en la base de datos y las recompensas denominadas en dólares se convierten a CONFIO al precio actual de la curva on-chain. Esto evita mantener manualmente un precio y no mueve tokens on-chain antes del lanzamiento DEX.

Al reclamar, el firmante del backend emite una autorización EIP-712 de corta vigencia por el total acumulado ganado. RewardVault resta lo ya reclamado y paga solo la diferencia; el total acumulado protege contra reutilizaciones. Los plazos cortos limitan la vigencia de una firma si un derecho debe corregirse a la baja.

Los reclamos están bloqueados hasta DEX. Antes de abrirlos, la tesorería multiparte debe fondear un tramo CONFIO, activar el firmante y el flujo del cliente, y ejecutar la función irreversible `unlockClaims()`. Después, los usuarios pueden reclamar mediante transacciones patrocinadas.

> **Pool de recompensas controlado por tesorería**
>
> RewardVault no es un depósito en garantía sin necesidad de confianza. Los derechos de recompensa siguen siendo obligaciones discrecionales de tesorería: su propietario de gobernanza puede rotar el firmante, pausar reclamos y retirar fondos incluso después del desbloqueo DEX irreversible. Los usuarios dependen de que la tesorería concilie obligaciones, fondee el pool y mantenga disponibles los reclamos válidos. Plazos cortos y fondeo por tramos operativos limitan la exposición del firmante, pero no eliminan esa dependencia de confianza.

**RewardVault canónico:** [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code)

## 8. Billetera, seguridad y arquitectura abierta

### 8.1 Modelo no custodial

La clave EVM se genera en el dispositivo del usuario. El servidor de Confío no conserva esa clave privada. El material cifrado de recuperación está diseñado para la nube personal del usuario, evitando que Confío mantenga un repositorio central de claves. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío nunca conserva la clave de la billetera y, por tanto, no puede firmar una transacción ordinaria como si fuera ese usuario. Los contratos de producto y activos emitidos conservan sus propios controles divulgados de elegibilidad, pausa, congelamiento, actualización o gobernanza. Claves no custodiales no significan productos financieros sin controles.

### 8.2 Transacciones patrocinadas

Los usuarios no necesitan adquirir BNB para los flujos normales. Confío emplea autorizaciones EIP-7702 y un delegado de lotes desplegado sin propietario: el usuario firma las llamadas previstas y el patrocinador paga gas. Aprobaciones y acciones pueden ejecutarse atómicamente, reduciendo el riesgo de autorizaciones de gasto permanentes. <sup>[8, 17]</sup>

El patrocinador no puede elegir llamadas arbitrarias. La política del servidor restringe destinos, selectores, montos, destinatarios, vencimientos y límites diarios antes de transmitir. Las alternativas de emergencia y salidas directas son importantes porque el patrocinio es un servicio de aplicación, no una garantía blockchain.

### 8.3 Código abierto y verificabilidad pública

Aplicación móvil, backend, contratos, registros de despliegue y pruebas son públicos. Donde se admite, los contratos desplegados tienen verificación de fuente, permitiendo comparar código público con bytecode activo. <sup>[3, 8, 9, 17]</sup>

La seguridad se busca mediante verificabilidad abierta y controles conservadores, no mediante ocultamiento:

- pruebas unitarias, de fork, invariantes/fuzz, adversariales, diferenciales y ensayos de actualización;
- código y registros de despliegue públicos;
- gobernanza multiparte para operaciones privilegiadas;
- cobro limitado de comisiones y respaldo que no puede retirarse indiscriminadamente;
- protecciones de oráculo, pausas, protección contra reutilización, límites de deslizamiento y salidas de emergencia explícitas; y
- indicadores de activación y límites de despliegue gradual en producción.

Ningún método de revisión elimina los riesgos contractuales u operativos.

### 8.4 Actualización y gobernanza

Los vaults cUSD y cUSD+ siguen siendo actualizables. cUSD+ depende permanentemente de contratos externos Ondo que pueden migrar o cambiar; cUSD es el perímetro compartido de pagos y comisiones entre productos. La inmutabilidad irreversible podría dejar usuarios bloqueados o perpetuar una falla de integración general. Las actualizaciones se controlan mediante gobernanza multiparte, implementaciones públicas, verificaciones de disposición de almacenamiento e historial verificable.

Otros componentes tienen diseños más limitados cuando corresponde. El token $CONFIO y la curva de preventa no son actualizables; los contratos de reemplazo de pagos, nóminas, invitaciones y preventa limitan la administración a operaciones definidas, como pausar actividad nueva, rotar patrocinadores o cobrar comisiones demostrablemente devengadas.

## 9. Usuarios, distribución y entrada al mercado

### 9.1 Métricas operativas actuales

| Métrica | Instantánea | Definición |
| --- | ---: | --- |
| Verificación telefónica completada | 8,004 | Usuarios que completaron la verificación telefónica. |
| Usuarios verificados por Didit | 177 | Usuarios que presentaron documento oficial y completaron selfie en vivo, prueba de presencia real y coincidencia facial. |
| Finalización de identidad | 61.5% | Proporción que completó Didit entre quienes iniciaron el flujo. |
| Dispositivos alcanzables por push | 2,094 | Dispositivos actualmente accesibles mediante notificaciones push. |
| Utilizados en los últimos 30 días | 2,092 | Dispositivos alcanzables registrados como usados en los 30 días previos; no se presenta como MAU estandarizado. |

Estas métricas internas no están auditadas y corresponden al 23 de julio de 2026. No implican que todos tengan fondos, estén activos, sean elegibles para todo producto o sean únicos entre todas las mediciones de dispositivos. <sup>[14]</sup>

### 9.2 La confianza es el canal de distribución

La audiencia del fundador en español suma aproximadamente 480,000 personas entre plataformas. La ventaja no es solo la cifra de seguidores, sino la capacidad de explicar productos financieros de forma reiterada, pública y en el lenguaje cultural del usuario objetivo. <sup>[15]</sup>

> **Distribución + confianza + adaptación local**
>
> Confío no pretende ganar ofreciendo más cashback permanentemente. Busca convertir una audiencia que confía en usuarios verificados, saldos fondeados, ahorro retenido, pagos recurrentes y referidos, con gasto en medios pagados prácticamente nulo hasta la fecha.

El embudo se mide desde alcance del contenido hasta instalación, verificación telefónica, identidad, primer fondeo, saldo retenido, depósito o transacción repetidos y referido. Las cohortes por país importan más que una cifra global de registros.

### 9.3 Despliegue por país

Confío no ofrece todas las funciones en todos los países. Métodos fiat, identidad, elegibilidad USDY, sanciones, retiros y soporte varían. El despliegue sigue capacidades verificadas y preparación jurídica y operativa, no una bandera en una página promocional.

## 10. Modelo de negocio

Confío vincula ingresos con actividad financiera útil, no con trading especulativo.

| Fuente de ingresos | Política actual |
| --- | --- |
| Entrada al sistema de dólares Confío | Comisión de conversión del 0.9% al pasar USDT a cUSD o cUSD+, tanto desde proveedor fiat como transferencia on-chain. Misma tasa para personas y empresas. |
| Salida del sistema | Comisión de conversión del 0.9% al pasar cUSD o cUSD+ a USDT externo, hacia proveedor fiat o billetera on-chain. Misma tasa para personas y empresas. |
| Transferencias personales y ahorro interno | Comisión de plataforma del 0% en envíos internos y conversión cUSD↔cUSD+ autorizada por patrocinador. Comisiones de red patrocinadas. |
| Pagos comerciales | Comisión plana de plataforma del 0.9%, aplicada por contrato. |
| Nóminas y pagos masivos | Comisión plana del 0.9%, con participaciones de comisión acumuladas aparte de los fondos empresariales en garantía. |
| Rendimiento cUSD+ | 15% de la apreciación positiva del precio de referencia USDY para Confío y 85% para el valor de referencia del titular cUSD+. Rendimiento variable y no garantizado. |
| Ondo Stocks | Comisión explícita fija del 0.30% por cada compra y venta completada, cobrada en USDT por el router desplegado. Pueden aplicarse aparte precios del proveedor, diferenciales, impuestos u otros costos de terceros divulgados. |
| Economía de canales fiat | Pueden aplicarse precios de Koywe y participación en ingresos de Guardarian según cotización vigente y acuerdo pertinente. |
| Otros productos financieros | Posibles comisiones o participación en ingresos de otros socios elegibles de RWA, corretaje, tarjetas o servicios empresariales, sujetos a condiciones y aprobaciones separadas. |

La regla coincide con la web pública: **0.9% para entrar, 0% para mover dentro y 0.9% para salir**. Confío Pay tiene una comisión de servicio independiente del 0.9%. Tipos de cambio y cargos de terceros se divulgan por separado cuando corresponda. Patrocinar la red es un costo del producto, no prueba de que toda acción sea económicamente gratuita.

Los clientes actuales compatibles muestran comisión e importe final antes de confirmar. Durante la transición de las tiendas, una versión antigua ya instalada puede aún mostrar “Comisión de Confío — Gratis”, aunque servidor y contratos apliquen el 0.9% y devuelvan el neto correcto. Estas versiones permanecen operativas durante esta breve ventana de compatibilidad, en lugar de bloquear acceso mientras se espera la revisión de la tienda.

## 11. Cumplimiento y modelo operativo

La arquitectura separa custodia de claves y obligaciones de productos y proveedores. Una billetera no custodial puede integrar activos con permisos, verificación de identidad, controles de sanciones, proveedores fiat y controles contractuales.

**Conoce a tu cliente (KYC, Know Your Customer)** comprende las verificaciones para establecer quién es el usuario y, cuando se requiere, dónde reside. **Prevención del lavado de dinero (AML, Anti-Money Laundering)** comprende controles de proveedores y transacciones destinados a detectar o prevenir infracciones de sanciones, fraude, lavado, financiación del terrorismo y otras actividades prohibidas. Las verificaciones dependen del producto, entidad jurídica, ubicación, transacción y socio.

> **Arquitectura integrada con proveedores**
>
> Confío está diseñada para que custodia fiat, conversión monetaria, identidad y acceso a activos con permisos sean realizados por los proveedores correspondientes, no por el software de billetera. Esto describe el diseño operativo; no afirma que Confío carezca de obligaciones legales o de cumplimiento.

- Didit respalda el flujo actual: documento oficial y selfie en vivo, con comprobaciones documentales, de presencia real y coincidencia facial.
- El domicilio es un requisito separado del proveedor. Para Koywe, Confío solicita que el usuario introduzca su dirección y la envía con su consentimiento para verificación por Koywe. <sup>[13]</sup>
- Koywe aplica sus propios controles de identidad, dirección, elegibilidad, sanciones y transacciones en sus canales locales. <sup>[13]</sup>
- El alta de Guardarian para SEPA y tarjetas incluye domicilio y sigue sus controles de identidad, elegibilidad, método, sanciones y transacciones. <sup>[13]</sup>
- Completar teléfono o Didit no garantiza aprobación del usuario o transacción por Koywe, Guardarian, Ondo u otro proveedor.
- La acuñación USDY está limitada por requisitos Ondo de elegibilidad, geografía, dirección y cumplimiento. <sup>[7, 10]</sup>
- Ondo Stocks tiene requisitos separados de Global Markets: elegibilidad, disponibilidad de activos y mercados, jurisdicción, certificaciones firmadas de operaciones y términos aplicables. <sup>[18]</sup>
- Países y canales adicionales se lanzan solo tras las verificaciones legales, operativas y de proveedor correspondientes.

## 12. Riesgos y mitigaciones

Ningún producto financiero blockchain está libre de riesgos. Esta tabla no es exhaustiva.

| Riesgo | Mitigación actual | Exposición residual |
| --- | --- | --- |
| Activos subyacentes y emisores | cUSD está respaldado por USDT; cUSD+ mantiene USDY y divulga estructura, contabilidad y elegibilidad; USDT es el activo externo de entrada/salida. | Persisten riesgos de pérdida de paridad, emisor, custodia, legales, reservas y redención de USDY y USDT. |
| Contratos inteligentes | Código abierto, despliegues verificados, pruebas por capas, revisión adversarial continua, controles acotados y estado público. | Son posibles defectos, fallas de integración y errores de actualización. |
| Oráculo | La protección por umbral detiene rutas de valor y exige respuesta de gobernanza vinculada a evidencia. | Datos erróneos o no disponibles pueden retrasar depósitos y redenciones. |
| Liquidez y redención | cUSD y cUSD+ tienen rutas definidas de redención a USDT con comisión sin permisos; Emergency Exit transmite directamente por varios nodos BSC públicos y puede recurrir al envío del propio cUSD/cUSD+. | Liquidez de InstantManager, proveedores, red o medidas de cumplimiento pueden retrasar salidas. |
| Permisos | Acuñación y acceso siguen elegibilidad; el usuario posee cUSD+, no USDY directamente. | Ondo u otro proveedor puede cambiar elegibilidad o restringir direcciones o transacciones. |
| Ondo Stocks y mercado | Router verificado, UUPS actualizable solo por el Safe propietario de 3 de 5, comisiones acotadas, autorización del usuario y devolución directa de principal, tokens y excedente de liquidación. | Persisten riesgos de cierre de mercado, precio, deslizamiento, emisor, token, corredor, custodio, liquidez, certificaciones, liquidación, elegibilidad, regulación, impuestos, proveedor y actualizaciones. Operaciones pueden retrasarse, rechazarse, restringirse o no estar disponibles. |
| Recuperación de claves | Claves generadas en dispositivo y recuperación en nube personal evitan un repositorio central. | Pérdida de dispositivo o nube, cambios de plataforma o defectos de recuperación afectan acceso. |
| Gobernanza de actualizaciones | Control multiparte, registros públicos, verificación de fuente y disposición de almacenamiento. | Firmantes autorizados podrían hacer cambios perjudiciales o no responder a incidentes. |
| Dependencia de BNB Smart Chain | Una red elimina riesgo de puente; la aplicación utiliza varias rutas RPC y salidas de emergencia. | Interrupción, congestión, coordinación de validadores, fallas RPC, gas o políticas pueden afectar todo el producto. |
| Canales fiat | Koywe y Guardarian están activos; solo se nombran nuevos proveedores tras verificar capacidades. | Cobertura, métodos, dependencias bancarias, precios y disponibilidad pueden cambiar. |
| Regulación y delitos financieros | Documento oficial/selfie, domicilio cuando se requiere, controles del proveedor, restricciones geográficas y revisión jurídica. | Verificar no elimina fraude ni finanzas ilícitas; proveedores o autoridades pueden rechazar, retrasar, reportar o restringir actividad. |
| Concentración y preventa | Oferta fija, contratos públicos, curva inmutable, tokenomics separado y tesorería visible on-chain. | Concentración del fundador, vesting, transferencias de tesorería, liquidez y volatilidad siguen siendo materiales. |
| Reclamos de recompensas | EIP-712 acumulativo, contabilidad antirreutilización, vencimientos cortos, bloqueo DEX, contrato público y fondeo por tramos. | Tesorería puede rotar firmante, pausar, retirar o no fondear obligaciones de la base de datos; no son derechos sin confianza contra una reserva inmutable. |
| Métricas y concentración | Definiciones, fechas y carácter no auditado divulgados. | Uso y saldos iniciales pueden concentrarse y no predecir adopción amplia. |

## 13. Hoja de ruta y estado actual

| Área | Completado / actual | Próximo hito verificable |
| --- | --- | --- |
| Comisiones cUSD/cUSD+ | Nuevo proxy UUPS cUSD desplegado y verificado; proxy cUSD+ existente actualizado; perímetro externo USDT de 90 puntos básicos y conversión interna gratuita solo patrocinada instalados. | Supervisar conciliación de eventos de comisiones, respaldo, rutas por elegibilidad, divulgación a clientes antiguos y salidas sin permisos durante el despliegue. |
| Transacciones patrocinadas | Delegado EIP-7702 sin propietario desplegado y verificado; política del servidor, registros y controles graduales implementados. | Ampliar volumen controlado y medir fiabilidad, costo del patrocinador y alternativas de emergencia. |
| Transferencias | Flujos entre amigos cUSD/cUSD+, conversión gratuita entre elegibilidades y escrow de invitaciones implementados en contratos, backend y móvil. | Despliegue controlado y medición de uso retenido. |
| Pagos comerciales | Contrato de reemplazo cUSD+/cUSD con comisión Pay independiente del 0.9% desplegado, verificado y conectado a producción. | Ampliar exposición gradual y medir liquidaciones, repetición y comisiones devengadas. |
| Nóminas | Escrow cUSD+/cUSD separado por activo, pagos firmados por delegados, flujos backend/cliente y vault de reemplazo desplegados y verificados. | Pilotos empresariales, exposición gradual y fiabilidad de depósitos y pagos a volumen significativo. |
| $CONFIO | Token fijo y preventa de reemplazo con curva continua pagada en cUSD desplegados, verificados, con historial importado, obligaciones fondeadas y conexión de producción BSC. | Sincronizar divulgaciones con estado on-chain y abrir reclamos solo bajo los controles publicados. |
| Recompensas $CONFIO | RewardVault canónico desplegado, verificado, conectado al token y bloqueado hasta DEX; al habilitarse, la acumulación solo en base de datos usa el precio actual de la curva. | Habilitar acumulación cuando esté operativamente lista; en DEX, fondear tramo, activar firmante EIP-712 de vencimiento corto y reclamo patrocinado del cliente, y desbloquear. |
| Ondo Stocks | Proxy UUPS dedicado desplegado y verificado en `0x40c8e134BCAf44EEf9e7D184846F36c9862329c3`; aplicación, backend, certificaciones, ejecución patrocinada, entrega directa, venta a ahorro y comisión fija del 0.30% implementados. | Completar y mantener controles de proveedor, patrocinador, ensayos, exposición gradual, elegibilidad y activación antes de ampliar operaciones reales. |
| Acceso fiat | Koywe activo en siete mercados LATAM; Guardarian activo para SEPA y tarjetas. | Agregar proveedores verificados y alternativas sin dependencias ocultas. |
| Distribución | 8,004 verificaciones telefónicas; 177 usuarios Didit; audiencia del fundador de unas 480,000 personas; gasto pagado prácticamente nulo hasta la fecha. | Convertir distribución en usuarios con fondos, saldos retenidos, repetición, referidos y cohortes por país. |

### 13.1 Principios de medición

Confío distingue registros, verificación telefónica, identidad verificada, usuarios con fondos, dispositivos alcanzables, usuarios activos y saldos retenidos. Las medidas centrales incluyen usuarios con fondos, obligaciones cUSD y cUSD+, respaldo, comisiones de conversión, depósitos brutos, redenciones, entrada neta, saldo promedio y mediano, retención, entradas originadas en fiat, concentración, volumen comercial, nóminas y cohortes por país.

La distribución se mide como embudo: alcance, visita a tienda, instalación, teléfono, identidad, primer fondeo, saldo retenido, depósito o transacción repetidos y referido. La adquisición orgánica se separa de campañas pagadas.

### 13.2 La siguiente prueba

> **De infraestructura desplegada a uso sostenido**
>
> La siguiente prueba es adopción sostenida en BNB Smart Chain: usuarios con fondos, depósitos repetidos, redenciones fiables, saldos cUSD/cUSD+ retenidos, liquidez USDT, actividad comercial y de nóminas y entradas medibles desde fiat en varios mercados latinoamericanos.

## 14. Aviso legal

Este documento es únicamente informativo y de referencia técnica. No constituye asesoría de inversión, jurídica, fiscal, contable o financiera; tampoco prospecto, oferta, solicitud, recomendación ni promesa de rendimiento. Las descripciones reflejan diseño y estado al 31 de agosto de 2026 y pueden cambiar.

USDT, cUSD y cUSD+ no son depósitos bancarios ni están cubiertos por un seguro de depósitos. Stablecoins, títulos tokenizados, contratos, blockchains, oráculos, proveedores fiat, creadores de mercado, custodios y otras infraestructuras pueden fallar, suspenderse, perder valor o quedar sujetos a nuevas reglas.

El rendimiento cUSD+ es variable, depende de USDY y del vault y no está garantizado. Acceso USDY y acuñación cUSD+ dependen de elegibilidad Ondo, cumplimiento, disponibilidad de proveedores y ley aplicable.

Ondo Stocks son instrumentos financieros tokenizados, no depósitos ni productos de ahorro asegurados. Acceso y negociación dependen de elegibilidad, jurisdicción, horario y disponibilidad de mercados, certificaciones y liquidación de Global Markets, funcionamiento blockchain y términos y leyes aplicables. El valor mostrado puede diferir del precio de ejecución; quizá no sea posible comprar, vender, transferir o redimir cuando se desee.

$CONFIO es independiente de USDT, cUSD, cUSD+ y USDY. No otorga derechos sobre respaldo, ingresos, capital social, activos o beneficios de Confío salvo que términos definitivos dispongan expresamente lo contrario. Los compradores deben revisar tokenomics, términos de preventa, contratos, estado de vesting, concentración de tesorería y ley aplicable.

Antes de usar servicios deben revisarse los términos definitivos de productos y proveedores, riesgos, contratos y legislación local.

## Notas

1. Banco Interamericano de Desarrollo, “Remittances to Latin America and the Caribbean Ease After 2025 Surge”, 16 de junio de 2026: remesas regionales estimadas de US$173.7 mil millones en 2025, 7.3% más que en 2024. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge

2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth”, 2 de octubre de 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/

3. Repositorio público y README de Confío: aplicación móvil, backend, contratos BSC, modelo de billetera, pagos, nóminas, token y preventa de código abierto. https://github.com/caesar4321/Confio

4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa”, fuente del proyecto, consultada en julio de 2026.

5. Documentación para desarrolladores de BNB Chain: introducción a BNB Smart Chain y finalidad de las transacciones. https://docs.bnbchain.org/bnb-smart-chain/introduction/

6. Documentación para desarrolladores de BNB Chain: comisiones de transacción y conceptos de red. https://docs.bnbchain.org/bnb-smart-chain/

7. Documentación de Ondo Finance, “USDY Basics”, consultada en julio de 2026. https://docs.ondo.finance/general-access-products/usdy/basics

8. Confío, “cUSD+ deployment record - BSC mainnet”, actualizado el 31 de agosto de 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

9. BscScan, proxy ERC1967 de Confío Dollar+, dirección `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code

10. Documentación para desarrolladores de Ondo Finance, “Integrating with the USDY InstantManager contract”. https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration

11. Confío, `CusdPlusVault.sol`: contabilidad desplegada, redención, protección del oráculo y lógica de participación de Confío del 15% en el rendimiento. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol

12. Documentación del ecosistema y para desarrolladores de BNB Chain, consultada en julio de 2026. https://www.bnbchain.org/en/developers

13. Registros de socios de Confío, julio de 2026: acuerdos comerciales e integraciones de producción de Koywe y Guardarian en los mercados y métodos admitidos. Las condiciones comerciales se rigen por los respectivos acuerdos.

14. Instantánea de analítica interna de Confío, 23 de julio de 2026: verificación telefónica completada, identidad Didit mediante documento oficial y selfie en vivo, y métricas de dispositivos FCM. No auditada.

15. Instantánea de analítica interna del canal del fundador, 23 de julio de 2026. La audiencia es aproximada y cambia con el tiempo.

16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps”, *Forbes Technology Council*, 6 de julio de 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/

17. Contratos BSC y registros de despliegue de Confío: `ConfioToken.sol`, `ConfioPresaleVault.sol`, `ConfioRewardVault.sol`, `ConfioVestingVault.sol`, `ConfioInviteEscrow.sol`, `ConfioBatchDelegate.sol`, `ConfioStockRouter.sol` y direcciones verificadas. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus y https://github.com/caesar4321/Confio/tree/main/contracts/ondo_stocks y https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md

18. Ondo Finance, “Ondo Stocks” y documentación de la API de Global Markets, consultadas en julio de 2026. https://ondo.finance/ondo-stocks y https://docs.ondo.finance/api-reference/quickstart

19. Oficina de Evaluación Independiente del FMI: documentación histórica del congelamiento parcial de depósitos, controles de capital y conversión forzosa en Argentina en 2001; revisión del FMI sobre flexibilización de la mayoría de restricciones cambiarias bajo el programa de estabilización de 2025. https://www.imf.org/External/NP/ieo/2003/arg/ y https://www.imf.org/es/news/articles/2025/07/31/pr25272-argentina-imf-completes-first-review-of-the-extended-arrangement-under-the-eff

20. FMI, “Digital Money and Central Banks Balance Sheet”, documento de trabajo n.º 2022/206: Venezuela como caso de dolarización real. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml

21. FMI, “Bolivia: 2025 Article IV Consultation”, informe de país n.º 2025/116. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384

22. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, febrero de 2026, depósitos por moneda. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF

23. Banco de México, agregados monetarios de 2024; Banco Interamericano de Desarrollo, estimación de remesas de México para 2025. https://www.banxico.org.mx/TablasWeb/informe-anual/compilacion-2024/7EF1402E-1443-4070-9C0A-6B352272C3B9.html y https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

24. Banco Interamericano de Desarrollo, *Remittances to Latin America and the Caribbean in 2025: Adaptations in a Context of Uncertainty*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf

25. ACNUR, *Global Report 2025 — Situation Overview: Colombia*: Colombia acogía aproximadamente 2.8 millones de venezolanos en 2025. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

### Procedencia del documento

Preparado a partir del whitepaper anterior en inglés, materiales de producto y tokenomics de Confío, registros de Koywe y Guardarian, repositorio público y despliegues BSC, documentación oficial BNB Chain y Ondo, literatura de mercado citada y métricas internas expresamente proporcionadas para esta actualización.
