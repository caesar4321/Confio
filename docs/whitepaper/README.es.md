# Confío: La plataforma de dólares digitales de confianza para América Latina

**Pagos en Algorand. Ahorros en BNB Smart Chain.**

Confío es una aplicación financiera totalmente de código abierto y no custodial que convierte la infraestructura de stablecoins y activos tokenizados en una experiencia móvil familiar para los usuarios latinoamericanos.

**Traducción al español · Versión 3.1 · Julio de 2026**<br>
Julian Moon · Fundador y CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Blockchain por dentro. Simple como PayPal.*

> **Aviso sobre esta traducción**
>
> Esta es una traducción de cortesía. El [documento original en inglés](README.md) es la única versión oficial y autoritativa del whitepaper de Confío. Si existiera cualquier diferencia de significado, interpretación o actualización entre esta traducción y el original, prevalece el texto en inglés. También está disponible la [traducción al coreano](README.ko.md).

## Cómo leer este documento

> **Un producto, infraestructura diseñada para cada propósito**
>
> Confío utiliza Algorand para los pagos con cUSD y BNB Smart Chain para el ahorro con cUSD+. Las cadenas cumplen funciones distintas, mientras la aplicación presenta una experiencia financiera única, coherente y no custodial.

Este documento explica la arquitectura de producto, estrategia, modelo operativo y riesgos materiales actuales de Confío. Sustituye el enfoque anterior, centrado principalmente en Argentina y Venezuela, por una tesis regional basada en pagos simples en dólares, ahorro accesible en dólares, control no custodial y conectividad fiat país por país.

<details>
<summary><strong>Contenido</strong></summary>

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Tesis de mercado](#2-tesis-de-mercado)
3. [Sistema de producto](#3-sistema-de-producto)
4. [cUSD: infraestructura de pagos en Algorand](#4-cusd-infraestructura-de-pagos-en-algorand)
5. [cUSD+: infraestructura de ahorro en BNB Smart Chain](#5-cusd-infraestructura-de-ahorro-en-bnb-smart-chain)
6. [Billetera, seguridad y arquitectura de código abierto](#6-billetera-seguridad-y-arquitectura-de-código-abierto)
7. [Usuarios, distribución y salida al mercado](#7-usuarios-distribución-y-salida-al-mercado)
8. [Modelo de negocio](#8-modelo-de-negocio)
9. [Estrategia multicadena y del token](#9-estrategia-multicadena-y-del-token)
10. [Cumplimiento y modelo operativo](#10-cumplimiento-y-modelo-operativo)
11. [Riesgos y mitigaciones](#11-riesgos-y-mitigaciones)
12. [Hoja de ruta y estado actual](#12-hoja-de-ruta-y-estado-actual)
13. [Aviso legal](#13-aviso-legal)
14. [Notas](#notas)

</details>

---

## 1. Resumen ejecutivo

Confío es una aplicación de dólares digitales para América Latina, totalmente de código abierto y no custodial. Ofrece una interfaz móvil familiar para mantener, enviar, gastar y hacer crecer activos denominados en dólares, sin exigir que el usuario administre tokens de gas, memorice direcciones blockchain o navegue pantallas de trading. <sup>[3]</sup>

> **Tesis de producto**
>
> La plataforma de dólares de consumo que gane en América Latina no pedirá que sus usuarios se conviertan en expertos en cripto. Combinará propiedad verificable on-chain con la claridad, recuperación, métodos de pago locales y soporte humano que se esperan de una fintech moderna. La competencia no se decidirá por paridad de funciones, sino por distribución, confianza y adaptación local. Confío entra con un canal en español liderado por su fundador de aproximadamente 480.000 personas, una relación pública de años con la región y, hasta la fecha, prácticamente cero gasto en medios pagados.

A medida que las aplicaciones financieras on-chain convergen en combinaciones similares de ahorro, envío y gasto, disponer del producto deja de ser una diferenciación suficiente. Distribución, confianza y relevancia local se convierten en las ventajas escasas. Confío las reúne mediante una audiencia hispanohablante liderada por su fundador, una base existente de usuarios verificados, métodos de pago específicos por país y un producto diseñado alrededor del comportamiento financiero latinoamericano, no de una interfaz cripto global genérica. <sup>[15, 16]</sup>

Confío utiliza una arquitectura multicadena deliberada y basada en funciones. cUSD permanece en Algorand como infraestructura de pagos y transferencias. cUSD+ opera en BNB Smart Chain como infraestructura de ahorro, respaldada por Ondo USDY. La aplicación hace que ambos sistemas de liquidación se sientan como un solo producto coherente.

| Producto | Función principal | Diseño de liquidación |
| --- | --- | --- |
| cUSD | Dólares digitales cotidianos para transferencias, contactos, pagos y operaciones empresariales. | Algorand; diseñado como unidad respaldada 1:1 por USDC para liquidación rápida y de bajo costo. |
| cUSD+ | Ahorro en dólares con exposición a rendimiento variable, presentado como un saldo acumulativo. | BNB Smart Chain; respaldado por una bóveda con USDY y con entrada/salida mediante USDT. |
| $CONFIO | Comunidad, recompensas y futura utilidad del ecosistema; separado de los activos de respaldo. | Actualmente Algorand. Este whitepaper no presupone una migración a BNB. |

Al 23 de julio de 2026, Confío registra 8.004 usuarios que completaron la verificación telefónica y 177 usuarios que completaron la verificación de identidad de Didit mediante un documento oficial y una selfie en vivo para controles de prueba de vida y coincidencia facial. El 61,5% de quienes iniciaron el flujo de Didit lo completaron. Confío también registra 2.094 dispositivos alcanzables por notificaciones push; 2.092 de ellos fueron utilizados en los últimos 30 días. Son métricas operativas internas, no auditadas de forma independiente, y no deben interpretarse como usuarios con fondos ni como usuarios activos mensuales. <sup>[14]</sup>

La bóveda de BNB Smart Chain está desplegada y verificada, se controla mediante gobernanza Safe multipartita e integra USDY, USDT, Ondo InstantManager y el oráculo de precio de USDY en producción. Confío trabaja con Ondo Finance dentro de su marco de elegibilidad y cumplimiento para ofrecer la experiencia de ahorro cUSD+. <sup>[8, 9]</sup>

## 2. Tesis de mercado

### 2.1 Un problema de acceso al dólar, no de conocimiento cripto

América Latina no es una sola crisis monetaria homogénea. Algunos usuarios necesitan protegerse de la volatilidad de su moneda; otros necesitan liquidación transfronteriza asequible, un lugar seguro para ahorrar en dólares o una forma práctica de pagar y recibir pagos. Los une la demanda de una unidad confiable en dólares y la insatisfacción con la fricción para obtenerla y usarla.

| Mercado | Necesidad de dólares observada | Implicación para el producto |
| --- | --- | --- |
| Argentina | La inflación recurrente, los controles de capital y la memoria institucional del *corralito* de 2001 y la conversión forzada de depósitos en dólares enseñaron a los hogares a valorar el acceso y el control tanto como el rendimiento nominal. Las restricciones cambiarias más recientes se han flexibilizado, pero el déficit histórico de confianza sigue siendo relevante. <sup>[19]</sup> | Un producto en dólares debe explicar con especial claridad los límites de custodia, derechos de retiro, precios y cambios de reglas. |
| Venezuela | La inflación extrema convirtió al dólar estadounidense tanto en reserva de valor como en medio de pago cotidiano, creando una economía muy dolarizada pero operativamente fragmentada. <sup>[20]</sup> | El acceso al dólar y su utilidad de pago son necesidades inmediatas; sanciones, disponibilidad de proveedores y cumplimiento requieren controles más estrictos. |
| Bolivia | La evaluación del FMI de 2025 describió reservas de divisas utilizables cercanas a cero, una brecha creciente con el tipo de cambio paralelo y fuertes limitaciones al acceso privado a dólares al tipo oficial. <sup>[21]</sup> | El acceso confiable, precio local transparente y liquidez de retiro importan antes que optimizar el rendimiento. |
| Perú | Datos de la SBS muestran que el sistema financiero regulado ya mantiene depósitos en moneda extranjera por decenas de miles de millones de dólares. <sup>[22]</sup> | Los ahorristas existentes en dólares son un mercado inicial natural para ahorro portátil, controlado por el usuario y cUSD+. |
| México | Banco de México reportó MXN 949.400 millones en depósitos inmediatos y a plazo denominados en moneda extranjera en 2024, mientras las remesas alcanzaron aproximadamente US$62.500 millones en 2025. <sup>[23]</sup> | La oportunidad combina ahorro en dólares de mayor saldo con un flujo transfronterizo recurrente enorme, conectado localmente mediante SPEI. |
| Colombia | Estados Unidos originó el 53,4% de las remesas recibidas por Colombia en 2025, mientras el país acogía aproximadamente 2,8 millones de venezolanos. Su escala de remesas y diáspora venezolana crean una oportunidad específica para transferencias familiares Colombia–Venezuela. <sup>[24, 25]</sup> | PSE y Nequi ofrecen acceso local en Colombia, mientras cUSD está diseñado para permitir transferencias y liquidación en dólares, sujetas a cumplimiento, entre usuarios conectados a lo largo del corredor. |

Estos mercados no comparten una sola crisis, pero muestran un **reflejo dolarizador** común: cuando la confianza, el acceso o el poder adquisitivo son inciertos, las personas buscan exposición al dólar mediante cualquier canal disponible. La estrategia de Confío parte de la causa concreta de esa demanda, sin tratar a América Latina como un mercado intercambiable.

**Los corredores de origen importan tanto como los mercados de destino.** En 2025, Estados Unidos originó el 35,7% de las remesas recibidas en Sudamérica y Europa el 36,2%, incluidos 19,7 puntos porcentuales procedentes de España. Confío considera por ello a Estados Unidos y España mercados de origen estratégicos, a Colombia tanto un destino como un puente hacia hogares venezolanos, y al resto de América Latina una red de mercados receptores y de circulación distintos. <sup>[24, 25]</sup>

Esta estrategia de corredores se refiere a transferencias con cUSD, acceso a pagos locales y entradas y salidas fiat conformes. No implica que cUSD+, USDY u Ondo Stocks estén disponibles para personas estadounidenses; los productos de ahorro e inversión siguen sus propios términos, restricciones jurisdiccionales y reglas de elegibilidad.

Las stablecoins han superado su condición de instrumento de trading de nicho. Chainalysis informa que representaron más de la mitad de las compras en exchanges en varios mercados fiat latinoamericanos importantes durante el año terminado en junio de 2025, mientras la adopción cripto regional creció con fuerza en segmentos minoristas e institucionales. <sup>[2]</sup>

Las remesas siguen siendo económicamente decisivas. El Banco Interamericano de Desarrollo estimó que alcanzaron un récord de US$173.700 millones en América Latina y el Caribe en 2025, un 7,3% más que en 2024. Confío no presupone sustituir toda la infraestructura de remesas; se concentra en la billetera del consumidor, el acceso local y la experiencia de liquidación en dólares que conecta remitentes y receptores. <sup>[1]</sup>

### 2.2 La brecha de producto

Las opciones existentes suelen obligar a elegir. Bancos y fintechs locales pueden ofrecer buena experiencia, pero conservan custodia y dependen del acceso bancario nacional. Los exchanges ofrecen liquidez, pero están optimizados para traders. Las billeteras de autocustodia ofrecen control, pero exponen al usuario a frases semilla, direcciones, gas, puentes y selección de tokens.

- Confío prioriza el dólar, no el trading.
- La billetera es no custodial en la capa de claves, mientras los servicios fiat aplican los controles de identidad y cumplimiento exigidos por sus proveedores.
- La selección de blockchain sigue la función: confiabilidad de pagos para cUSD y conectividad EVM/RWA para cUSD+.
- La expansión por país sigue la preparación operativa y cobertura de socios, no una ideología de mercado único.

### 2.3 Panorama competitivo

| Categoría | Fortaleza y limitación típicas | Diferencia de Confío |
| --- | --- | --- |
| Bancos y servicios de remesas | Marcas conocidas y alcance en efectivo o cuentas, pero generalmente custodiales y limitados por cuentas, corredores, horarios e intermediarios. | Billetera en dólares controlada por el usuario, con liquidación digital directa y acceso local. |
| Exchanges y mercados P2P | Liquidez profunda y amplio acceso a stablecoins, pero pantallas de trading, libros de órdenes, disputas y riesgo de contraparte añaden carga cognitiva. | Experiencia centrada en dólares que oculta la mecánica de exchange y presenta acciones claras. |
| Aplicaciones de dólares custodiales y neobancos | Buena experiencia localizada, pero el acceso depende del modelo de custodia y de pocos socios bancarios o corredores. | UX fintech local combinada con claves de firma del usuario y controles de proveedores claramente separados. |
| Billeteras de autocustodia | Control abierto de activos, pero hacen visibles frases semilla, gas, direcciones hexadecimales, puentes y selección de tokens. | Recuperación en nube personal, tarifas de red patrocinadas, envíos por contacto y abstracción de cUSD/cUSD+. |
| Aplicaciones financieras on-chain | Paquetes cada vez más parecidos de ahorro, rendimiento, transferencias y gasto; muchas compiten por los mismos usuarios cripto mediante recompensas y cashback. | Distribución en español liderada por el fundador, confianza comunitaria y productos y rieles por país orientados a incorporar nuevos usuarios latinoamericanos on-chain. |

### 2.4 La distribución es la nueva frontera competitiva

La infraestructura de stablecoins se generaliza y las aplicaciones convergen en un paquete familiar: mantener dólares, obtener rendimiento variable, enviar entre países y gastar con métodos locales. Al volverse reproducibles estas funciones, la competencia pasa del acceso a infraestructura a la capacidad de alcanzar usuarios, ganar su confianza y adaptar el producto a la demanda local. El análisis sectorial describe cada vez más esta carrera como una competencia de distribución, no puramente técnica. <sup>[16]</sup>

Confío no busca superar a competidores mediante incentivos temporales. Convierte un canal en español liderado por su fundador en un ciclo medible: educación, instalación, verificación telefónica y de identidad, fondeo, saldos retenidos, uso repetido, referidos y, finalmente, mayor utilidad comercial y de planillas. Contactos telefónicos, QR interoperable, SPEI, PIX, PSE/Nequi, Alias/CVU y superficies locales no son localización posterior: forman parte del sistema de producto y distribución.

### 2.5 El problema más profundo: falta de confianza

Debajo de la volatilidad monetaria existe un costo estructural: la falta de confianza. Las personas aprendieron a desconfiar de instituciones que congelan acceso, cambian reglas, ocultan spreads o fallan sin aviso. Confío no pide reemplazar esa experiencia por fe ciega en otra empresa. Combina claves controladas por el usuario, código abierto, respaldo transparente y controles de proveedores separados para que las afirmaciones importantes puedan verificarse.

> **Lo tuyo, tuyo**
>
> La promesa de Confío es simple: lo que pertenece al usuario permanece bajo su control. Se aplica a la custodia de la billetera; los controles del emisor, activo, cumplimiento y proveedor se divulgan en lugar de ocultarse.

### 2.6 Para quién es Confío

El cliente inicial no se define solo por nacionalidad. Confío está diseñado para personas comunes con objetivos en dólares: conservar ahorros, enviar dinero a familia, cobrar, pagar un comercio o colocar parte de su saldo en ahorro transparente. Los ahorristas de mayor saldo son un punto de entrada importante para cUSD+, mientras los pagos siguen diseñados para uso cotidiano amplio.

## 3. Sistema de producto

Confío separa la experiencia del usuario de la infraestructura de liquidación. El usuario ve saldos en dólares y acciones claras; la aplicación elige la cadena apropiada, prepara la transacción y abstrae las tarifas rutinarias. Esto no significa que las cadenas sean iguales: sus propiedades y riesgos se explican en el producto y en este documento.

| Capa del consumidor | Capa de producto Confío | Capa de liquidación y respaldo |
| --- | --- | --- |
| Inicio con Google/Apple; identidad telefónica; UX primero en español | Creación y recuperación de billetera; transferencias por contacto; presentación de saldos | Claves generadas en el dispositivo; transacciones firmadas por el usuario |
| Documento oficial, selfie en vivo y dirección residencial ingresada por el usuario cuando se requiere | Orquestación de identidad y alta con proveedores, con consentimiento | Controles de documento, prueba de vida y coincidencia facial de Didit; dirección y controles específicos de Koywe y Guardarian |
| Métodos de pago locales e internacionales | Orquestación de rampas; cotizaciones, órdenes, estado y soporte | Rieles locales Koywe en siete mercados; Guardarian SEPA y acceso en USD con Visa, Mastercard, Apple Pay y Google Pay |
| Pagar, enviar, recibir | cUSD | Liquidación en Algorand; diseño respaldado por USDC |
| Ahorrar y retirar | cUSD+ | Bóveda en BNB Smart Chain; respaldo USDY; entrada y salida USDT |

### 3.1 Dos cadenas, dos funciones

Pagos y ahorro no deben imponerse sobre la misma cadena por simetría arquitectónica. Los pagos favorecen costo predecible, finalidad inmediata y flujos atómicos. El ahorro con activos del mundo real favorece compatibilidad EVM, integraciones institucionales y acceso al ecosistema de stablecoins y desarrolladores de BNB Chain.

### 3.2 No custodial no significa no regulado

Confío distingue las claves del usuario, los contratos del emisor o bóveda y los proveedores regulados fiat/RWA. Confío no posee la clave privada del usuario. Al mismo tiempo, emisión de cUSD, elegibilidad de cUSD+, rampas fiat y activos subyacentes pueden tener requisitos de **conocimiento del cliente (Know Your Customer, KYC)** y controles de **prevención del lavado de activos (Anti-Money Laundering, AML)**, incluida la revisión de sanciones y monitoreo de transacciones. Que la billetera sea no custodial no elimina esos controles separados. <sup>[3, 4]</sup>

## 4. cUSD: infraestructura de pagos en Algorand

cUSD es la unidad de dólares digitales de Confío para transferencias y pagos cotidianos. Está diseñado con respaldo 1:1 en USDC sobre Algorand. La propuesta es simple: un saldo denominado en dólares que se envía a un contacto telefónico o se usa en un flujo empresarial sin exponer la conversión subyacente. <sup>[3]</sup>

### 4.1 Por qué Algorand sigue siendo el hogar de los pagos

La confiabilidad es prioritaria para pagos. Algorand Mainnet registra cero interrupciones de protocolo desde su lanzamiento en junio de 2019: más de siete años de disponibilidad ininterrumpida a julio de 2026. Para usuarios que dependen de Confío para enviar, cobrar o pagar, la disponibilidad continua es un requisito de primer orden. <sup>[17]</sup>

Algorand también proporciona finalidad inmediata: una transacción incluida en un bloque es final, sin esperar una posible reorganización. Su tarifa mínima baja es independiente de la complejidad computacional del contrato. La operación ininterrumpida, finalidad instantánea y costos bajos y predecibles encajan con pagos minoristas, QR, escrow y planillas atómicas. <sup>[5, 6]</sup>

- Cero interrupciones desde 2019 ofrecen un historial operativo demostrado para pagos siempre disponibles.
- Envíos por contacto y flujos de reclamo pueden agruparse con la liquidación.
- Las tarifas patrocinadas permiten experiencia sin gas visible sin negar que el costo existe.
- La finalidad rápida reduce ambigüedad en el punto de pago.
- cUSD permanece separado de cUSD+; un producto de ahorro en BNB Smart Chain no exige migrar pagos.

### 4.2 Respaldo, controles y propiedad del usuario

La clave de Algorand se genera en el dispositivo y se protege mediante la ruta de recuperación en la nube personal del usuario. Confío no almacena la clave privada sin cifrar. Sin embargo, cUSD es un activo emitido: respaldo, acuñación, rescate y controles legalmente exigidos al emisor son distintos de la custodia de la billetera. Este modelo de dos capas es más preciso que afirmar que todo el producto carece de permisos. <sup>[3, 4]</sup>

## 5. cUSD+: infraestructura de ahorro en BNB Smart Chain

### 5.1 Propósito

cUSD+ es un token acumulativo de ahorro en dólares que ofrece a usuarios elegibles exposición al rendimiento variable de Ondo USDY mediante un saldo familiar. USDY es una nota tokenizada acumulativa cuyo precio de referencia aumenta con los ingresos subyacentes. Disponibilidad y rescate están sujetos a elegibilidad, cumplimiento y términos de Ondo; cUSD+ no elimina esas condiciones. <sup>[7]</sup>

> **Arquitectura de producción**
>
> La bóveda de BSC Mainnet está desplegada, con código verificado e integrada con USDY, InstantManager y el oráculo de precios de Ondo en producción. Suscripciones y rescates operan dentro del marco de compradores autorizados y elegibilidad de Ondo.

### 5.2 Flujo de activos

| Paso | Depósito | Rescate |
| --- | --- | --- |
| 1 | Usuario o relayer aporta USDT en BSC. | Usuario solicita rescatar cUSD+. |
| 2 | La bóveda llama a `subscribe` de Ondo InstantManager. | La bóveda quema el cUSD+ correspondiente. |
| 3 | InstantManager entrega USDY a la bóveda. | La bóveda envía USDY mediante `redeem` de InstantManager. |
| 4 | La bóveda acuña cUSD+ al usuario al precio de referencia protegido. | USDT se entrega al usuario o dirección de rampa designada. |

USDY sin envolver permanece dentro de infraestructura aprobada. Los usuarios entran y salen mediante USDT, sin recibir USDY directamente. Esto respeta el carácter autorizado del activo subyacente y conserva una ruta clara de rescate. La documentación de Ondo también exige registrar la dirección exacta que llama al InstantManager. <sup>[8, 10]</sup>

### 5.3 Participación en el rendimiento y acumulación de valor

La bóveda asigna a Confío el 15% de la apreciación positiva del precio de referencia de USDY. El 85% restante se refleja en el valor de referencia de los titulares de cUSD+. Es una participación en apreciación variable, no un APY fijo ni garantizado. Si cambia el rendimiento de USDY, cambia el importe bruto disponible para titulares y Confío. <sup>[8, 11]</sup>

La bóveda mantiene un valor de referencia interno y comprueba que el respaldo USDY cubra las obligaciones. Movimientos del oráculo superiores al umbral configurado detienen las rutas de valor hasta registrar una decisión de gobernanza. Así se reduce el riesgo de convertir una observación anómala en dilución o rescate inseguro. <sup>[8, 11]</sup>

### 5.4 Por qué cUSD+ usa BNB Smart Chain

La razón principal es Ondo Finance. Confío no eligió BNB Smart Chain y luego buscó un activo de ahorro. cUSD+ se diseñó alrededor de USDY, y Ondo puso su infraestructura de producción —USDY, InstantManager, oráculo y suscripción/rescate con USDT— a disposición en BNB Smart Chain. Mantener la bóveda en esa red ofrece una ruta directa y autorizada al activo subyacente. <sup>[7, 8, 10]</sup>

La compatibilidad EVM, liquidez USDT, infraestructura de billeteras, bloques cortos y tarifas bajas de BNB Smart Chain fortalecen la decisión y permiten futuras integraciones RWA. Son ventajas de apoyo, no la causa original. El TVL de la cadena no crea automáticamente valor para cUSD+, y el despliegue BNB no implica migrar cUSD ni $CONFIO desde Algorand. <sup>[8, 12]</sup>

### 5.5 Ondo Stocks (Global Markets)

Confío planea extender la experiencia a acciones y ETF estadounidenses tokenizados elegibles, emitidos mediante Ondo Global Markets. El flujo diseñado permite comprar desde cUSD+ y devolver las ventas directamente a cUSD+, donde el saldo restante puede continuar acumulando rendimiento variable ligado a USDY. El router actúa como paso, no como custodio: los activos se mueven dentro de la transacción autorizada y no permanecen en el router. <sup>[3, 18]</sup>

El precio objetivo de lanzamiento es una comisión explícita de Confío del 0,30% en cada compra y venta. No es un margen oculto: se calcula por separado y se transfiere on-chain en USDT. Cualquier costo o spread incluido en la cotización de Ondo, junto con cargos de terceros, debe mostrarse por separado antes de confirmar. El precio final se fijará cuando se conozca el esquema comercial y de cotización completo de Ondo Global Markets.

## 6. Billetera, seguridad y arquitectura de código abierto

### 6.1 Abierto por defecto

La aplicación móvil, backend y contratos inteligentes de Confío se publican bajo licencia MIT. El repositorio incluye React Native, servicios Django/GraphQL, contratos de Algorand y Solidity, integraciones de rampas, pagos, planillas e infraestructura de pruebas. Usuarios, revisores y desarrolladores pueden inspeccionar, bifurcar o adaptar la implementación completa, en vez de confiar en un cliente cerrado. <sup>[3]</sup>

### 6.2 Propiedad y recuperación de claves

Las claves se generan en el dispositivo y se cifran para recuperación mediante el entorno personal de Google o Apple del usuario. El producto evita una incorporación centrada en la frase semilla, pero mantiene la autocustodia: Confío no debe poseer una clave maestra de servidor capaz de mover fondos ordinarios. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío nunca posee las claves de firma del usuario. Ningún operador de Confío puede firmar una transacción de la billetera por el usuario, ni siquiera nosotros. Activos emitidos como cUSD y la bóveda cUSD+ mantienen controles propios de emisor, activo, cumplimiento y gobernanza, divulgados por separado.

### 6.3 Gobernanza de contratos y seguridad operativa

El proxy de cUSD+ se gobierna mediante un Safe multipartito. Se conserva la capacidad de actualización porque la bóveda depende de contratos y oráculos externos de Ondo que pueden migrar. Esto crea riesgo de gobernanza, pero bloquear permanentemente una implementación dependiente de infraestructura cambiante podría inmovilizar fondos. La mitigación es gobernanza transparente, aprobación multipartita, código verificado, controles de layout de almacenamiento y registros públicos de actualización. <sup>[8, 9]</sup>

La revisión de seguridad es continua, no una certificación puntual. El código pasa ciclos adversariales recurrentes con modelos avanzados de IA junto con pruebas unitarias, fork de mainnet, invariantes, fuzzing, diferenciales y ensayos de actualización. Confío se apoya en verificabilidad abierta, defensa en profundidad, controles conservadores y registros públicos, no en la oscuridad. <sup>[8]</sup>

| Superficie de control | Diseño actual |
| --- | --- |
| Claves de transacción | Generadas y usadas en el dispositivo; protegidas mediante recuperación en nube personal. |
| Gas rutinario | Confío patrocina todas las transacciones blockchain del usuario; no necesita ALGO ni BNB para usar la aplicación. |
| Tesorería y actualizaciones cUSD+ | Aprobación Safe multipartita; historial público de implementación y actualizaciones. |
| Respaldo y precio | Diseño respaldado por USDC para cUSD; bóveda USDY y lógica de oráculo protegida para cUSD+. |
| Transparencia | Aplicación, backend, contratos y documentación de despliegue públicamente inspeccionables. |

## 7. Usuarios, distribución y salida al mercado

### 7.1 Métricas operativas actuales

| Métrica | Valor actual | Definición / cautela |
| --- | --- | --- |
| Usuarios con teléfono completo | 8.004 | Completaron verificación telefónica; no equivale a usuarios con fondos. |
| Usuarios verificados por Didit | 177 | Presentaron documento oficial y completaron selfie en vivo, prueba de vida y coincidencia facial. Esto no significa aprobación automática por todos los proveedores. |
| Finalización de identidad Didit | 61,5% | Tasa entre quienes iniciaron ese flujo; separada de dirección, monitoreo transaccional y elegibilidad por proveedor. |
| Dispositivos alcanzables por push | 2.094 | Dispositivos actualmente alcanzables mediante FCM. |
| Utilizados en 30 días | 2.092 | Dispositivos alcanzables utilizados en 30 días; no se etiquetan como MAU auditados. |
| Audiencia del fundador | ≈480.000 | Audiencia hispanohablante aproximada; las métricas de plataforma varían. |

Fuente: analítica interna de producto y canal, 23 de julio de 2026. Métricas no auditadas. <sup>[14, 15]</sup>

### 7.2 La distribución es una capacidad de producto

> **La confianza es el canal de distribución**
>
> La presencia del fundador de Confío en TikTok alcanza a la audiencia hispanohablante exacta del producto y crea adquisición orgánica con prácticamente cero gasto en medios pagados.

La adopción financiera suele comenzar por la credibilidad del mensajero. La distribución en español liderada por el fundador no es un adorno: es un canal directo de adquisición y educación. La prueba operativa no es el número de seguidores por sí solo, sino la conversión medible desde contenido hasta verificación, depósito, saldo retenido y uso repetido. <sup>[15]</sup>

Esto cambia la economía de crecimiento. Confío puede explicar productos, responder objeciones en el idioma de la audiencia, observar conversiones y mejorar sin depender por defecto de subsidios. La audiencia no sustituye el encaje producto-mercado; es una ruta repetible para comprobar si confianza y educación se convierten en uso financiado.

El ciclo previsto es:

1. Contenido del fundador identifica una necesidad y explica el producto en español sencillo.
2. El usuario entra a una experiencia móvil familiar y completa teléfono o identidad cuando corresponde.
3. Rieles locales e internacionales convierten intención en saldos cUSD o cUSD+ financiados.
4. Transferencias, rescates, soporte y controles transparentes construyen confianza retenida.
5. Usuarios retenidos generan referidos, utilidad en contactos, demanda comercial y evidencia para expansión.

La distribución consigue el primer uso; la utilidad local confiable consigue retención.

### 7.3 Expansión por país

Confío abandona un whitepaper centrado en Argentina y Venezuela. El producto es regional, pero el acceso es local. Cada país se habilita solo cuando rieles fiat, cumplimiento, soporte, precios y liquidez son operacionalmente creíbles.

- Koywe está activo en siete mercados: Alias/CVU en Argentina, SPEI en México, QR interoperable en Perú y Bolivia, transferencia bancaria en Chile, PSE/Nequi en Colombia y PIX en Brasil. <sup>[13]</sup>
- El QR interoperable activo en Perú y Bolivia sitúa a Confío dentro de un comportamiento cotidiano ignorado por aplicaciones centradas en tarjetas; es acceso actual, no una hoja de ruta especulativa. <sup>[13, 16]</sup>
- Guardarian ofrece SEPA en la zona euro y acceso en USD con Visa, Mastercard, Apple Pay y Google Pay. <sup>[13]</sup>
- Se nombran proveedores adicionales solo después de confirmar contratos y capacidad productiva.
- Perú y México son mercados de ahorro importantes; Bolivia y Venezuela tienen otras necesidades de acceso; Colombia combina remesas domésticas grandes con transferencias familiares ligadas a Venezuela; Chile, Argentina y Brasil requieren secuencias propias. <sup>[24, 25]</sup>
- Estados Unidos y España son orígenes estratégicos de remesas. El despliegue depende de fondeo del remitente, acceso del receptor, liquidación conforme, retiro o reutilización local y soporte en ambos extremos. <sup>[24]</sup>
- La aplicación muestra únicamente módulos listos y apropiados para cada mercado.

## 8. Modelo de negocio

Confío alinea ingresos con actividad financiera útil, no trading especulativo. Las transferencias personales son gratuitas a nivel de plataforma, los flujos empresariales pagan 0,9% y cUSD+ alinea ingresos con usuarios que conservan y aumentan su ahorro.

| Fuente | Política actual |
| --- | --- |
| Transferencias persona a persona | Comisión Confío 0%. Confío patrocina la red; pueden aplicar cargos fiat o de terceros debidamente informados. |
| Pagos a comercios | Comisión plana Confío de 0,9%. |
| Planillas y pagos masivos | Comisión plana Confío de 0,9%. |
| Participación cUSD+ | La bóveda asigna 15% de la apreciación positiva de USDY a Confío y 85% al valor de referencia del titular. Rendimiento variable, no garantizado. |
| Transacciones Ondo Stocks | Comisión explícita prevista de 0,30% en cada compra y venta, separada del costo/spread de la cotización Ondo y cargos de terceros. |
| Economía de rampas fiat | Precios de Koywe y participación de ingresos de Guardarian según cotización activa y contrato. |
| Productos futuros | Posibles comisiones o participación de otros socios RWA, brokerage o tarjetas, sujetos a términos y aprobaciones. |

Patrocinar red es un costo del producto, no prueba de gratuidad económica. Confío lo asume para simplificar la experiencia, mientras rampas, liquidez, cumplimiento y soporte conservan costos reales.

### 8.1 Lo que no respalda los productos

$CONFIO no respalda cUSD ni cUSD+. El respaldo se evalúa mediante stablecoin subyacente, activos de bóveda, contratos, rutas de rescate y términos legales. Preventa, precio del token y capital societario están separados del respaldo de activos de usuarios.

## 9. Estrategia multicadena y del token

### 9.1 Diseño multicadena por función

Confío no trata la cadena como prueba de lealtad. cUSD y pagos permanecen en Algorand por su idoneidad para transacciones finales y baratas. cUSD+ usa BNB Smart Chain porque su economía depende de USDY, USDT, contratos EVM y potenciales integraciones RWA. BNB complementa, no reemplaza, Algorand.

### 9.2 $CONFIO

$CONFIO es un token comunitario y de ecosistema separado, emitido actualmente en Algorand. Este documento no anuncia migración ni un nuevo token BNB. Una decisión futura se tomaría cuando liquidez externa, preparación TGE/DEX, requisitos concretos de exchanges y utilidad puedan evaluarse con datos reales.

Una representación o migración futura deberá preservar la oferta. Los tokens Algorand distribuidos no pueden duplicarse mediante airdrop BSC: se requeriría bloqueo, quema o reclamo que preserve suministro. Las asignaciones no distribuidas pueden fijarse al distribuirse por primera vez sin duplicar circulación.

> **Política actual**
>
> Mantener cUSD en Algorand, lanzar cUSD+ en BNB Smart Chain y aplazar la decisión de cadena para $CONFIO hasta que utilidad y estructura de mercado la justifiquen.

## 10. Cumplimiento y modelo operativo

Confío separa custodia de software de obligaciones de producto y proveedor. Una billetera no custodial puede integrar activos autorizados, verificación, sanciones, proveedores fiat y controles de emisor. **Conocimiento del cliente (KYC)** son los controles para establecer identidad y, cuando corresponde, residencia. **Prevención del lavado de activos (AML)** son controles del proveedor y de transacciones destinados a detectar o impedir sanciones, fraude, lavado, financiamiento del terrorismo y otras actividades prohibidas. Dependen del producto, entidad, ubicación, transacción y socio.

> **Arquitectura de publicador de software**
>
> Confío está diseñado para que actividades reguladas —custodia fiat, conversión, identidad y acceso a activos autorizados— sean realizadas por los proveedores licenciados o regulados correspondientes, no por el software de la billetera. Describe el diseño operativo; no afirma que Confío carezca de obligaciones.

- Didit soporta la verificación actual. El usuario presenta documento oficial y selfie en vivo; Didit realiza controles de documento, prueba de vida y coincidencia facial. Sus métricas se separan del teléfono y de la aprobación por proveedores fiat o RWA.
- La dirección residencial es un requisito adicional. En operaciones Koywe, Confío solicita que el usuario la ingrese y, con su consentimiento, la envía a Koywe para su verificación. <sup>[13]</sup>
- Koywe ofrece rieles activos en siete mercados y aplica controles propios de identidad, dirección, elegibilidad, sanciones y transacciones. <sup>[13]</sup>
- Guardarian ofrece SEPA y acceso en dólares con tarjeta. Su alta incluye dirección residencial y controles propios de identidad, dirección, elegibilidad, método de pago, sanciones y transacciones. <sup>[13]</sup>
- Verificar teléfono o identidad Didit no garantiza aprobación de Koywe, Guardarian, Ondo u otro proveedor.
- USDY se limita a participantes no estadounidenses elegibles y direcciones exactas aprobadas bajo el marco de Ondo. <sup>[7, 10]</sup>
- Los controles del emisor cUSD y de contratos cUSD+ son distintos de poseer la clave de la billetera.
- Nuevos países y rieles se lanzan tras los controles legales, operativos y del proveedor correspondientes.

## 11. Riesgos y mitigaciones

Ningún producto financiero blockchain carece de riesgo. Esta tabla resume riesgos materiales, mitigaciones actuales y exposición residual; no es exhaustiva.

| Riesgo | Mitigación actual | Exposición residual |
| --- | --- | --- |
| Activo subyacente y emisor | cUSD usa diseño respaldado por USDC; cUSD+ mantiene USDY y divulga estructura y elegibilidad. | Persisten riesgos de pérdida de paridad, emisor, custodia, reservas, legales y de rescate. |
| Contratos inteligentes | Código abierto, despliegue verificado, pruebas por capas, revisión adversarial continua, gobernanza multipartita y protecciones de oráculo. | Pueden existir errores, fallos de integración y actualización. |
| Oráculo | Umbral de protección detiene rutas de valor y exige respuesta de gobernanza con evidencia. | Datos incorrectos o indisponibles pueden retrasar depósitos y rescates. |
| Liquidez y rescate | cUSD+ admite rescate definido a USDT desde el primer día. | Liquidez InstantManager, proveedores, red o cumplimiento pueden retrasar salidas. |
| Permisos | USDY y bóveda siguen compradores autorizados y elegibilidad Ondo. | Ondo puede cambiar elegibilidad o bloquear una dirección. |
| Recuperación de claves | Claves del dispositivo y nube personal evitan una bóveda central. | Pérdida de dispositivo/nube o fallos de recuperación pueden afectar acceso. |
| Gobernanza de actualizaciones | Safe multipartito, registros públicos, verificación de código y layout. | Firmantes autorizados podrían aprobar cambios dañinos o no responder. |
| Rampas fiat | Koywe y Guardarian activos; nuevos proveedores solo tras verificar contrato y producción. | Cobertura, métodos, bancos, precios y suspensiones pueden cambiar. |
| Regulación y crimen financiero | Documento y selfie en vivo; dirección aportada por usuario; verificación del proveedor, sanciones, controles transaccionales, mercados por fases y revisión legal. | La identidad no elimina fraude o actividad ilícita; proveedores o autoridades pueden rechazar, demorar, reportar o restringir. |
| UX multicadena | La aplicación abstrae cadenas y separa funciones. | Puentes, conversiones, recuperación y fallos por cadena añaden complejidad. |
| Métricas y concentración | Se explican definiciones y carácter no auditado. | Uso o TVL inicial concentrado puede no predecir adopción amplia. |

## 12. Hoja de ruta y estado actual

| Área | Completado / actual | Próximo hito verificable |
| --- | --- | --- |
| Pagos cUSD | Billetera Algorand y stack de pagos en producción; contactos, rampas, pagos y módulos empresariales abiertos. | Profundizar uso financiado, comercios y confiabilidad por país. |
| Contratos cUSD+ | Proxy BSC Mainnet desplegado, actualizado, verificado e integrado con USDY/USDT/InstantManager/oráculo de producción. | Ampliar uso manteniendo respaldo, rescate y gobernanza transparente. |
| Operaciones cUSD+ | Safe multipartito, registro público y transacciones patrocinadas. | Ampliar monitoreo, automatización y procedimientos de incidentes. |
| Seguridad | Pruebas por capas: adversarial, unitarias, fork, invariantes/fuzz, diferenciales y actualizaciones; código público. | Ampliar continuamente cobertura, modelos de amenaza y evidencia pública. |
| Acceso fiat | Koywe activo en siete mercados; Guardarian para SEPA y tarjetas. | Agregar proveedores verificados y rutas alternativas. |
| Distribución | 8.004 usuarios con teléfono completo; 177 con documento y selfie Didit; ≈480.000 de audiencia y prácticamente cero medios pagados. | Repetir el ciclo contenido→usuario financiado, retención, referidos y cohortes sin depender de subsidios. |

### 12.1 Principios de medición

Confío distingue registros, teléfono completo, verificados, financiados, dispositivos alcanzables, activos y saldos retenidos. Para cUSD+: usuarios financiados, TVL, depósitos brutos, rescates, flujo neto, saldos medio y mediano, retención, origen fiat, concentración y cohortes. Para remesas: origen/destino, volumen completado, repetición, valor mediano, tiempo, costo total divulgado y comportamiento del receptor: retirar, conservar, transferir o gastar.

La distribución se mide como embudo: alcance de contenido, visita, instalación, teléfono, identidad, primer fondeo, saldo retenido, repetición y referido. Se distinguen adquisición orgánica y campañas pagadas por contenido y país.

### 12.2 La próxima prueba

> **De infraestructura a uso retenido**
>
> La próxima prueba es adopción sostenida: usuarios financiados, depósitos repetidos, rescates confiables, saldos retenidos y flujo fiat medible en varios mercados.

## 13. Aviso legal

Este documento se ofrece solo con fines informativos y de referencia técnica. No constituye asesoría de inversión, legal, tributaria, contable o financiera; tampoco prospecto, oferta, solicitud, recomendación ni promesa de rendimiento. Las descripciones reflejan el diseño y estado al 23 de julio de 2026 y pueden cambiar.

cUSD y cUSD+ no son depósitos bancarios, no están cubiertos por seguro de depósitos y pueden no estar disponibles en ciertas jurisdicciones o para ciertas personas. Stablecoins, notas tokenizadas, contratos, cadenas, oráculos, puentes, proveedores fiat y custodios pueden fallar, suspenderse, perder valor o quedar sujetos a nuevas reglas.

Todo rendimiento de cUSD+ es variable, depende de USDY y la bóveda y no está garantizado. USDY y cUSD+ están sujetos a elegibilidad Ondo, cumplimiento, proveedores y ley aplicable.

Ondo Stocks son productos financieros tokenizados, no acciones emitidas directamente por Confío. Disponibilidad, ejecución, transferencia, rescate, derechos económicos y elegibilidad geográfica se rigen por términos de Ondo, cotizaciones, proveedores y ley. No están disponibles para personas estadounidenses mediante el flujo contemplado.

$CONFIO está separado del respaldo de cUSD y cUSD+. Este documento no modifica términos, asignación, bloqueos, derechos o divulgaciones de $CONFIO. El usuario debe revisar términos definitivos, riesgos, contratos, proveedores y ley local.

## Notas

Los títulos de las fuentes se conservan en su idioma original para mantener referencias bibliográficas exactas.

1. Inter-American Development Bank, “Remittances to Latin America and the Caribbean Ease After 2025 Surge,” 16 June 2026: remesas regionales estimadas en US$173.700 millones en 2025, +7,3%. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge
2. Chainalysis, “Latin America Emerges as Crypto Powerhouse Amid Volatile Growth,” 2 October 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/
3. Repositorio público y README de Confío: aplicación, backend, contratos, cUSD, billetera, pagos y planillas. https://github.com/caesar4321/Confio
4. Confío, “Por qué Confío no guarda tu dinero - y por qué eso importa,” fuente del proyecto, consultada en julio de 2026.
5. Algorand Foundation Developer Portal, “Instant Finality,” 5 March 2024. https://developer.algorand.org/solutions/avm-evm-instant-finality/
6. Algorand Developer Portal, documentación de transacciones y tarifas. https://developer.algorand.org/docs/get-details/transactions/
7. Ondo Finance, “USDY Basics,” consultado en julio de 2026. https://docs.ondo.finance/general-access-products/usdy/basics
8. Confío, “cUSD+ deployment record - BSC mainnet,” actualizado el 20 de julio de 2026. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md
9. BscScan, proxy ERC1967 de Confío Dollar+, `0x3C29417eb4314155e63d4C7D4507852b87763Ed1`. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code
10. Ondo Finance, “Integrating with the USDY_InstantManager contract.” https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration
11. Confío, `CusdPlusVault.sol`: contabilidad, rescate, protección de oráculo y participación de rendimiento del 15%. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol
12. BNB Chain, introducción y finalidad de BNB Smart Chain. https://docs.bnbchain.org/bnb-smart-chain/introduction/
13. Registros internos de socios de Confío, julio de 2026: acuerdos e integraciones productivas de Koywe y Guardarian; los términos comerciales se rigen por sus contratos.
14. Analítica interna de Confío, 23 de julio de 2026: teléfono, documento/selfie Didit y FCM. No auditada. Didit es distinto de dirección, screening transaccional y elegibilidad por proveedor.
15. Analítica interna del canal del fundador, 23 de julio de 2026. La audiencia es aproximada y cambia.
16. Benedetto Biondi, “The New Face Of Global Payments: Onchain Consumer Finance Apps,” *Forbes Technology Council*, 6 July 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/
17. Algorand, información oficial de red, consultada el 23 de julio de 2026: “0 downtime in 7 years (and counting).” https://algorand.co/
18. Ondo Finance, “Ondo Stocks” y documentación Global Markets API, julio de 2026. https://ondo.finance/ondo-stocks y https://docs.ondo.finance/api-reference/quickstart
19. Fondo Monetario Internacional, documentación histórica del *corralito*, conversión de depósitos y controles; revisión de flexibilización en 2025. https://www.elibrary.imf.org/display/book/9781589062245/back-1.xml y https://www.imf.org/es/news/articles/2025/07/31/pr25272-argentina-imf-completes-first-review-of-the-extended-arrangement-under-the-eff
20. Fondo Monetario Internacional, “Digital Money and Central Banks Balance Sheet,” Working Paper No. 2022/206: dolarización real de Venezuela. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml
21. Fondo Monetario Internacional, “Bolivia: 2025 Article IV Consultation,” Country Report No. 2025/116. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384
22. Superintendencia de Banca, Seguros y AFP del Perú, *Carpeta de Información del Sistema Financiero*, febrero de 2026. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF
23. Banco de México, agregados monetarios 2024 y estadísticas de remesas 2025. https://www.banxico.org.mx/TablasWeb/informe-anual/compilacion-2024/7EF1402E-1443-4070-9C0A-6B352272C3B9.html y https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadroAnalitico&idCuadro=CA11&locale=es&sector=1
24. Inter-American Development Bank, *Remittances to Latin America and the Caribbean in 2025: Adaptations in a Context of Uncertainty*: origen EE.UU./Europa/España y 53,4% estadounidense para Colombia. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf
25. UNHCR, *Global Report 2025 — Situation Overview: Colombia*: aproximadamente 2,8 millones de venezolanos en Colombia. La oportunidad del corredor es una inferencia de Confío, no una estimación de volumen. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

### Procedencia del documento

Preparado a partir del whitepaper anterior, pitch deck y materiales de producto, registros actuales de Koywe y Guardarian, repositorio y despliegues públicos, documentación oficial de Algorand/BNB Chain/Ondo, literatura citada y métricas internas proporcionadas para esta actualización.
