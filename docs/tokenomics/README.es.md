# Tokenomics de $CONFIO

**Traducción al español · Versión 3.0 · 31 de julio de 2026**

> **Oferta fija. Preventa continua on-chain. Propiedad del fundador divulgada con claridad.**

Este documento describe el token $CONFIO canónico en BNB Smart Chain, su oferta fija y asignación, la curva continua de preventa, la distribución de recompensas, los compromisos de vesting, los controles de gobernanza y los riesgos materiales.

**[La edición en inglés](README.md) es la única fuente oficial y autoritativa.** Esta versión en español es una traducción de cortesía y puede quedar temporalmente desactualizada. Si existe cualquier diferencia, prevalece la edición en inglés.

$CONFIO es independiente de USDT, cUSD+, USDY, Ondo Stocks y de la empresa operadora. No respalda los saldos en dólares de los usuarios y, por sí solo, no representa acciones, deuda, participación en ingresos ni un derecho sobre los activos o utilidades de Confío.

## Contenido

1. [Principios de diseño](#1-principios-de-diseño)
2. [Token canónico y oferta](#2-token-canónico-y-oferta)
3. [Asignación](#3-asignación)
4. [Preventa pública continua](#4-preventa-pública-continua)
5. [Recompensas por referidos y uso](#5-recompensas-por-referidos-y-uso)
6. [Fondo de Invitación Cultural](#6-fondo-de-invitación-cultural)
7. [Asignación de la co-builder creativa](#7-asignación-de-la-co-builder-creativa)
8. [Asignación del fundador](#8-asignación-del-fundador)
9. [Vesting, reclamos y oferta circulante](#9-vesting-reclamos-y-oferta-circulante)
10. [Límites de utilidad y valor](#10-límites-de-utilidad-y-valor)
11. [Divulgación para el lanzamiento en DEX](#11-divulgación-para-el-lanzamiento-en-dex)
12. [Riesgos materiales](#12-riesgos-materiales)
13. [Aviso legal](#13-aviso-legal)
14. [Fuentes primarias](#14-fuentes-primarias)

---

## 1. Principios de diseño

1. **Un único token canónico:** solo el contrato divulgado en BNB Smart Chain es oficial.
2. **Tope fijo:** se acuñaron 1,000,000,000 CONFIO una sola vez. El token no tiene propietario, minter ni función de pausa. Cada titular puede quemar sus propios tokens, por lo que la oferta puede disminuir, pero no aumentar.
3. **Precio continuo:** la preventa pública no tiene fases, rondas ni ventanas de precio seleccionadas manualmente. El precio depende de los tokens vendidos acumulados bajo una curva lineal por tramos e inmutable.
4. **Propiedad del fundador declarada directamente:** 893,600,000 CONFIO corresponden a la asignación del fundador. Que estén bajo custodia de tesorería no los convierte en una reserva de ecosistema indefinida.
5. **Un derecho de reclamo no es circulación:** las asignaciones de preventa y los derechos de recompensa no circulan hasta que se habilita el mecanismo correspondiente y los tokens son reclamados.
6. **Reglas on-chain donde más importan:** el límite de oferta, la curva, la contabilidad de compras y la verificación de respaldo de la preventa se aplican mediante contratos públicos.
7. **Límites de confianza explícitos:** el fondo de recompensas y las futuras operaciones de vesting conservan controles de tesorería divulgados; no se presentan como trustless cuando no lo son.
8. **Sin retorno garantizado:** los precios de preventa, las utilidades del token y los planes de listado no garantizan valor de mercado, liquidez, rendimiento ni apreciación.

---

## 2. Token canónico y oferta

| Campo | Valor canónico actual |
|---|---|
| Red | BNB Smart Chain |
| Estándar | BEP-20 / ERC-20 |
| Nombre on-chain | Confio |
| Nombre de marca | Confío |
| Símbolo | CONFIO |
| Decimales | 18 |
| Oferta inicial y máxima | 1,000,000,000 CONFIO |
| Contrato canónico | [`0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8`](https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8) |
| Vault canónico de vesting | [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code) |
| Poderes privilegiados del token | Sin propietario, sin minter y sin pausa a nivel del token |
| Extensiones | ERC-2612 Permit y Burnable iniciado por el titular |

La oferta completa de mil millones de tokens se acuñó una sola vez a la tesorería multipartita del proyecto durante el despliegue. Distribuir desde esa tesorería conforme a este documento no constituye una nueva emisión.

El nombre on-chain usa la forma ASCII **“Confio”** porque los exploradores y wallets muestran metadatos acentuados de manera inconsistente. El producto y la marca siguen siendo **“Confío.”**

El contrato canónico reemplaza el primer despliegue con nombre acentuado en `0xd57BEc35857839DC33F6FaBE7356C6a19a8d72c1`. Ese contrato fue abandonado antes de cualquier distribución externa o conexión con la preventa, y su oferta completa fue quemada. No debe considerarse un token $CONFIO oficial.

---

## 3. Asignación

| Asignación | CONFIO | Porcentaje de la oferta inicial | Principio de liberación |
|---|---:|---:|---|
| Preventa pública | 74,000,000 | 7.40% | Las asignaciones quedan bloqueadas hasta el lanzamiento oficial en DEX y el desbloqueo irreversible de reclamos |
| Recompensas por referidos y uso | 7,400,000 | 0.74% | Se acumulan según las reglas activas; los reclamos on-chain permanecen bloqueados hasta el lanzamiento en DEX |
| Fondo de Invitación Cultural | 15,000,000 | 1.50% | Vesting lineal de 90 días después del evento de activación publicado |
| Asignación de la co-builder creativa | 10,000,000 | 1.00% | Vesting lineal de 24 meses después de la activación |
| Asignación del fundador — Julian Moon | 893,600,000 | 89.36% | Vesting lineal de 36 meses después de la activación |
| **Total** | **1,000,000,000** | **100.00%** | Oferta inicial fija |

La asignación de 89.36% se muestra intencionalmente como asignación del fundador. La preventa y las asignaciones divulgadas para colaboradores y comunidad son partes de la oferta fija puestas a disposición por una startup liderada por su fundador; no convierten $CONFIO en acciones de la empresa.

Los 10,000,000 tokens de la co-builder creativa se separaron de la asignación original de 903,600,000 tokens de Julian Moon. La oferta total no aumentó. El Fondo de Invitación Cultural permanece limitado a 15,000,000 tokens salvo que una versión futura reasigne de forma transparente tokens de otra categoría; el contrato no puede acuñar oferta adicional.

---

## 4. Preventa pública continua

### 4.1 Una curva, sin fases

La preventa ofrece hasta 74,000,000 CONFIO mediante una sola curva continua denominada en USDT. No existen Fase 1, Fase 2, Fase 3, subrondas, cambios de precio programados ni transiciones manuales.

El contrato divide la curva en tres **tramos** matemáticos únicamente para calcular eficientemente un precio continuo:

| CONFIO vendidos acumulados | Movimiento del precio spot | Tokens del tramo | Referencia del costo integrado de la curva |
|---:|---:|---:|---:|
| 0 a 4,000,000 | US$0.20 → US$0.30 | 4,000,000 | US$1,000,000 |
| 4,000,000 a 24,000,000 | US$0.30 → US$0.70 | 20,000,000 | US$10,000,000 |
| 24,000,000 a 74,000,000 | US$0.70 → US$1.30 | 50,000,000 | US$50,000,000 |
| **Curva completa** | **US$0.20 → US$1.30** | **74,000,000** | **US$61,000,000** |

Dentro de cada tramo, el precio spot aumenta linealmente con los tokens vendidos acumulados. Los extremos y la asignación quedaron fijados en el constructor, y el contrato desplegado no contiene una función capaz de cambiarlos.

Las cifras de costo integrado muestran el costo matemático de recorrer cada tramo completo desde su primer token hasta el último. Los ingresos reales en BSC-USDT excluyen montos recaudados por el sistema anterior y también pueden ser menores si la curva no se vende por completo.

Los límites de los tramos **no** crean fases de venta. Una compra puede atravesar un límite en una sola transacción y el contrato aplica a cada parte la porción correspondiente de la curva continua.

### 4.2 Cómo se calcula una compra

El contrato cobra el área matemática exacta bajo la curva para la cantidad adquirida. En términos prácticos:

- el comprador paga todos los precios intermedios desde la posición vendida actual hasta la nueva;
- una compra grande puede abarcar más de un tramo;
- dividir una compra en varias no produce un descuento sistemático;
- el redondeo se realiza de forma conservadora a favor del vault;
- la aplicación lee el precio on-chain actual, en lugar de mantener un precio manual por fase; y
- el comprador firma un pago máximo, por lo que otra compra que mueva la curva por encima de ese límite hace revertir la transacción en vez de cobrar más de lo autorizado.

El contrato es la autoridad sobre el costo y la cantidad acumulada vendida. Los registros del backend respaldan elegibilidad, límites, historial y visualización, pero no pueden seleccionar manualmente otro precio.

### 4.3 Referencias de valoración totalmente diluida

| Punto de la curva | Referencia aritmética con oferta inicial de 1B |
|---:|---:|
| US$0.20 | US$200,000,000 |
| US$0.30 | US$300,000,000 |
| US$0.70 | US$700,000,000 |
| US$1.30 | US$1,300,000,000 |

Estas son referencias simples de precio multiplicado por oferta. No son valoraciones de la empresa, tasaciones independientes, pronósticos, capitalizaciones garantizadas ni promesas de que un mercado secundario cotizará al precio de la curva.

### 4.4 Contrato y controles de la preventa

**Contrato canónico de preventa:** [`0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c`](https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code)

El contrato no es actualizable. Su propietario no puede cambiar la curva ni acuñar CONFIO. Sus poderes administrativos limitados incluyen:

- rotar sponsors de transacciones aprobados;
- pausar nuevas compras;
- asignar o corregir créditos de compras anteriores dentro de un pool limitado;
- conectar una sola vez el token CONFIO canónico;
- abrir los reclamos una sola vez, sujeto a respaldo completo;
- retirar los ingresos de la preventa; y
- retirar únicamente CONFIO que exceda las obligaciones pendientes.

Las compras usan BSC-USDT y lotes patrocinados de transacciones EIP-7702. El backend aplica términos, elegibilidad geográfica, controles de sanciones, límites de compra y verificaciones de cuenta; el contrato aplica independientemente el precio y la contabilidad de asignaciones.

### 4.5 Reclamos y respaldo

Comprar durante la preventa registra una asignación; no vuelve transferibles los tokens inmediatamente.

- Los reclamos permanecen bloqueados hasta el lanzamiento oficial en DEX.
- Antes del desbloqueo irreversible, el vault debe tener suficiente CONFIO canónico para cubrir todas las asignaciones pendientes.
- Después del desbloqueo, el contrato rechaza cualquier nueva obligación que no esté respaldada por tokens ya mantenidos en el vault.
- Cada comprador reclama directamente a la misma dirección BSC propietaria de la asignación.
- El propietario no puede retirar CONFIO reservado para obligaciones no reclamadas.

Por ello, la asignación de preventa no forma parte de la oferta circulante solo por haber sido vendida o acreditada.

Si la preventa se cierra antes de vender los 74,000,000 tokens, el remanente seguirá clasificado dentro de la asignación de preventa hasta que una versión autoritativa posterior divulgue otro destino. No se convierte silenciosamente en asignación adicional del fundador ni en oferta circulante.

### 4.6 Compras anteriores

El vault BSC de reemplazo se inicializó con **17,713.85 CONFIO** vendidos bajo el sistema anterior. Este monto se incluyó en `totalSold`, estableciendo el punto inicial correcto de la curva, y en un pool de migración limitado.

A medida que se vinculan las direcciones BSC actuales de los usuarios, sus asignaciones exactas pueden acreditarse desde ese pool. Cada crédito reduce el saldo restante y no puede crear obligaciones superiores al monto ya contabilizado en la curva. Un crédito erróneo aún no reclamado puede corregirse; una asignación ya reclamada no puede revocarse mediante este mecanismo.

### 4.7 Elegibilidad

La participación está sujeta a los términos definitivos, controles de identidad y sanciones, ley aplicable, límites de cuenta y restricciones geográficas. Actualmente se excluye de la preventa a residentes de Estados Unidos y a ciudadanos o residentes de Corea del Sur. Las restricciones pueden ampliarse o cambiar cuando sea necesario, y el acceso técnico nunca establece elegibilidad legal.

---

## 5. Recompensas por referidos y uso

El pool de 7,400,000 tokens busca reconocer adopción verificada y actividad que califique, no la simple creación pasiva de una wallet.

Cuando se habilita la acumulación de recompensas en BSC:

1. el usuario completa las acciones que califican según los términos visibles;
2. Confío aplica verificaciones de identidad, persona duplicada, cuenta y abuso;
3. la recompensa denominada en dólares se convierte a CONFIO utilizando el precio vivo de la curva on-chain en el momento en que se gana;
4. el monto resultante se registra en la base de datos como parte del derecho acumulado del usuario; y
5. ningún token de recompensa se mueve on-chain hasta que los reclamos se abren con el lanzamiento en DEX.

La fórmula es:

```text
Recompensa en CONFIO = recompensa denominada en dólares ÷ precio vivo de la curva on-chain
```

Así, una misma recompensa en dólares produce menos CONFIO a medida que avanza la curva. Esto elimina el mantenimiento manual de precios por fase, pero no garantiza el valor de mercado posterior de esos CONFIO.

El modelo antiabuso usa evidencia de identidad, no solo verificaciones de teléfono o dispositivo. La verificación incluye documento oficial, selfie en vivo, prueba de vida y comparación facial. Los controles de persona duplicada usan la identidad normalizada y el país emisor. Solo el primer referido válido asociado con una misma identidad verificada puede conservar la recompensa correspondiente.

Los eventos, montos, límites y disponibilidad pueden cambiar de forma prospectiva. Los términos visibles y los datos registrados para cada evento controlan ese evento.

### 5.1 Modelo de reclamo del RewardVault

**RewardVault canónico:** [`0x812b8d86952123bED0a33E92a76211cbbACDe730`](https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code)

Los reclamos usan una firma EIP-712 de corta vigencia sobre el monto acumulado ganado por el usuario. El contrato paga únicamente la diferencia entre ese monto firmado y lo ya reclamado, evitando que una firma repetida pague dos veces.

Este es un **pool de recompensas controlado por tesorería**, no un escrow trustless. La tesorería multipartita puede rotar al firmante, pausar reclamos y retirar fondos, incluso después del desbloqueo. Por ello, los usuarios dependen de los registros de Confío, el servicio de firma, la política de fondeo y la tesorería para honrar obligaciones válidas. Los plazos cortos limitan la vigencia de autorizaciones antiguas o incorrectamente altas.

El RewardVault está desplegado y su código fuente está verificado, mientras la acumulación y los reclamos siguen sujetos a controles operativos. Al lanzar el DEX, Confío debe fondear un tramo adecuado, activar el servicio de firma y el flujo de reclamo del cliente, y abrir los reclamos antes de que los usuarios reciban tokens del vault.

---

## 6. Fondo de Invitación Cultural

El Fondo de Invitación Cultural asigna 15,000,000 CONFIO para reconocer contribuciones comunitarias documentadas realizadas antes de que el producto alcanzara escala convencional.

La estructura prevista es:

- asignación agregada limitada a 15,000,000 CONFIO;
- montos individuales determinados mediante un registro publicado y conciliado;
- vesting lineal de 90 días después del evento de activación publicado; y
- publicación de la metodología final, registro de participantes, proceso de apelación y conciliación agregada antes de distribuir.

Este fondo es independiente de las recompensas por referidos. Las recompensas reconocen adopción del producto; el Fondo reconoce contribución cultural y comunitaria temprana documentada.

---

## 7. Asignación de la co-builder creativa

La asignación de la co-builder creativa es de 10,000,000 CONFIO, o 1.00% de la oferta inicial.

Su liberación prevista es vesting lineal de 24 meses después de la activación; vesting no equivale a venta. El vault BSC canónico está desplegado y verificado, pero esta asignación aún no ha sido fondeada, agregada ni activada. Al activarse deben publicarse beneficiaria, transacción de fondeo, transacción de inicio y monto reclamado.

---

## 8. Asignación del fundador

**893,600,000 CONFIO, o 89.36% de la oferta inicial, están asignados al fundador Julian Moon.** Es la mayor asignación y crea riesgos materiales de concentración, gobernanza, liquidez y percepción de presión vendedora que cada comprador debe evaluar directamente.

Confío usa deliberadamente una analogía con una startup tradicional: el fundador comienza como propietario de la oferta fija y vende o asigna porciones definidas mediante la preventa, programas comunitarios y asignaciones a colaboradores. Esto describe la lógica de propiedad y financiamiento; **$CONFIO no es capital social**, y comprarlo no convierte a nadie en accionista de Confío ni de una entidad afiliada.

La estructura prevista es aproximadamente 36 meses de vesting lineal después de la activación. Distribuir 893,600,000 CONFIO linealmente durante 36 meses equivale en promedio a que aproximadamente **24.82 millones de CONFIO se vuelvan vested por mes**. El vesting es continuo, no una venta mensual programada, y vested no significa transferido ni vendido.

El vault BSC canónico está desplegado, no es actualizable, tiene código verificado y pertenece a la tesorería multipartita. Exige fondeo completo antes de agregar una asignación, vesting lineal después de una transacción de inicio separada, reclamo por el beneficiario, irrevocabilidad después del inicio y retiros de tesorería limitados al excedente.

La asignación del fundador aún no ha sido fondeada, agregada ni activada en ese vault, por lo que su reloj de vesting BSC no está corriendo. Las asignaciones bloqueadas anteriores deben conciliarse uno a uno durante la migración para impedir una doble liberación. Cuando se active, Confío deberá publicar beneficiario, monto, transacciones de fondeo e inicio, duración, monto vested, monto reclamado y conciliación del bloqueo anterior.

El tamaño de esta asignación hace que el mapeo público de wallets, la divulgación del estado de vesting, la transparencia de transferencias y los reportes disciplinados del fundador sean más importantes que declaraciones promocionales sobre alineación a largo plazo.

---

## 9. Vesting, reclamos y oferta circulante

### 9.1 Eventos de liberación

Los siguientes conceptos no deben confundirse:

- **asignado:** incluido en una categoría de este documento;
- **vendido o ganado:** existe un derecho registrado para un comprador o participante;
- **vested:** transcurrió la restricción temporal correspondiente;
- **reclamable:** el contrato y la política permiten retirarlo;
- **reclamado:** los tokens se movieron a la dirección del beneficiario; y
- **circulante:** los tokens son transferibles fuera de un vault bloqueado o sistema de reclamo restringido.

Los reclamos de preventa y recompensas están vinculados al lanzamiento oficial en DEX, no a completar una fase numerada. Los relojes cultural, co-builder y fundador comienzan únicamente mediante sus transacciones de activación divulgadas por separado.

**Vault BSC canónico de vesting:** [`0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A`](https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code)

A la fecha de esta versión, el vault está desplegado, pero las asignaciones del fundador, co-builder y Fondo Cultural no han sido fondeadas, agregadas ni iniciadas en BSC. Desplegar el contrato por sí solo no crea una obligación ni inicia un reloj.

### 9.2 Definición de oferta circulante

Para reportes públicos, la oferta circulante debe incluir solo CONFIO canónico transferible fuera de contratos de distribución bloqueados o reservados. Según la fecha, puede incluir:

- asignaciones de preventa desbloqueadas y reclamadas;
- recompensas válidamente reclamadas;
- tokens culturales, co-builder o del fundador ya vested y efectivamente liberados; y
- otras transferencias expresamente divulgadas por tesorería.

Debe excluir:

- saldos de tesorería no asignados;
- asignaciones de preventa no reclamadas;
- recompensas registradas en base de datos pero no reclamadas;
- asignaciones aún no vested; y
- tokens mantenidos en contratos de distribución para obligaciones futuras.

Los 74,000,000 tokens completos de la preventa no deben reportarse como circulantes solo por estar ofrecidos. Tampoco los pools completos de recompensas o Cultura antes de reclamos o liberaciones reales.

---

## 10. Límites de utilidad y valor

La función actual y prevista de $CONFIO incluye reconocimiento comunitario, recompensas, participación en el ecosistema y posibles mecanismos futuros de gobernanza o beneficios. Cualquier utilidad material debe implementarse y divulgarse antes de que los usuarios dependan de ella.

$CONFIO **no**:

- respalda USDT, cUSD+, USDY u Ondo Stocks;
- representa un derecho de redención por un dólar u otra cantidad fija;
- recibe automáticamente la participación de Confío en el rendimiento de cUSD+, comisiones de comercios, payroll, Ondo Stocks, revenue share de proveedores o ingresos de la empresa;
- representa acciones de Confío o una entidad afiliada; ni
- garantiza voto, listado, liquidez, apreciación, rendimiento, dividendos, recompras o quemas.

Confío puede proponer en el futuro staking, gobernanza, beneficios vinculados a comisiones, recompras, quemas u otros mecanismos. Ninguno debe suponerse hasta que se publiquen términos definitivos, implementación, revisión legal y detalles contractuales.

---

## 11. Divulgación para el lanzamiento en DEX

Antes del lanzamiento oficial y el desbloqueo de reclamos, Confío debería publicar una divulgación fechada que incluya al menos:

- contratos canónicos del token, preventa, recompensas y vesting activo;
- oferta total actual y cualquier quema;
- saldos de tesorería y vaults de distribución;
- total vendido, USDT recaudado, pool anterior no asignado, reclamos y obligaciones pendientes;
- fondeo del pool de recompensas, derechos agregados registrados, reglas y montos reclamados;
- estado de activación del vesting del fundador, co-builder y Fondo Cultural;
- oferta circulante verificada bajo esta definición;
- DEX, par, liquidez inicial, propiedad o bloqueo de liquidez y acuerdos de market making;
- transferencias materiales de tesorería y desbloqueos conocidos; y
- cambios de elegibilidad, utilidad, comisiones o términos legales.

El precio inicial en DEX es un evento de mercado y liquidez. No se garantiza que sea igual al precio actual de la curva ni al extremo final de US$1.30.

---

## 12. Riesgos materiales

| Riesgo | Por qué importa |
|---|---|
| Concentración del fundador | El fundador posee 89.36% de la oferta inicial. El vesting reduce la transferibilidad inmediata, pero no elimina la concentración ni la posible presión vendedora futura. |
| Valoración implícita | La curva alcanza referencias precio-por-oferta de hasta US$1.3B antes de que un mercado externo establezca un precio independiente. |
| Movimiento continuo | Cada compra puede mover la curva. La cotización puede cambiar antes de transmitirse y compradores posteriores pagan más bajo la regla fija. |
| Presión del desbloqueo DEX | Los reclamos de preventa y recompensas pueden crear una oferta transferible significativa mientras la liquidez disponible sea mucho menor. |
| Confianza en tesorería y recompensas | Los derechos viven en la base de datos y dependen de un vault controlado por tesorería, un firmante, fondeo y disponibilidad operativa. |
| Implementación de vesting | El vault BSC está desplegado, pero cada asignación aún debe conciliarse, fondearse, agregarse, activarse y reportarse correctamente. Errores pueden alterar tiempos o crear riesgo de doble liberación. |
| Contratos inteligentes | Los contratos de token, preventa, recompensas, vesting y transacciones patrocinadas pueden contener defectos pese al código público y las pruebas extensas. |
| Red | BNB Smart Chain puede sufrir congestión, concentración, censura, reorganizaciones, exploits, cambios de comisiones o interrupciones. |
| Stablecoin | Las compras usan USDT, que conlleva riesgos de emisor, reservas, depeg, congelamiento, legalidad y redención. |
| Clasificación regulatoria | Las autoridades pueden clasificar el token, preventa, recompensas o utilidad futura de forma diferente entre jurisdicciones o con el tiempo. |
| Elegibilidad y sanciones | Una transacción puede ser técnicamente posible pero no legal o contractualmente disponible. Las reglas pueden cambiar. |
| Sin captura automática de valor | El crecimiento de usuarios, saldos cUSD+, pagos, comisiones o ingresos no crea automáticamente demanda ni distribuciones para $CONFIO. |
| Mercado y liquidez | No se garantiza listado en DEX o CEX. Si existe, el precio puede ser volátil y la liquidez puede desaparecer. |
| Claves y tesorería | La gobernanza multipartita reduce el riesgo de una sola clave, pero no elimina colusión, compromiso, falla del firmante o transacciones erróneas. |
| Suplantación | Cualquiera puede crear tokens con el mismo nombre o símbolo. Solo la dirección canónica de este documento es oficial. |

---

## 13. Aviso legal

Este documento es informativo y puede modificarse cuando cambien contratos, productos, leyes o términos definitivos. No constituye asesoría de inversión, legal, tributaria, contable o financiera ni una promesa de desempeño futuro.

$CONFIO no es un depósito bancario, no está asegurado y puede perder parte o todo su valor. No representa acciones, deuda, un derecho de depósito ni un derecho garantizado a ingresos, utilidades, rendimiento, liquidez, redención, gobernanza, recompras, listado o apreciación.

El acceso a preventa, recompensas, reclamos, transferencias y utilidad puede limitarse por identidad, jurisdicción, sanciones, ley, política de proveedores, controles técnicos o términos definitivos. Cada comprador debe realizar su propia evaluación y obtener asesoría profesional cuando corresponda.

Los contratos desplegados y registros definitivos controlan el comportamiento on-chain. Si este documento contradice un contrato sobre una regla on-chain inmutable, prevalece el contrato. Si marketing, una traducción o redes sociales contradicen esta edición autoritativa en inglés, prevalece el inglés salvo términos definitivos posteriores.

---

## 14. Fuentes primarias

1. ConfioToken canónico en BscScan: oferta inicial de 1,000,000,000; sin propietario, minter ni pausa; ERC-2612 Permit y quema por el titular.
   https://bscscan.com/token/0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8

2. ConfioPresaleVault canónico: curva inmutable, compras en USDT, contabilidad, respaldo, pool anterior y controles de reclamo.
   https://bscscan.com/address/0x1a2dD9b49987DE86dC96fC86c715b62aaDFf095c#code

3. ConfioRewardVault canónico: reclamos EIP-712 acumulados, señal irreversible de desbloqueo DEX, rotación de firmante, pausa y retiros de tesorería.
   https://bscscan.com/address/0x812b8d86952123bED0a33E92a76211cbbACDe730#code

4. Repositorio público de Confío: contratos BSC del token, preventa y recompensas, pruebas y registro de despliegues.
   https://github.com/caesar4321/Confio/tree/main/contracts/cusd_plus

5. ConfioVestingVault canónico: creación de asignaciones totalmente fondeadas, inicio separado, vesting lineal, reclamos, revocación previa al inicio, cambio de beneficiario y retiro solo de excedente.
   https://bscscan.com/address/0xb873e4dbFdf25EcB0F663CA9154F7384d780bE7A#code

6. Repositorio público: lector del precio vivo de la curva y estadísticas de preventa.
   https://github.com/caesar4321/Confio/blob/main/presale/price_utils.py

7. Repositorio público: acumulación de recompensas y conversión con la curva viva.
   https://github.com/caesar4321/Confio/blob/main/achievements/services/referral_rewards.py

8. Whitepaper en inglés: arquitectura actual en BNB Smart Chain y separación de $CONFIO.
   https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.md

---

*$CONFIO es independiente de los productos en dólares de Confío. Verifica el contrato canónico antes de cualquier transacción.*
