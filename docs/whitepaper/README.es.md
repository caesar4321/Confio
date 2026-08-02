# Confío: La plataforma de dólares digitales de confianza para América Latina

**Finanzas en dólares creadas para América Latina: dinero controlado por el usuario, distribuido mediante confianza.**

Confío es una aplicación financiera totalmente abierta y no custodial, construida para la realidad del dólar en América Latina. Combina acceso local a dinero fiduciario, dólares con rendimiento, transferencias, pagos, nómina y activos tokenizados en una experiencia móvil familiar, sin exigir que el usuario entienda cripto.

**Referencia global · Versión 4.0 · Julio de 2026**<br>
Julian Moon · Fundador y CEO<br>
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

*Lo tuyo, tuyo. · Blockchain por dentro. Simple como PayPal.*

**Original autoritativo:** El documento en inglés es la única versión autoritativa del whitepaper de Confío. Esta traducción se ofrece por conveniencia y puede quedar rezagada. Si existe una diferencia, prevalece el texto en inglés.

Este documento es la referencia global actual sobre la arquitectura, estrategia, modelo operativo y riesgos materiales de Confío. La asignación y el vesting de $CONFIO se detallan en el documento separado de tokenomics.

<details>
<summary><strong>Contenido</strong></summary>

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Tesis de mercado](#2-tesis-de-mercado)
3. [Sistema de producto en BNB Smart Chain](#3-sistema-de-producto-en-bnb-smart-chain)
4. [Por qué BNB Smart Chain](#4-por-qué-bnb-smart-chain)
5. [cUSD+: ahorro que se puede mover](#5-cusd-ahorro-que-se-puede-mover)
6. [Pagos, nómina y activos tokenizados](#6-pagos-nómina-y-activos-tokenizados)
7. [$CONFIO en BNB Smart Chain](#7-confio-en-bnb-smart-chain)
8. [Billetera, seguridad y arquitectura abierta](#8-billetera-seguridad-y-arquitectura-abierta)
9. [Usuarios, distribución y salida al mercado](#9-usuarios-distribución-y-salida-al-mercado)
10. [Modelo de negocio](#10-modelo-de-negocio)
11. [Cumplimiento y modelo operativo](#11-cumplimiento-y-modelo-operativo)
12. [Riesgos y mitigaciones](#12-riesgos-y-mitigaciones)
13. [Hoja de ruta y estado actual](#13-hoja-de-ruta-y-estado-actual)
14. [Aviso legal](#14-aviso-legal)
15. [Notas](#notas)

</details>

---

## 1. Resumen ejecutivo

Confío es una aplicación de dólares digitales, totalmente abierta y no custodial, para América Latina. Permite guardar, ahorrar, enviar, gastar e invertir mediante una interfaz móvil familiar, sin administrar tokens de gas, memorizar direcciones blockchain ni navegar pantallas de exchange. <sup>[3]</sup>

> **Tesis de producto**
>
> La plataforma de dólares de consumo que gane en América Latina no pedirá al usuario convertirse en experto cripto. Combinará propiedad verificable on-chain con la claridad, recuperación, métodos locales de pago y soporte humano de una fintech moderna. La competencia se decidirá por distribución, confianza y adecuación local, no por paridad de funciones. Confío entra con un canal hispanohablante liderado por su fundador de aproximadamente 480.000 personas, años de relación pública con la región y, hasta hoy, gasto en medios pagados efectivamente igual a cero.

Todo el sistema de producto de Confío se liquida en BNB Smart Chain:

| Componente | Función principal | Diseño |
| --- | --- | --- |
| USDT | Entrada, liquidez y salida universal. | BSC-USDT llega por proveedores locales e internacionales, puede mantenerse o transferirse y es el activo de entrada y salida de cUSD+. |
| cUSD+ | Saldo principal de ahorro y transacciones. | Participaciones acumulativas respaldadas por USDY que pueden ahorrarse, enviarse, gastarse, pagarse por nómina o redimirse a USDT. |
| Ondo Stocks | Acceso elegible a mercados tokenizados. | Compras y ventas dentro de la app se lanzan en la misma actualización y se liquidan mediante Ondo Global Markets en BNB Smart Chain. |
| $CONFIO | Token comunitario y del ecosistema. | BEP-20 de oferta fija con preventa on-chain denominada en USDT. No respalda los saldos en dólares de los usuarios. |

La arquitectura de una sola red sigue el centro económico del producto: Ondo hizo disponibles en BNB Smart Chain USDY, InstantManager, el oráculo, la ruta USDT de suscripción/redención y Global Markets. Confío consolidó pagos, nómina, transferencias y $CONFIO en esa misma red para eliminar cambios de cadena y liquidez fragmentada. <sup>[7, 8, 10]</sup>

Al 23 de julio de 2026, 8.004 usuarios habían completado la verificación telefónica y 177 la verificación de identidad de Didit mediante documento oficial y selfie en vivo para prueba de vida y comparación facial. El flujo de Didit registra una finalización de 61,5% entre quienes lo iniciaron. Confío registra además 2.094 dispositivos alcanzables por notificaciones, 2.092 de ellos usados en los 30 días anteriores. Son métricas internas, no auditadas, y no equivalen a usuarios financiados ni a una definición estandarizada de MAU. <sup>[14]</sup>

La bóveda cUSD+, el delegado de transacciones patrocinadas, el token $CONFIO, las bóvedas de preventa, recompensas y vesting, el escrow de invitaciones, el contrato de pagos a comercios y la bóveda de nómina están desplegados y con código verificado en BNB Smart Chain. Los componentes correspondientes están conectados a producción con controles de exposición gradual. cUSD+ está registrado para la infraestructura permissionada de Ondo e integra USDY, USDT, InstantManager y oráculo de producción. <sup>[8, 9, 17]</sup>

## 2. Tesis de mercado

### 2.1 Un problema de acceso al dólar, no de conocimiento cripto

América Latina no es una crisis monetaria homogénea. Algunos usuarios buscan protección frente a la moneda local; otros necesitan liquidación transfronteriza barata, ahorro seguro en dólares o una forma práctica de pagar y cobrar. Los conecta la demanda de una unidad dólar confiable y el rechazo a la fricción que la rodea. La adopción regional de stablecoins demuestra que este comportamiento ya ocurre on-chain. <sup>[2]</sup>

| Mercado | Necesidad observada | Implicación de producto |
| --- | --- | --- |
| Argentina | Inflación, controles y memoria del *corralito* enseñaron a valorar acceso y control tanto como rendimiento. <sup>[19]</sup> | Custodia, retiros, precios y cambios de reglas deben ser excepcionalmente claros. |
| Venezuela | La inflación extrema convirtió al dólar en reserva y medio cotidiano dentro de una economía fragmentada. <sup>[20]</sup> | Acceso y pagos son inmediatos; sanciones y disponibilidad exigen controles más estrictos. |
| Bolivia | El FMI describió reservas utilizables casi agotadas, brecha cambiaria y acceso oficial severamente limitado. <sup>[21]</sup> | Acceso confiable, precio transparente y QR interoperable resuelven liquidez diaria. |
| Perú | Los hogares mantienen decenas de miles de millones de dólares en depósitos y Yape, PLIN y QR ya normalizaron pagos móviles. <sup>[22]</sup> | El reto no es crear deseo por dólares, sino ofrecer ahorro y pagos portátiles con entradas familiares. |
| México | Depósitos en moneda extranjera y unos US$62.500 millones de remesas muestran demanda de ahorro y transferencia. <sup>[23]</sup> | SPEI, saldo dólar, rendimiento y envíos familiares pueden convivir en un producto. |
| Colombia | EE. UU. aporta más de la mitad de las remesas y Colombia acoge a unos 2,8 millones de venezolanos. <sup>[24, 25]</sup> | PSE, Nequi y banca local conectan remesas con el corredor familiar Colombia–Venezuela. |
| Estados Unidos y España | Son dos mercados de origen esenciales: EE. UU. aporta 35,7% de los flujos sudamericanos y Europa 36,2%, incluidos 19,7 puntos de España. <sup>[24]</sup> | Tarjeta y SEPA deben conectar ingresos de la diáspora con saldos en dólares sin convertir ambos lados en traders. |

El resultado es un **reflejo dólar** regional: las personas buscan USD incluso cuando el acceso es caro, informal o frágil.

### 2.2 Las remesas son una oportunidad de balance

América Latina y el Caribe recibieron unos US$173.700 millones en remesas en 2025. <sup>[1]</sup> En vez de tratar cada remesa como un envío aislado, Confío la convierte en el inicio de una relación financiera: conservar dólares, obtener rendimiento variable con cUSD+, enviar, pagar o retirar localmente.

### 2.3 Convergencia de las finanzas de consumo

Exchanges, fintechs, billeteras y empresas de stablecoins convergen en saldos dólar, rendimiento, tarjetas, transferencias y activos tokenizados. Cuando los menús se parecen, muchos compran a los mismos usuarios cripto con cashback. Confío compite con distribución y confianza local difíciles de replicar y con rieles específicos por país. <sup>[15, 16]</sup>

### 2.4 El problema más profundo: *falta de confianza*

Congelamientos bancarios, controles, fintechs fallidas, brokers informales, spreads ocultos y plataformas especulativas produjeron un déficit de confianza. Confío responde con dos capas: control verificable —la clave nace en el dispositivo y Confío no la posee— y confianza humana mediante educación en español, precios claros, métodos locales, liderazgo visible y soporte contextual. *Lo tuyo, tuyo* es promesa de marca y restricción arquitectónica.

## 3. Sistema de producto en BNB Smart Chain

| Acción | Activo o contrato | Resultado on-chain |
| --- | --- | --- |
| Agregar dólares | USDT | El proveedor entrega BSC-USDT a la dirección propia del usuario. |
| Ahorrar | Bóveda cUSD+ | InstantManager convierte USDT en USDY y la bóveda emite cUSD+ al valor de referencia protegido. |
| Enviar | cUSD+ o USDT | Un receptor elegible recibe cUSD+; otros reciben USDT mediante redención atómica o transferencia directa. |
| Pagar | cUSD+ o $CONFIO, fondeado con cUSD+ o USDT | El comercio cobra en cUSD+ o $CONFIO; el contrato paga al comercio, aplica 0,9% y registra la comisión on-chain. |
| Nómina | cUSD+ con salida opcional a USDT | La empresa fondea un escrow y delegados autorizados firman pagos. |
| Comprar o vender activos | Ondo Global Markets | Las órdenes elegibles usan cotización y attestations de Ondo en BSC. |
| Preventa $CONFIO | USDT | Una transacción patrocinada compra asignación sobre una curva inmutable. |
| Recompensas | RewardVault | Derechos acumulativos se registran off-chain y se reclaman on-chain tras el desbloqueo DEX. |

### 3.1 Despliegues públicos en BNB Smart Chain

Todos están activos en mainnet y tienen código verificado.

| Contrato | Dirección |
| --- | --- |
| Proxy de bóveda cUSD+ | [`0x3C29417eb4314155e63d4C7D4507852b87763Ed1`](https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code) |
| Delegado de lotes patrocinados | [`0xC06BD197b34a587026615C6AEd21301F5E99bc00`](https://bscscan.com/address/0xC06BD197b34a587026615C6AEd21301F5E99bc00#code) |
| Token $CONFIO | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| Bóveda de preventa | [`0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c`](https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code) |
| Bóveda de recompensas | [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code) |
| Bóveda de vesting | [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| Escrow de invitaciones | [`0xeFF0Af29FcB8f010f3B1e58bd5bbA36AEad4D0d6`](https://bscscan.com/address/0xeFF0Af29FcB8f010f3B1e58bd5bbA36AEad4D0d6#code) |
| Pagos a comercios | [`0x039Ebe91283c686F23F4C751600a39567967736D`](https://bscscan.com/address/0x039Ebe91283c686F23F4C751600a39567967736D#code) |
| Nómina | [`0x851cA801c3028D4C0e651d29803f8e35D86d7299`](https://bscscan.com/address/0x851cA801c3028D4C0e651d29803f8e35D86d7299#code) |

### 3.2 Por qué importa una sola red

No se requiere bridge entre ahorro, pagos, nómina, activos tokenizados y $CONFIO; una dirección EVM recibe fondos y activos; y un solo sistema patrocinado cubre gas. Cada producto conserva sus propias reglas económicas, legales y de elegibilidad.

### 3.3 Acceso local e internacional

Koywe ofrece rieles locales activos en siete mercados mediante transferencias bancarias, Alias/CVU, SPEI, QR interoperable, PSE/Nequi y PIX según el país. Guardarian ofrece SEPA en la eurozona y compras en USD con Visa, Mastercard, Apple Pay y Google Pay. <sup>[13]</sup>

## 4. Por qué BNB Smart Chain

### 4.1 El producto siguió la infraestructura de Ondo

La razón principal es Ondo Finance. cUSD+ se diseñó alrededor de USDY, y Ondo desplegó USDY, InstantManager, oráculo, ruta USDT y Global Markets en BNB Smart Chain. Ubicar todo Confío junto a esa infraestructura da una ruta directa y permissionada a ahorro y activos tokenizados. <sup>[7, 8, 10, 18]</sup>

### 4.2 Economía y liquidez de escala de consumo

BNB Smart Chain aporta liquidez USDT, costos bajos, infraestructura EVM madura y un ecosistema de pagos, billeteras, DeFi y RWA. El tamaño de la cadena no crea demanda: el valor depende de usuarios, saldos retenidos, salidas confiables, distribución, seguridad y economía transparente. <sup>[5, 6, 12]</sup>

### 4.3 Compensaciones de red y gobernanza

Interrupción, coordinación de validadores, congestión, cambios de gas, fallas RPC o políticas del ecosistema siguen siendo posibles. Confío usa patrocinio, múltiples RPC, salidas de emergencia, propiedad no custodial y estado público, pero no elimina el riesgo base.

## 5. cUSD+: ahorro que se puede mover

cUSD+ es una participación acumulativa denominada en dólares y respaldada por USDY en la bóveda desplegada. El usuario ve dólares, no shares, gas, approvals u oráculos.

### 5.1 Depósito y redención

USDT llega a la dirección BSC del usuario; un lote patrocinado autoriza y llama la bóveda; InstantManager suscribe USDY; y la bóveda emite cUSD+. Para salir, quema las participaciones, redime USDY y envía USDT directamente al usuario, receptor o riel. La bóveda es el comprador permissionado de USDY; el usuario posee cUSD+.

### 5.2 Valor acumulativo y participación en rendimiento

El valor de referencia asigna 85% de la apreciación positiva de USDY a los holders y 15% a excedente de Confío. No aumenta el número de participaciones; aumenta su valor dólar. El rendimiento es variable y no está garantizado. <sup>[7, 11]</sup>

### 5.3 Respaldo y controles de oráculo

La bóveda publica obligaciones, ratio de respaldo y excedente, redondea a favor del respaldo y limita cobros a excedente comprobable. El owner no puede barrer USDY de respaldo. Una caída o movimiento fuera del umbral detiene rutas de valor hasta una decisión documentada de gobernanza.

### 5.4 Ahorro como saldo transaccional

cUSD+ puede seguir acumulando valor hasta enviarse, gastarse o pagarse por nómina. Cuando no es adecuado para el receptor, Confío lo redime atómicamente y entrega USDT. USDT sigue siendo una alternativa visible de primera clase.

## 6. Pagos, nómina y activos tokenizados

### 6.1 Transferencias entre personas

El usuario firma y Confío patrocina. cUSD+ se transfiere a receptores elegibles, se redime atómicamente a USDT para otros receptores, o se envía USDT directamente. Confío cobra 0% de comisión de plataforma; pueden existir cargos de entrada o salida.

### 6.2 Pagos a comercios

El comercio cobra en una de dos denominaciones: **cUSD+**, el saldo en dólares, o **$CONFIO**, expresado como cantidad de tokens y no como monto en dólares. Ambas liquidan en BNB Smart Chain.

Quien tiene USDT sin convertir puede pagar igual una factura en dólares, incluido quien no es elegible para emitir cUSD+, y el comercio recibe el mismo token que gastó el pagador. USDT es una vía de fondeo del pagador, no una tercera denominación que el comercio pueda cobrar.

El contrato calcula 0,9%, paga el neto al comercio y acumula únicamente comisiones ganadas. El backend firma una autorización de corta duración sobre los términos exactos y el contrato registra la liquidación contra el identificador de la factura: cada factura se liquida una sola vez y nadie sin esa autorización puede consumir su identificador. Cada factura registra además la única red autorizada a liquidarla, de modo que un mismo cobro no puede pagarse dos veces en redes distintas. Aprobación y pago son atómicos.

### 6.3 Nómina y pagos masivos

Las empresas mantienen capital en un escrow cUSD+ y autorizan delegados para pagos específicos. El receptor recibe cUSD+ o USDT redimido, y la contabilidad de comisiones permanece separada del escrow empresarial.

### 6.4 Ondo Stocks

En la misma actualización, usuarios elegibles pueden comprar y vender productos tokenizados de Ondo Global Markets. Confío presenta disclosure y cotización, cobra 0,30% por compra o venta separado de la ejecución de Ondo, obtiene la attestation requerida y patrocina la liquidación en BSC. No está disponible para personas estadounidenses. <sup>[18]</sup>

## 7. $CONFIO en BNB Smart Chain

### 7.1 Token de oferta fija

$CONFIO es un BEP-20 no actualizable de 1.000.000.000 de unidades. No tiene owner, minter, proxy, tax, blacklist, pause ni freeze. La oferta se acuñó una sola vez a la tesorería multipartita. No respalda USDT, cUSD+, USDY ni Ondo Stocks. <sup>[17]</sup>

### 7.2 Preventa on-chain

La preventa usa USDT y una curva continua e inmutable: 0–4M CONFIO, US$0,20→0,30; 4–24M, US$0,30→0,70; 24–74M, US$0,70→1,30. El contrato integra el costo bajo la curva, impide descuentos por dividir compras y abre reclamos solo con respaldo suficiente. La elegibilidad y los términos siguen aplicando. <sup>[17]</sup>

### 7.3 Recompensas y reclamos bloqueados hasta DEX

La actividad elegible se registra en la base de datos y se convierte a CONFIO al precio vivo de la curva. Tras el lanzamiento DEX, una autorización EIP-712 de corta duración permite reclamar la diferencia entre derecho acumulado y monto ya reclamado. La tesorería controla firmante, pausa y fondeo: no es un escrow trustless y los usuarios dependen de su conciliación y fondeo.

## 8. Billetera, seguridad y arquitectura abierta

### 8.1 Modelo no custodial

La clave EVM nace en el dispositivo y el servidor de Confío no la posee. El material cifrado de recuperación se diseña para la nube personal del usuario. <sup>[3, 4]</sup>

> **Ni siquiera nosotros**
>
> Confío nunca posee la clave de la billetera y no puede firmar una transacción ordinaria como el usuario. Los contratos y activos sí conservan sus controles divulgados de elegibilidad, pausa, freeze, upgrade o gobernanza.

### 8.2 Transacciones patrocinadas

Confío usa autorizaciones EIP-7702 y un delegado sin owner: el usuario firma las llamadas y el sponsor paga gas. La política del servidor limita destinos, selectores, montos, receptores, plazos y límites diarios. <sup>[8, 17]</sup>

### 8.3 Código abierto y verificabilidad

App, backend, contratos, despliegues y pruebas son públicos. La seguridad combina pruebas unitarias, fork, invariantes/fuzz, adversariales, diferenciales y ensayos de upgrade; código verificado; gobernanza multipartita; cobros acotados; guardas de oráculo; pausas; protección de replay; slippage y canarios. Ningún método elimina el riesgo. <sup>[3, 8, 9, 17]</sup>

### 8.4 Actualización y gobernanza

La bóveda cUSD+ permanece actualizable porque depende de contratos externos de Ondo que pueden migrar. Otros componentes son más estrechos: token y curva no son actualizables; pagos y nómina restringen administración a acciones definidas.

## 9. Usuarios, distribución y salida al mercado

### 9.1 Métricas actuales

| Métrica | Corte | Definición |
| --- | ---: | --- |
| Usuarios con teléfono completo | 8.004 | Completaron verificación telefónica. |
| Verificados por Didit | 177 | Documento oficial y selfie en vivo con prueba de vida y comparación facial. |
| Finalización de identidad | 61,5% | Completaron Didit entre quienes lo iniciaron. |
| Dispositivos alcanzables | 2.094 | Alcanzables mediante push. |
| Usados en 30 días | 2.092 | Dispositivos alcanzables usados; no se presenta como MAU estándar. |

Son métricas internas no auditadas al 23 de julio de 2026 y no implican que todos estén financiados, activos, sean únicos o elegibles. <sup>[14]</sup>

### 9.2 La confianza es el canal de distribución

La audiencia hispanohablante del fundador suma aproximadamente 480.000. La ventaja no es solo el número: es explicar productos pública, repetida y culturalmente. Confío busca transformar esa confianza en verificación, fondeo, saldos retenidos, pagos repetidos y referidos, con gasto pagado efectivamente cero hasta hoy. <sup>[15]</sup>

### 9.3 Despliegue país por país

Métodos fiduciarios, identidad, elegibilidad USDY, Ondo Stocks, sanciones, retiros y soporte varían. El lanzamiento sigue capacidad comprobada y preparación legal/operativa, no una bandera de marketing.

## 10. Modelo de negocio

| Línea | Política actual |
| --- | --- |
| Transferencias P2P | 0% de Confío; pueden aplicar proveedores. |
| Comercios | 0,9% fijo, aplicado por contrato. |
| Nómina | 0,9% fijo, separado del escrow. |
| Rendimiento cUSD+ | 15% de apreciación positiva para Confío y 85% para holders; variable y no garantizado. |
| Ondo Stocks | 0,30% por compra y venta, separado de Ondo y terceros. |
| Rieles fiduciarios | Precios Koywe y revenue share Guardarian según cotización y contrato. |
| Productos futuros | Posibles comisiones o revenue share sujetos a términos y aprobaciones. |

## 11. Cumplimiento y modelo operativo

**Conozca a su cliente (KYC)** son controles para establecer identidad y, cuando corresponde, residencia. **Prevención de lavado de activos (AML)** son controles de proveedor y transacción contra sanciones, fraude, lavado, financiamiento del terrorismo y otras actividades prohibidas.

Confío está diseñado para que custodia fiduciaria, conversión, verificación y acceso permissionado sean realizados por proveedores relevantes, sin afirmar que el software carezca de obligaciones legales. Didit verifica documento oficial, selfie en vivo, prueba de vida y rostro. Para Koywe, Confío solicita voluntariamente la dirección residencial y, con consentimiento, la entrega para verificación del proveedor. Guardarian también exige dirección y aplica sus propios controles. Verificar teléfono o Didit no garantiza aprobación de Koywe, Guardarian u Ondo. <sup>[7, 10, 13, 18]</sup>

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación actual | Exposición residual |
| --- | --- | --- |
| Activos e issuers | Estructura de USDY y USDT visible. | Depeg, issuer, custodia, reserva, ley y redención. |
| Contratos | Código abierto, despliegues verificados, pruebas y controles acotados. | Bugs, integraciones y upgrades. |
| Oráculo | Umbral detiene rutas y exige respuesta documentada. | Datos erróneos o ausentes retrasan operaciones. |
| Liquidez | Redención a USDT y USDT como fallback. | Ondo, proveedores, red o compliance pueden retrasar salidas. |
| Permissioning | Acceso según elegibilidad; usuario posee cUSD+. | Proveedores pueden cambiar reglas o restringir operaciones. |
| Recuperación | Claves en dispositivo y nube personal. | Pérdida de acceso o defectos. |
| Gobernanza | Control multipartito y registros públicos. | Firmantes autorizados pueden errar o no responder. |
| BNB Smart Chain | Sin bridge, múltiples RPC y salidas. | Una falla de red afecta todo el producto. |
| Rieles fiat | Koywe y Guardarian activos. | Cobertura, precio y disponibilidad cambian. |
| Regulación | Documento/selfie, dirección, screening y geofencing. | No elimina fraude ni rechazo regulatorio. |
| Token | Oferta fija, contratos públicos, curva inmutable y tokenomics separado. | Concentración, vesting, liquidez y volatilidad. |
| Recompensas | Reclamos acumulativos, plazos cortos y bloqueo DEX. | Tesorería controla firmante, pausa, retiros y fondeo. |
| Métricas | Definiciones y fecha divulgadas. | Uso temprano puede ser concentrado. |

## 13. Hoja de ruta y estado actual

| Frente | Completado / actual | Próxima evidencia |
| --- | --- | --- |
| cUSD+ | Proxy mainnet verificado, registrado con Ondo y conectado a contratos de producción. | Escalar con respaldo y redenciones confiables. |
| Patrocinio | Delegado EIP-7702 sin owner y políticas implementadas. | Ampliar canarios y medir costo/fiabilidad. |
| Transferencias | Flujos cUSD+/USDT en backend y móvil. | Despliegue controlado y retención. |
| Comercios | Contrato 0,9% desplegado y conectado. | Exposición gradual y volumen repetido. |
| Nómina | Escrow, delegados, salida USDT y app conectados. | Pilotos empresariales. |
| $CONFIO | Token y preventa continua desplegados y conectados. | Fondear obligaciones antes de reclamos. |
| Recompensas | RewardVault canónico desplegado y bloqueado hasta DEX. | Activar acumulación; luego firmante, cliente, fondeo y unlock. |
| Ondo Stocks | Compra/venta integrada en la misma versión. | Lanzar a elegibles y medir ejecución. |
| Acceso fiat | Koywe en siete mercados; Guardarian SEPA/tarjetas. | Añadir proveedores y fallback verificados. |
| Distribución | 8.004 phone-complete, 177 Didit, audiencia ≈480.000, gasto pagado efectivamente cero. | Convertir en usuarios financiados y saldos retenidos. |

### 13.1 Principios de medición

Confío separa registros, teléfono completo, verificados, financiados, dispositivos alcanzables, activos y saldos retenidos. Mide TVL cUSD+, USDT, depósitos, redenciones, flujo neto, saldo medio/mediano, retención, origen fiat, concentración, comercio, nómina y cohortes por país.

### 13.2 La próxima prueba

> **De infraestructura desplegada a uso retenido**
>
> La próxima prueba es adopción sostenida en BNB Smart Chain: usuarios financiados, depósitos repetidos, redenciones confiables, saldos cUSD+ retenidos, liquidez USDT, actividad comercial y de nómina, y entradas fiat medibles en varios mercados.

## 14. Aviso legal

Este documento es informativo y técnico; no es asesoría ni prospecto, oferta, solicitud, recomendación o promesa de retorno. Refleja el diseño al 31 de julio de 2026 y puede cambiar.

USDT y cUSD+ no son depósitos bancarios ni están asegurados. Stablecoins, notas tokenizadas, contratos, blockchains, oráculos, proveedores, market makers y custodios pueden fallar, suspenderse, perder valor o enfrentar reglas nuevas. El rendimiento de cUSD+ es variable y depende de USDY y de la bóveda. Ondo Stocks son productos tokenizados sujetos a términos, cotizaciones, elegibilidad y ley de Ondo; no están disponibles para personas estadounidenses mediante Confío.

$CONFIO es separado de USDT, cUSD+, USDY y Ondo Stocks. No concede derecho sobre respaldo, ingresos, equity, activos o ganancias de Confío salvo términos definitivos expresos. Deben revisarse tokenomics, términos, contratos, vesting, concentración y ley aplicable.

## Notas

1. BID, remesas regionales 2025: US$173.700 millones. https://www.iadb.org/en/blog/migration/remittances-latin-america-and-caribbean-ease-after-2025-surge
2. Chainalysis, adopción cripto latinoamericana 2025. https://www.chainalysis.com/blog/latin-america-crypto-adoption-2025/
3. Repositorio público de Confío. https://github.com/caesar4321/Confio
4. Confío, “Por qué Confío no guarda tu dinero”.
5. Documentación BNB Smart Chain. https://docs.bnbchain.org/bnb-smart-chain/introduction/
6. Documentación de comisiones y red. https://docs.bnbchain.org/bnb-smart-chain/
7. Ondo, USDY Basics. https://docs.ondo.finance/general-access-products/usdy/basics
8. Registro de despliegue cUSD+ en BSC. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/DEPLOYMENT.md
9. Proxy cUSD+ en BscScan. https://bscscan.com/address/0x3C29417eb4314155e63d4C7D4507852b87763Ed1#code
10. Integración USDY InstantManager. https://docs.ondo.finance/developer-guides/usdy-instant-manager-integration
11. `CusdPlusVault.sol`. https://github.com/caesar4321/Confio/blob/main/contracts/cusd_plus/CusdPlusVault.sol
12. Ecosistema BNB Chain. https://www.bnbchain.org/en/developers
13. Registros de socios Confío, julio de 2026: Koywe y Guardarian.
14. Métricas internas Confío, 23 de julio de 2026; no auditadas.
15. Analítica interna del canal del fundador, 23 de julio de 2026.
16. Benedetto Biondi, *The New Face Of Global Payments*, Forbes, 6 de julio de 2026. https://www.forbes.com/councils/forbestechcouncil/2026/07/06/the-new-face-of-global-payments-onchain-consumer-finance-apps/
17. Contratos y despliegues BSC de Confío. https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus
18. Ondo Stocks y API Global Markets. https://ondo.finance/ondo-stocks
19. FMI, documentación histórica de Argentina. https://www.imf.org/External/NP/ieo/2003/arg/
20. FMI, dolarización real de Venezuela, WP 2022/206. https://www.elibrary.imf.org/view/journals/001/2022/206/article-A001-en.xml
21. FMI, Bolivia Article IV 2025. https://www.imf.org/en/publications/cr/issues/2025/06/02/bolivia-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-567384
22. SBS Perú, depósitos por moneda, febrero de 2026. https://intranet2.sbs.gob.pe/estadistica/financiera/2026/Febrero/SF-2102-fe2026.PDF
23. Banco de México e informe BID 2025. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf
24. BID, *Remittances to Latin America and the Caribbean in 2025*. https://publications.iadb.org/publications/english/document/Remittances-to-Latin-America-and-the-Caribbean-in-2025-Adaptations-in-a-Context-of-Uncertainty.pdf
25. ACNUR, *Global Report 2025 — Colombia*. https://www.unhcr.org/sites/default/files/2026-06/global-report-2025-situation-overview-colombia.pdf

### Procedencia del documento

Traducción de conveniencia preparada a partir del whitepaper autoritativo en inglés, el repositorio público, registros de despliegue BSC, documentación oficial de BNB Chain y Ondo, registros de Koywe y Guardarian, literatura citada y métricas internas proporcionadas para esta actualización.
