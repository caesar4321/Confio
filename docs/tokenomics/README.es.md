# Tokenomics de $CONFIO

**Oferta fija. Asignaciones verificables. Utilidad ganada mediante participación real.**

**Referencia global · Versión 2.0 · Julio de 2026**
Julian Moon · Fundador y CEO
[confio.lat](https://confio.lat) · [GitHub](https://github.com/caesar4321/Confio)

**Traducción de cortesía:** Este documento es una traducción al español. La [versión original en inglés](README.md) es la única versión oficial y vinculante de referencia. Si existe alguna diferencia, prevalece el texto en inglés. También está disponible la [traducción al coreano](README.ko.md).

## Cómo leer este documento

Este documento describe la oferta fija, la asignación prevista, el calendario de preventa, los fondos de recompensas, el vesting, la política multicadena y los riesgos materiales de $CONFIO. Sustituye la Edición Inglesa de 2025.

$CONFIO es independiente de los productos financieros de Confío:

- **cUSD** es el activo de pagos en Algorand.
- **cUSD+** es el producto de ahorro en BNB Smart Chain respaldado por Ondo USDY.
- **$CONFIO** es el token de comunidad, recompensas y futura utilidad del ecosistema. No respalda cUSD ni cUSD+.

Nada en este documento promete precio de mercado, listado en un exchange, rendimiento, participación en ingresos, propiedad de la empresa ni derecho sobre las ganancias de Confío.

## 1. Principios

$CONFIO se diseña alrededor de cinco principios:

1. **Oferta fija:** no se puede acuñar $CONFIO adicional.
2. **Identidad pública:** el Asset ID oficial de Algorand es la defensa principal contra activos falsos.
3. **Participación real:** las recompensas dependen del uso verificado del producto o de contribuciones tempranas documentadas, no de airdrops indiscriminados.
4. **Concentración visible:** las grandes asignaciones del fundador y colaboradores se divulgan y bloquean en el tiempo.
5. **Integridad entre cadenas:** ninguna representación o migración futura puede duplicar la oferta económica.

La tokenomics no sustituye la adopción. La relevancia de largo plazo de $CONFIO depende de que Confío atienda usuarios reales y establezca funciones útiles y legalmente sostenibles para el token.

## 2. Identidad on-chain y oferta fija

| Parámetro | Estado actual |
| --- | --- |
| Red | Algorand Mainnet |
| Estándar | Algorand Standard Asset (ASA) |
| Nombre | Confío |
| Unidad | CONFIO |
| Asset ID | **3351104258** |
| Decimales | 6 |
| Oferta fija | **1.000.000.000 CONFIO** |
| Autoridad manager | Ninguna |
| Autoridad freeze | Ninguna |
| Autoridad clawback | Ninguna |

[Verificar $CONFIO en Pera Explorer](https://explorer.perawallet.app/asset/3351104258/) o mediante la [API de Algorand Mainnet](https://mainnet-api.algonode.cloud/v2/assets/3351104258).

Sin autoridad manager no se pueden cambiar los parámetros ni la oferta. Sin freeze ni clawback, Confío no puede congelar ni recuperar por la fuerza los $CONFIO de una cuenta de usuario. El campo informativo reserve de Algorand no permite acuñar y no cambia la oferta fija.

Los usuarios deben verificar el Asset ID, no solo el nombre o ticker.

## 3. Asignación

| Asignación | Tokens | Porcentaje | Política de liberación |
| --- | ---: | ---: | --- |
| Preventa pública | 74.000.000 | 7,40% | Bloqueados hasta completar la Fase 3 y el evento oficial de lanzamiento/desbloqueo en DEX |
| Recompensas por referidos y uso | 7.400.000 | 0,74% | Ganadas y reclamadas según las reglas activas |
| Fondo de Invitación Cultural | 15.000.000 | 1,50% | Vesting lineal previsto de 90 días después del disparador preventa/DEX |
| Co-Builder Creativa | 10.000.000 | 1,00% | Bloqueados hasta el disparador y luego vesting lineal durante 24 meses |
| Reserva del fundador y ecosistema | 893.600.000 | 89,36% | Bloqueados hasta el disparador y luego vesting lineal durante 36 meses |
| **Total** | **1.000.000.000** | **100,00%** | Fijo |

La asignación de 10.000.000 para la Co-Builder Creativa se separó del remanente original de 903.600.000 controlado por el fundador. No aumentó la oferta. Después de esa reasignación, la reserva del fundador y ecosistema es de 893.600.000.

El Fondo de Invitación Cultural queda fijado en 15.000.000 en esta versión. Cualquier aumento futuro exigiría una reasignación pública desde otra categoría; la oferta total no puede aumentar.

## 4. Preventa pública

La preventa pública tiene cinco ventanas de precio. La Fase 1 contiene tres subrondas operativas; las Fases 2 y 3 son rondas independientes.

| Ventana | Precio de referencia | Meta/tope de recaudación | Tokens al alcanzar la meta |
| --- | ---: | ---: | ---: |
| Fase 1-1 | US$0,20 | US$250.000 | 1.250.000 |
| Fase 1-2 | US$0,25 | US$350.000 | 1.400.000 |
| Fase 1-3 | US$0,30 | US$400.000 | aproximadamente 1.333.333,33 |
| Fase 2 | US$0,50 | US$10.000.000 | 20.000.000 |
| Fase 3 | US$1,00 | US$50.000.000 | 50.000.000 |
| **Total** | — | **Hasta US$61.000.000** | **hasta 74.000.000 asignados** |

La aritmética de metas y precios utiliza aproximadamente 73.983.333,33 tokens. Los aproximadamente 16.666,67 restantes permanecen dentro de la asignación fija de 74.000.000 para redondeo y conciliación final; no aumentan la asignación.

Las metas son importes máximos del programa, no pronósticos ni compromisos. Los tokens no vendidos permanecen dentro de la asignación de preventa hasta que Confío publique una política posterior.

### 4.1 Transiciones operativas de subronda

El backend representa actualmente la Fase 1 como una fase agregada. Las Fases 1-1, 1-2 y 1-3 se implementan como ventanas de precio controladas manualmente:

- en cada transición programada, un operador autorizado actualiza el precio, tope y estado visible en el backend;
- la ronda activa o precio del contrato de preventa se actualiza mediante una transacción administrativa on-chain;
- el precio y snapshot de ronda configurados manualmente en la aplicación de recompensas deben actualizarse para mantener alineada la conversión de referidos;
- la transición no ocurre automáticamente solo porque pase una fecha o se alcance una meta.

El precio y ronda registrados on-chain al realizar una transacción controlan el cálculo. Después de cada transición se deben conciliar backend, contrato de preventa y contrato de recompensas. Estos controles pueden cambiar una ronda activa hacia adelante, pero no aumentar la oferta fija ni la asignación de 74.000.000.

### 4.2 Interpretación del precio

Los precios de preventa son precios de oferta para cada fase. No son valoraciones independientes, precios de mercado garantizados ni promesas de que un DEX abrirá o se mantendrá al mismo precio.

Solo como referencia aritmética:

| Precio | Referencia de valor totalmente diluido |
| ---: | ---: |
| US$0,20 | US$200.000.000 |
| US$0,25 | US$250.000.000 |
| US$0,30 | US$300.000.000 |
| US$0,50 | US$500.000.000 |
| US$1,00 | US$1.000.000.000 |

Estas cifras multiplican el precio por la oferta fija de mil millones. No representan valoración empresarial, tasación ni capitalización esperada.

### 4.3 Bloqueo y reclamo

Las compras crean derechos bloqueados. La política actual es:

- ninguna asignación de preventa se reclama antes de completar la Fase 3 y realizar el evento oficial de lanzamiento/desbloqueo en DEX;
- el desbloqueo on-chain está diseñado para ser permanente una vez ejecutado;
- el comprador debe cumplir las reglas vigentes de reclamo, cuenta y jurisdicción;
- los términos definitivos y registros del producto controlan cada compra.

La asignación de preventa no es oferta circulante antes del desbloqueo.

### 4.4 Elegibilidad

La participación está sujeta a ley aplicable, controles de identidad y sanciones, términos y restricciones geográficas. La implementación actual excluye a residentes de Estados Unidos y a ciudadanos o residentes de Corea del Sur. Las restricciones pueden cambiar, y el acceso técnico no establece elegibilidad legal.

Los fondos de preventa no respaldan cUSD ni cUSD+.

## 5. Recompensas por referidos y uso

El fondo de 7.400.000 tokens recompensa adopción verificada, no la simple creación pasiva de una billetera.

Según el flujo actual:

1. el usuario referido completa una recarga calificante de al menos US$19 equivalentes;
2. completa una conversión USDC→cUSD calificante de al menos US$19 equivalentes;
3. el referido y quien lo invitó reciben elegibilidad para **US$5 equivalentes en $CONFIO cada uno**, convertidos al precio de referencia activo;
4. el reclamo y retiro están sujetos a verificación personal y controles contra identidades duplicadas.

| Precio activo | Cada persona elegible | Total por pareja válida |
| ---: | ---: | ---: |
| US$0,25 | 20 CONFIO | 40 CONFIO |
| US$0,50 | 10 CONFIO | 20 CONFIO |
| US$1,00 | 5 CONFIO | 10 CONFIO |

El control actual utiliza evidencia de identidad personal, no solo teléfono o dispositivo. La persona presenta un documento oficial y una selfie en vivo para pruebas de vida y coincidencia facial. La detección usa la identidad documental normalizada junto con el país emisor. Solo la primera referencia válida de una misma identidad conserva la recompensa.

Los parámetros pueden cambiar prospectivamente. Las reglas mostradas en la aplicación y registradas para un evento concreto controlan ese evento. Las recompensas nunca pueden exceder el fondo financiado.

## 6. Fondo de Invitación Cultural

El fondo reserva 15.000.000 $CONFIO para personas cuya hospitalidad, comidas, transporte, asistencia profesional, donaciones, membresías, regalos de creador u otro apoyo directo documentado ayudó a formar Confío antes de la validación institucional.

No es airdrop público, venta ni salario. Es un programa limitado de reconocimiento.

Salvaguardas actuales:

- fondo fijo: **15.000.000 CONFIO**;
- máximo previsto por persona: **150.000 CONFIO**;
- mínimo previsto para una persona incluida: **1.000 CONFIO**;
- período público de revisión y corrección;
- vesting lineal aproximado de 90 días después del disparador preventa/DEX.

La metodología final, lista elegible, apelaciones y reconciliación agregada deben publicarse antes de distribuir. Las tablas ilustrativas anteriores no se incorporan porque contenían multiplicadores de lealtad superpuestos y no constituían una regla final internamente consistente.

Este fondo es distinto del programa de referidos: uno reconoce contribución humana previa al producto; el otro recompensa adopción verificada.

## 7. Asignación de la Co-Builder Creativa

**10.000.000 CONFIO (1,00%)** corresponden a Susy Ramirez por contribuciones creativas y comunitarias de largo plazo.

La asignación está en una aplicación de vesting de Algorand:

- total bloqueado: 10.000.000;
- duración tras activación: aproximadamente 24 meses;
- inicio no activado al 23 de julio de 2026;
- cantidad reclamada: cero a esa fecha.

[Verificar App ID 3359297921](https://mainnet-api.algonode.cloud/v2/applications/3359297921).

Vesting no significa venta.

## 8. Reserva del fundador y ecosistema

**893.600.000 CONFIO (89,36%)** pertenecen a la reserva del fundador y ecosistema. Es la mayor asignación y crea un riesgo material de concentración.

La reserva está destinada a alineación de largo plazo, contratación, desarrollo, operaciones, alianzas y crecimiento. Estos fines no garantizan cómo se usará, transferirá o venderá una cantidad ya vested.

La asignación está en una aplicación de vesting de Algorand:

- total bloqueado: 893.600.000;
- duración tras activación: aproximadamente 36 meses;
- inicio no activado al 23 de julio de 2026;
- cantidad reclamada: cero a esa fecha.

[Verificar App ID 3359301443](https://mainnet-api.algonode.cloud/v2/applications/3359301443).

Como escala, 36 meses equivalen en promedio a aproximadamente 24,82 millones de tokens vested por mes. El vesting es continuo, no una venta mensual programada, y vested no significa vendido.

La concentración exige mapeo público de billeteras, divulgación del vesting, transparencia de transferencias y reportes disciplinados de tesorería.

## 9. Desbloqueos y oferta circulante

Asignación no significa circulación.

La edición 2025 llamó “oferta circulante inicial” a 96,4 millones (9,64%), combinando categorías que no se liberan al mismo tiempo. Se sustituye por esta definición:

> **La oferta circulante al lanzamiento en DEX son los tokens efectivamente desbloqueados, reclamados, vested y transferibles en ese momento, no el tamaño máximo de cada categoría potencial.**

La cifra dependerá de reclamos de preventa, recompensas ganadas y reclamadas, la parte vested del Fondo Cultural, cantidades vested de fundador o co-builder y cualquier asignación divulgada para liquidez o market making.

Antes del DEX, Confío debe publicar una foto fechada que concilie oferta total, saldos en contratos, derechos de preventa, recompensas pendientes, oferta transferible, liquidez y balances no circulantes.

## 10. Política multicadena e integridad de oferta

$CONFIO es actualmente un ASA de Algorand. cUSD permanece en Algorand para pagos; cUSD+ usa BNB Smart Chain por su integración con Ondo USDY, USDT y contratos EVM.

Este documento no anuncia migración ni versión BSC de $CONFIO. La cadena canónica solo debe reconsiderarse con evidencia sobre utilidad, preparación DEX, liquidez, requisitos de exchanges y uso real.

En una representación futura:

- los tokens Algorand ya distribuidos no pueden duplicarse con un airdrop incondicional;
- debe usarse lock-and-mint, burn-and-claim o mecanismo equivalente;
- cada reclamo debe impedir replay y doble emisión;
- asignaciones no distribuidas pueden emitirse inicialmente en la cadena elegida sin crear copia;
- oferta y circulación agregadas deben ser reconciliables públicamente.

El límite económico de mil millones aplica entre todas las cadenas, no a cada una por separado.

## 11. Utilidad y límite de captura de valor

El rol actual y previsto incluye reconocimiento comunitario, recompensas y futura participación o gobernanza del ecosistema. La utilidad exacta debe implementarse y divulgarse antes de que los usuarios dependan de ella.

$CONFIO actualmente **no** otorga:

- propiedad de Confío;
- derecho sobre activos, ingresos, rendimiento o ganancias;
- derecho sobre reservas de cUSD/cUSD+;
- derecho a USDY u Ondo Stocks;
- buybacks, burns, staking, dividendos o reparto de comisiones garantizados;
- listado garantizado;
- precio o piso de liquidez garantizado.

Los ingresos operativos de Confío—comisiones de merchant/payroll, participación en la apreciación de cUSD+, economía de proveedores fiat o comisiones de Ondo Stocks—no se transfieren automáticamente a holders. Cualquier mecanismo futuro requerirá política pública separada y revisión legal.

## 12. Divulgación antes de un listado DEX

Antes de un listado o desbloqueo oficial, la divulgación definitiva debe publicar:

- fecha, red, Asset ID/contrato y venue;
- oferta exacta desbloqueada y circulante;
- mapeo de billeteras y aplicaciones materiales;
- transacciones de inicio y estado del vesting;
- reclamos y derechos no reclamados;
- distribuciones de recompensas y Fondo Cultural;
- asignaciones y restricciones de liquidez/market making;
- custodia y gobernanza de tesorería;
- cambios de utilidad, cadena o elegibilidad;
- conflictos y acuerdos relacionados.

Ningún precio promocional sustituye esta divulgación.

## 13. Riesgos materiales

| Riesgo | Importancia |
| --- | --- |
| Concentración | La reserva representa 89,36%; el vesting reduce liquidez inmediata, no el riesgo futuro. |
| Valoración de preventa | Los precios implican referencias diluidas altas antes de mercado externo. |
| Desbloqueos | Reclamos y vesting pueden aumentar mucho la oferta transferible. |
| Utilidad | El éxito del producto no crea automáticamente demanda de $CONFIO. |
| Liquidez | Un pool puede ser poco profundo, volátil o inexistente. |
| Regulación | La clasificación puede variar por jurisdicción y tiempo. |
| Operación y contratos | Software de preventa, recompensas, vesting, reclamos o migración puede fallar. |
| Cadena y proveedores | Redes, billeteras, indexadores y exchanges pueden fallar o restringir acceso. |
| Migración | Un mal diseño puede duplicar oferta o dejar holders varados. |
| Fraude | Activos con nombre similar pueden engañar; manda el Asset ID. |
| Sin captura automática | Confío puede crecer sin transferir ingresos o rendimiento a $CONFIO. |

La lista no es exhaustiva.

## 14. Aviso legal

Este documento es informativo y técnico. No es asesoría ni prospecto, oferta, solicitud, recomendación o promesa de retorno.

$CONFIO no es depósito bancario, no está asegurado y puede perder parte o todo su valor. No representa equity, deuda, depósito ni derecho garantizado a ingresos, ganancias, rendimiento, liquidez, redención o listado. Disponibilidad, venta, recompensas, reclamos, transferencias y utilidad pueden restringirse por ley, jurisdicción, identidad, sanciones, proveedores o términos definitivos.

La preventa se rige por términos separados. Si existe conflicto con ley aplicable, acuerdo ejecutado, parámetros on-chain o términos de una transacción, prevalecen estos últimos en la medida exigida.

Las declaraciones futuras son inciertas y pueden cambiar.

## 15. Fuentes y verificación

1. [$CONFIO Asset ID 3351104258, Algorand Mainnet](https://mainnet-api.algonode.cloud/v2/assets/3351104258)
2. [$CONFIO en Pera Explorer](https://explorer.perawallet.app/asset/3351104258/)
3. [Especificación del token](https://github.com/caesar4321/Confio/blob/main/contracts/confio/CONFIO_TOKEN_SPEC.md)
4. [Fases agregadas del backend](https://github.com/caesar4321/Confio/blob/main/presale/management/commands/setup_presale.py), [control administrativo de rondas y precios](https://github.com/caesar4321/Confio/blob/main/contracts/presale/admin_presale.py) y [snapshot de precio para recompensas](https://github.com/caesar4321/Confio/blob/main/contracts/rewards/confio_rewards.py)
5. [Contrato y desbloqueo de preventa](https://github.com/caesar4321/Confio/blob/main/contracts/presale/README.md)
6. [Lógica de referidos](https://github.com/caesar4321/Confio/blob/main/achievements/services/referral_rewards.py) y [política de identidad](https://github.com/caesar4321/Confio/blob/main/docs/security/REFERRAL_REWARD_IDENTITY_POLICY.md)
7. [Vesting Co-Builder, App ID 3359297921](https://mainnet-api.algonode.cloud/v2/applications/3359297921)
8. [Vesting fundador, App ID 3359301443](https://mainnet-api.algonode.cloud/v2/applications/3359301443)
9. [Restricciones geográficas](https://github.com/caesar4321/Confio/blob/main/docs/legal/GEO_BLOCKING.md)
10. [Whitepaper global](https://github.com/caesar4321/Confio/blob/main/docs/whitepaper/README.md)

### Procedencia

Preparado a partir de la tokenomics 2025, el repositorio público actual, el estado de Algorand Mainnet, el whitepaper vigente y las decisiones de producto y estrategia reflejadas al 23 de julio de 2026.
