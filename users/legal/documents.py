"""
Legal documents content in Spanish. These are the legally binding versions of our legal documents.
Each document is a dictionary with sections, where each section has a title and content.
"""

TERMS = {
    'title': 'Términos de Servicio',
    'version': '1.8.2',
    'last_updated': '2026-10-30',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Introducción',
            'content': 'Bienvenido a Confío, la billetera abierta para la economía del dólar en América Latina. Al utilizar nuestros servicios, usted acepta estos términos. Por favor, léalos cuidadosamente.'
        },
        {
            'title': '2. Definiciones',
            'content': [
                {'term': 'Confío', 'definition': 'La plataforma y servicios proporcionados por Duende Limited, sociedad constituida en la República de Seychelles. "Confío", "nosotros" y "nuestro" se refieren a Duende Limited.'},
                {'term': 'Usuario', 'definition': 'Cualquier persona que utilice nuestros servicios.'},
                {'term': 'Servicios', 'definition': 'Incluye la billetera, transferencias y cualquier otra funcionalidad ofrecida por Confío.'},
                {'term': 'Monedas', 'definition': 'Incluye cUSD, cUSD+, CONFIO y cualquier otra moneda soportada.'},
                {'term': 'cUSD (Confío Dollar)', 'definition': 'Token emitido por Duende Limited sobre BNB Chain, respaldado 1:1 por USDT y convertible únicamente en USDT conforme a la sección 5. No es dinero de curso legal ni otorga derecho a recibir dólares estadounidenses.'},
                {'term': 'a-cUSD (Antiguo Confío Dollar)', 'definition': 'Versión anterior de cUSD sobre Algorand, respaldada 1:1 por USDC y convertible únicamente en USDC a través de su contrato inteligente.'},
                {'term': 'cUSD+', 'definition': 'Token que representa cUSD depositado en la función de ahorro con rendimiento, respaldado 1:1 por USDY de Ondo Finance.'},
                {'term': 'USDT', 'definition': 'Stablecoin emitida por Tether, un tercero ajeno a Confío. Las recargas hacia la función de ahorro se acreditan primero en USDT sobre BNB Chain y se convierten a cUSD+ solo si usted es elegible conforme a la sección 12.'},
                {'term': 'Acciones tokenizadas', 'definition': 'Tokens emitidos por terceros que representan exposición 1:1 a acciones reales de empresas de los Estados Unidos.'}
            ]
        },
        {
            'title': '3. Uso del Servicio',
            'content': [
                'Proporcionar información precisa y completa',
                'Mantener la seguridad de su cuenta',
                'Cumplir con todas las leyes aplicables'
            ]
        },
        {
            'title': '4. Transacciones y Monedas',
            'content': [
                'Irreversibles una vez confirmadas en la blockchain',
                'Sin cargo de gas para el usuario final',
                'Procesadas a través de blockchains públicas: actualmente BNB Chain para cUSD, el ahorro con rendimiento, las acciones tokenizadas y $CONFIO, y Algorand para los saldos existentes de a-cUSD',
                'Podemos incorporar, migrar o dejar de soportar activos y redes. Si dejamos de soportar un activo o una red, se lo informaremos con antelación razonable y mantendremos disponible una vía para retirar o convertir su saldo.'
            ]
        },
        {
            'title': '5. Confío Dollar (cUSD)',
            'content': [
                'cUSD es un token emitido por Duende Limited sobre BNB Chain. Cada cUSD en circulación está respaldado por un USDT depositado en un contrato inteligente público, cuyo saldo cualquier persona puede verificar en la blockchain.',
                'El único derecho que otorga cUSD es convertirlo en USDT a través de ese contrato inteligente, a razón de 1:1 menos la comisión de conversión. Duende Limited no se obliga a pagar, recomprar ni canjear cUSD por dólares estadounidenses ni por ninguna otra moneda de curso legal.',
                'El nombre "Confío Dollar" y la palabra "dólares" en la app describen la unidad de valor que sigue cUSD; no representan un derecho a recibir dólares estadounidenses.',
                'cUSD no es dinero de curso legal, ni un depósito bancario, ni una cuenta de pago. No está protegido por seguros de depósito (como FDIC) ni por fondos de garantía estatales.',
                'cUSD no genera rendimiento ni intereses, y Confío no le paga ningún rendimiento por mantenerlo.',
                'Las conversiones entre USDT y cUSD pagan una comisión que se muestra antes de confirmar la operación. El contrato limita esa comisión a un máximo de 0,9 % por conversión.',
                'USDT es emitido por Tether, un tercero ajeno a Confío. El valor de cUSD depende del valor de USDT: si USDT pierde su paridad o su emisor falla, cUSD puede perder valor en la misma medida.',
                'El contrato inteligente de cUSD es administrado por una billetera multifirma de Confío, que puede actualizarlo y pausarlo. Mientras esté pausado, no es posible enviar cUSD ni convertirlo a USDT.',
                'a-cUSD, la versión anterior sobre Algorand, está respaldada 1:1 por USDC y solo puede convertirse en USDC a través de su contrato inteligente, a razón de 1:1 y con un mínimo de 1 a-cUSD por conversión. Ese contrato también puede pausarse o congelar cuentas concretas; mientras tanto, la conversión no está disponible para las cuentas afectadas.',
                'Podemos limitar o suspender la emisión de nuevo cUSD en determinadas jurisdicciones, incluidos los Estados Unidos de América, para cumplir requisitos regulatorios. Esto no afecta la conversión de cUSD existente a USDT ni el envío o retiro de su saldo.'
            ]
        },
        {
            'title': '6. Preventa y Token $CONFIO',
            'content': [
                'La preventa de $CONFIO da acceso a un token del ecosistema Confío y no representa acciones, participación societaria, dividendos ni derecho a utilidades, ingresos o activos de Confío.',
                'La compra de $CONFIO no constituye una cuenta de ahorro, depósito bancario, contrato de inversión, asesoría financiera ni oferta pública de valores.',
                'El valor, liquidez, disponibilidad y utilidad futura de $CONFIO pueden cambiar o no materializarse. No garantizamos apreciación, mercado secundario, listados ni recompra.',
                'Cualquier funcionalidad, beneficio o acceso futuro asociado a $CONFIO depende del desarrollo del producto, requisitos técnicos, cumplimiento normativo y decisiones operativas de Confío.',
                'Al participar en la preventa, usted declara que compra por su propio criterio y que entiende que puede perder la totalidad del valor entregado.'
            ]
        },
        {
            'title': '7. Ahorro con Rendimiento (cUSD+)',
            'content': [
                'Al usar la función de ahorro, su cUSD se convierte en cUSD+, un token respaldado 1:1 por USDY de Ondo Finance, un activo emitido por terceros y respaldado por bonos del Tesoro de los Estados Unidos de corto plazo, fondos de valores gubernamentales e instrumentos de efectivo.',
                'El rendimiento es variable, se genera a través de USDY y puede cambiar día a día. No es una tasa fija, no está garantizado y puede diferir del mostrado en la app.',
                'cUSD+ no es una cuenta de ahorro bancaria ni un depósito. No está protegido por seguros de depósito (como FDIC) ni por fondos de garantía estatales.',
                'La conversión entre cUSD y cUSD+ depende de contratos inteligentes y de emisores o proveedores terceros; en condiciones excepcionales de mercado o técnicas, los retiros podrían demorarse o verse afectados.',
                'Existen riesgos técnicos y de terceros, incluyendo errores en contratos inteligentes, cambios regulatorios y riesgo del emisor del activo de respaldo. En casos extremos puede perder parte o la totalidad del valor depositado.',
                'Las tasas mostradas ya descuentan la comisión de Confío; cualquier costo adicional de una operación se muestra antes de confirmarla.',
                'Si usted no es elegible para el ahorro con rendimiento conforme a la sección 12, su recarga permanece en USDT: se muestra dentro de su cuenta de ahorro y puede enviarla, gastarla o retirarla en cualquier momento, pero no genera rendimiento ni está respaldada por USDY. En ese caso aplican los riesgos del emisor de USDT (Tether) y no los de Ondo Finance.',
                'Los retiros y las conversiones de salida no están sujetos a restricciones geográficas: no ser elegible no le impide retirar sus fondos. Los retiros siguen sujetos a los riesgos técnicos, de mercado y de terceros descritos en esta sección y a las pausas descritas en la sección 5.'
            ]
        },
        {
            'title': '8. Acciones de EE.UU. (Acciones Tokenizadas)',
            'content': [
                'La función de acciones da acceso a acciones tokenizadas respaldadas 1:1 por acciones reales de empresas de los Estados Unidos, emitidas por terceros (Ondo Finance).',
                'Las acciones tokenizadas representan exposición económica al precio de la acción subyacente y no otorgan derechos directos de accionista, como el voto. Los dividendos se reinvierten automáticamente.',
                'El valor de las acciones puede subir o bajar. Puede perder parte o la totalidad de lo invertido. Rendimientos pasados no garantizan resultados futuros.',
                'Confío no ofrece asesoría financiera ni recomendaciones de inversión. Usted decide qué, cuándo y cuánto comprar o vender bajo su propio criterio.',
                'Precios, horarios de mercado, liquidez y ejecución dependen de mercados y proveedores terceros y pueden diferir de lo mostrado en la app en tiempo real.',
                'La disponibilidad de esta función depende de su jurisdicción, del emisor y de requisitos regulatorios; podemos limitarla o suspenderla cuando sea necesario.'
            ]
        },
        {
            'title': '9. Oro y Bitcoin',
            'content': [
                'La función Oro y Bitcoin le permite comprar y vender tokens que siguen el precio del oro y de Bitcoin, emitidos por terceros. Las operaciones se ejecutan en PancakeSwap, un exchange descentralizado de terceros, independiente de Confío.',
                'Los tokens quedan en su propia cuenta, firmada con su llave. Confío no los custodia.',
                'El precio sube y baja a cualquier hora, también de noche y en fines de semana. Puede perder parte o la totalidad de lo invertido.',
                'Cada compra y cada venta pagan la comisión de conversión de Confío Dollar, que se muestra antes de confirmar.',
                'La compra no está disponible en algunos países (sección 12).',
                'Confío no ofrece asesoría financiera.'
            ]
        },
        {
            'title': '10. Futuros (Contratos Perpetuos)',
            'content': [
                'Futuros le permite abrir posiciones largas o cortas, con apalancamiento, sobre el precio de un activo (criptomonedas, acciones, índices, materias primas y divisas). Las posiciones se abren en Hyperliquid, un exchange descentralizado de terceros, independiente de Confío.',
                'Confío no es un exchange, un bróker ni la contraparte de sus operaciones. Las órdenes se ejecutan en Hyperliquid, en una cuenta a su nombre. Confío prepara las órdenes y transferencias que usted elige y las envía con su firma; usted firma cada operación con su propia llave, y Confío no puede mover su posición sin su firma.',
                'Al abrir una posición o agregar margen, el monto sale de su Confío Dollar y cruza a su cuenta de Hyperliquid mediante Relay, un servicio de terceros para transferir entre redes. Al cerrar, el dinero vuelve por la misma vía a su Confío Dollar. Si al cerrar quedan menos de US$2 en su cuenta de Hyperliquid, ese saldo no se trae de vuelta y permanece a su nombre en Hyperliquid.',
                'Cada salida y cada entrada pagan la comisión de conversión de Confío Dollar (0,9 %). La transferencia entre redes y las comisiones de Hyperliquid tienen su propio costo, y la primera vez Hyperliquid cobra un cargo de activación de su cuenta. Antes de abrir una posición se muestran todos los costos; al agregar margen o al cerrar se muestra la comisión de conversión, y los costos de la transferencia y de Hyperliquid se descuentan del monto transferido.',
                'Con apalancamiento, una variación pequeña del precio puede hacerle perder todo el margen de una posición. Si el precio llega al nivel de liquidación, Hyperliquid cierra la posición; en una liquidación de respaldo se pierde todo el margen de esa posición. Las posiciones abiertas pagan o reciben financiamiento periódicamente, y los precios se mueven las 24 horas.',
                'Una orden «a mi precio» (límite) puede no ejecutarse nunca, o ejecutarse solo en parte. Mientras espera, su margen permanece en su cuenta de Hyperliquid y usted puede cancelarla.',
                'Los niveles de «tomar ganancia» y «limitar pérdida» son órdenes de Hyperliquid que se ejecutan al precio de mercado cuando se alcanzan, por lo que el precio final puede ser distinto del nivel elegido. La protección elegida junto con una orden límite se activa cuando esa orden se ejecuta por completo.',
                'Hyperliquid y Relay son operados por terceros. Pueden pausarse, fallar o cambiar sus reglas, comisiones y mercados, y Confío no puede revertir sus operaciones. Si Confío deja de operar, la Salida de Emergencia de la app le permite retirar sus fondos de Hyperliquid con su propia llave, una vez transcurrido el plazo sin actividad de Confío que la app indica.',
                'Cerrar posiciones y traer su dinero de vuelta nunca está limitado por país. Solo abrir posiciones o agregar margen puede estarlo (sección 12).',
                'Confío no ofrece asesoría financiera ni recomendaciones. Usted decide qué, cuándo y con cuánto apalancamiento operar.'
            ]
        },
        {
            'title': '11. Limitaciones de Responsabilidad',
            'content': [
                'Pérdidas debido a errores del usuario',
                'Problemas de conectividad',
                'Fluctuaciones en el valor de las monedas',
                'Variaciones de rendimiento o de precio en cUSD+, USDY o acciones tokenizadas',
                'Actos u omisiones de emisores o proveedores terceros de los activos subyacentes',
                'Liquidaciones, financiamiento y variaciones de precio en Futuros',
                'Interrupciones, fallas o cambios de Hyperliquid, Relay o PancakeSwap',
                'Acciones de terceros'
            ]
        },
        {
            'title': '12. Restricciones Geográficas',
            'content': {
                'preventa_de_$confio': [
                    'La participación en la preventa de monedas y ciertos servicios financieros de Confío está estrictamente prohibida para:',
                    'Residentes o ciudadanos de los Estados Unidos de América (US)',
                    'Residentes o ciudadanos de Corea del Sur (KR)',
                    'Residentes del Reino Unido (GB)'
                ],
                'ahorro_con_rendimiento_y_acciones': [
                    'cUSD+ (USDY) y las acciones tokenizadas son emitidos por Ondo Finance y están sujetos, además, a las reglas de elegibilidad del emisor.',
                    'Estas funciones no están disponibles para personas ubicadas o residentes en: Estados Unidos, Canadá, Afganistán, Bielorrusia, Corea del Norte, Cuba, Irán, Libia, Myanmar, Rusia, Siria, Somalia, Sudán, Sudán del Sur, ni en las regiones ocupadas de Ucrania (Crimea, Donetsk, Luhansk, Jersón, Zaporiyia y Sebastopol).',
                    'En ciertas jurisdicciones solo están disponibles para inversionistas calificados o profesionales según la ley local, incluyendo Brasil, el Espacio Económico Europeo, el Reino Unido, Suiza, Hong Kong, Singapur y Malasia.',
                    'La lista de jurisdicciones del emisor puede cambiar; la versión vigente está publicada en docs.ondo.finance. Podemos bloquear, limitar o suspender estas funciones para cumplir con esos requisitos.',
                    'Si usted no es elegible, puede seguir usando el resto de Confío con normalidad: recibir, enviar, pagar y retirar dólares digitales. Lo que no está disponible es la conversión a cUSD+ y la compra de acciones tokenizadas. La emisión de nuevo cUSD puede limitarse por jurisdicción conforme a la sección 5.',
                    'Para aplicar estas reglas usamos su país de residencia, que estimamos a partir de la ubicación de su dispositivo, cuando la ha compartido, y de sus direcciones IP, y, cuando corresponde, el país de la dirección IP desde la que se conecta. Si su cuenta tiene un número de teléfono verificado y no contamos con otro dato, usamos el país de ese número.'
                ],
                'oro_y_bitcoin': [
                    'La compra de oro y bitcoin no está disponible para personas ubicadas o residentes en Estados Unidos, Reino Unido, Cuba, Irán, Corea del Norte y Siria.',
                    'Para aplicar estas reglas usamos su país de residencia, que estimamos a partir de la ubicación de su dispositivo, cuando la ha compartido, y de sus direcciones IP, y el país de la dirección IP desde la que se conecta. Si su cuenta tiene un número de teléfono verificado y no contamos con otro dato, usamos el país de ese número.',
                    'Podemos ampliar o reducir la lista de países para cumplir con las reglas de los proveedores o la ley.',
                    'Estas restricciones solo afectan las compras. Si ya tiene tokens, puede venderlos cuando quiera.'
                ],
                'futuros': [
                    'Futuros no está disponible para personas ubicadas o residentes en Estados Unidos, Canadá, Reino Unido, Bélgica, Cuba, Irán, Corea del Norte y Siria, ni donde la ley local lo prohíba.',
                    'Para aplicar estas reglas usamos su país de residencia, que estimamos a partir de la ubicación de su dispositivo, cuando la ha compartido, y de sus direcciones IP, y el país de la dirección IP desde la que se conecta. Si su cuenta tiene un número de teléfono verificado y no contamos con otro dato, usamos el país de ese número.',
                    'Podemos ampliar o reducir la lista de países, o limitar Futuros, para cumplir con las reglas de los proveedores o la ley.',
                    'Estas restricciones solo afectan la apertura de posiciones y el margen adicional. Cerrar posiciones y retirar su dinero sigue disponible.'
                ]
            }
        },
        {
            'title': '13. Cumplimiento del Usuario',
            'content': [
                'Usted es responsable de verificar que el uso de Confío, la compra de $CONFIO y el uso de las funciones de ahorro e inversión estén permitidos en su jurisdicción.',
                'Podemos rechazar, limitar o cancelar acceso a servicios, a la preventa o a las funciones de ahorro e inversión si detectamos restricciones regulatorias, sanciones, fraude, suplantación o incumplimiento de estos términos.',
                'Podemos solicitar verificaciones adicionales de identidad, origen de fondos o residencia antes o después de permitir el uso de ciertas funciones.'
            ]
        },
        {
            'title': '14. Normas de la Comunidad',
            'content': [
                'Comunidad, dentro de Descubrir, permite a personas con identidad verificada publicar textos y fotos, compartir sus propios movimientos (compras y ventas de acciones, de oro y bitcoin y de futuros con su margen y resultado, recargas, retiros y envíos entre usuarios de Confío) con su monto y resultado, comentar, reaccionar, seguir a otros miembros y usar una foto de perfil. Nada de lo que usted mueve se publica sin que usted lo comparta. Su contenido se muestra a otros miembros con su nombre de usuario de Confío, o con un seudónimo si no eligió uno, nunca con su nombre real; las fotos publicadas y la foto de perfil también pueden verse con su enlace.',
                'Cada miembro verificado tiene un perfil de inversor visible para otros miembros con su nombre de usuario o seudónimo: el valor de sus dólares en Confío, sus acciones con su resultado, sus posiciones cerradas, los CONFIO comprados en la preventa y sus estadísticas de operación. Usted puede ocultar su perfil de inversor en cualquier momento desde su perfil.',
                'La Liga ordena a los inversores según su ganancia en dólares en el periodo, contando lo vendido y lo que aún tienen, y a los equipos según el promedio de esa ganancia por miembro. Junto a cada resultado se muestra su porcentaje y, para quien opera futuros, su apalancamiento promedio y sus liquidaciones. En Futuros cuenta el margen, nunca el tamaño apalancado. Para aparecer, su perfil de inversor debe estar visible y debe cumplir los mínimos de inversión que la app indica. La Liga otorga solo insignias, sin premios en dinero.',
                'Tenemos tolerancia cero con el contenido ofensivo y con los usuarios abusivos. No está permitido publicar estafas o fraudes; promesas de ganancias o invitaciones a invertir; pedidos de dinero o la compra y venta de dólares o criptomonedas fuera de la app; datos de contacto o enlaces para continuar en privado; datos personales propios o de terceros; suplantación de Confío, de bancos o de autoridades; spam; odio, acoso o amenazas; contenido sexual; violencia; ni contenido ilegal.',
                'Revisamos con sistemas automáticos, incluido un proveedor de inteligencia artificial (ver la Política de Privacidad), todo el contenido antes de publicarlo y podemos rechazarlo. Usted puede reportar contenido y bloquear a otros miembros desde la app. Revisamos los reportes y podemos retirar contenido en cualquier momento.',
                'Si incumple estas normas podemos retirar su contenido y suspender o cancelar su acceso a Comunidad o a su cuenta.',
                'Usted conserva los derechos sobre lo que publica y nos otorga una licencia no exclusiva y gratuita para mostrarlo dentro de Confío mientras permanezca publicado. Puede eliminar sus publicaciones, comentarios y foto de perfil en cualquier momento.',
                'Debe aceptar estas normas antes de publicar, comentar o usar una foto de perfil, y de nuevo cada vez que cambien.'
            ]
        },
        {
            'title': '15. Modificaciones',
            'content': 'Nos reservamos el derecho de modificar estos términos en cualquier momento. Los cambios entrarán en vigor al publicarlos en nuestro sitio web.'
        },
        {
            'title': '16. Contacto',
            'content': {
                'email': 'legal@confio.lat',
                'telegram': 'https://t.me/confio4world'
            }
        }
    ]
}

PRIVACY = {
    'title': 'Política de Privacidad',
    'version': '1.11.1',
    'last_updated': '2026-10-30',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Información que Recopilamos',
            'content': {
                'personal_info': [
                    'Nombre completo',
                    'Dirección de correo electrónico',
                    'Número de teléfono: crear una cuenta no lo requiere. Lo tenemos si usted lo verificó en una versión anterior de la app o si lo proporciona para una función que lo necesite. Para recargas, retiros y cuentas locales puede indicar un número de contacto, declarado por usted y no verificado, que no reemplaza al número que haya verificado',
                    'Si envía dinero por enlace a un contacto: el número que usted elige de su agenda, guardado solo en relación con su cuenta para gestionar ese envío y recordar qué cuenta Confío lo recibió. No guardamos su agenda, y ese dato no permite a otras personas encontrar a nadie en Confío',
                    'Direcciones de billetera',
                    'Información de transacciones',
                    'Información de cuenta y perfil, incluyendo identificadores internos, país de residencia estimado, país de teléfono si corresponde y nombre de usuario'
                ],
                'kyc_info': [
                    'Fecha de nacimiento',
                    'Número y tipo de identificación (por ejemplo cédula, DNI, pasaporte u otros documentos soportados)',
                    'Fotografía de documento de identidad',
                    'Documento de identidad escaneado o fotografiado',
                    'Selfie con documento de identidad',
                    'Información de dirección residencial',
                    'Datos del documento, como país emisor y fecha de expiración',
                    'Resultados de verificación, rechazos, motivos de revisión y señales de riesgo o AML'
                ],
                'biometric_info': [
                    'Imagen de su rostro tomada en la verificación de identidad (KYC), que guardamos como referencia para confirmar que es usted',
                    'Verificación con su rostro (Confío Face): un breve video de su rostro que se analiza en el momento para comprobar que es una persona real y presente, y una imagen de ese video que se compara con su imagen de referencia. De cada verificación Confío guarda hasta cinco imágenes; Confío no recibe ni guarda el video',
                    'Resultado de cada verificación con su rostro: si fue aprobada, niveles de coincidencia y de detección de persona real, motivo de rechazo, operación para la que se pidió y fecha y hora',
                    'Usamos su rostro solo con su consentimiento, que usted da al continuar en la pantalla de verificación de identidad y en la de Confío Face, para verificar su identidad, confirmar que es usted, comprobar que sus documentos son de la misma persona y proteger su cuenta y la plataforma contra abusos'
                ],
                'device_info': [
                    'Sistema operativo',
                    'Versiones de software y hardware',
                    'Dirección IP',
                    'Ubicación',
                    'Ubicación precisa del dispositivo al verificar Bre-B (coordenadas, precisión y hora de la lectura), solo en ese momento y con su permiso',
                    'ID del dispositivo',
                    'Huella del dispositivo, user agent, sesiones, última actividad y registros de seguridad',
                    'Configuración de notificaciones y tokens de notificaciones push',
                    'Señales de integridad de la app o del dispositivo para prevención de fraude'
                ],
                'payments_and_ramps': [
                    'Métodos de cobro o retiro guardados, como cuentas bancarias, identificadores, números de teléfono o alias según el método',
                    'Metadatos requeridos por proveedores de ramp on/off, incluyendo datos específicos del rail o proveedor',
                    'Dirección declarada por el usuario para recargas y retiros cuando sea necesaria para procesos regulatorios o de proveedor',
                    'Órdenes de recarga y retiro, estados, identificadores externos, montos, monedas y eventos de webhook relacionados'
                ],
                'support_and_content': [
                    'Conversaciones y mensajes de soporte',
                    'Preferencias y estados de lectura de notificaciones o contenido dentro de la app',
                    'Reacciones, suscripciones a canales y otra interacción con contenido publicado en la plataforma',
                    'Publicaciones, comentarios, fotos y foto de perfil que usted comparte en Comunidad, y los movimientos que usted decide compartir con su monto y resultado, que son visibles para otros miembros con su nombre de usuario o un seudónimo; los miembros que sigue y que lo siguen; los bloqueos y reportes que realiza; y el resultado de la revisión automática de ese contenido',
                    'Su perfil de inversor en Comunidad, visible para otros miembros con su nombre de usuario o seudónimo y nunca con su nombre real: el valor de sus dólares en Confío, sus acciones y su resultado, sus posiciones cerradas, los CONFIO comprados en la preventa y sus estadísticas de operación. Puede ocultarlo en cualquier momento desde su perfil'
                ],
                'business_and_payroll': [
                    'Datos de negocios, roles de empleados, permisos, notas internas y configuraciones operativas',
                    'Destinatarios de nómina, corridas de nómina, montos, comisiones, estado de pagos y metadatos asociados'
                ],
                'comprar': [
                    'Si abre una tienda: su nombre, descripción, ciudad y precios de envío; los productos con sus fotos, descripciones, precios y stock; y sus ventas',
                    'Si compra: los productos, montos y estado de sus pedidos, y los datos de entrega que usted indica: dirección, punto marcado en el mapa (coordenadas), referencia y teléfono para el repartidor',
                    'Los datos que guarda en su libreta de Comprar: etiqueta, país, ciudad, dirección, teléfono, referencia, coordenadas cuando las indica, preferencia de dirección predeterminada y fecha de último uso. En su cuenta personal también podemos ofrecerle su dirección de Recarga y su teléfono verificado para completar los datos de entrega si los selecciona; esa dirección no se modifica desde Comprar ni se ofrece en cuentas de negocio',
                    'Las calificaciones y opiniones que deja a las tiendas, y el resultado de la revisión automática de las opiniones y de los productos',
                    'También conservamos con el pedido el motivo que indica al reportar un problema, para que Confío gestione el reclamo, y la referencia o el enlace de seguimiento que proporciona la tienda. El seguimiento es accesible desde la cuenta compradora y desde la cuenta de la tienda, incluidas las personas autorizadas a consultar sus pedidos',
                    'Al abrir Comprar y al elegir «Usar mi ubicación», solicitamos la ubicación del dispositivo si tiene permiso; para buscar su ciudad podemos usar una lectura de hasta cinco minutos de antigüedad. Registramos sus coordenadas, precisión, dirección IP, país estimado de esa IP, fecha de la consulta, usuario, cuenta cuando está disponible y ciudad encontrada, si la hay. Al abrir el selector de entrega sin un punto previo, o al pulsar allí «Usar mi ubicación», solicitamos una ubicación de alta precisión, que puede tener hasta un minuto de antigüedad; mientras el mapa está abierto, también puede mostrar su ubicación si tiene permiso. Puede mover el mapa manualmente: el punto de entrega que confirma no tiene que coincidir con la ubicación del dispositivo',
                    'Si responde la encuesta de interés de Comprar: su país y ciudad, si desea comprar o vender, las categorías y productos que le interesan, el rango de precios, sus ventas mensuales y canales de venta cuando corresponde, y su preferencia de recibir avisos. Asociamos esas respuestas con su usuario y, cuando está disponible, su cuenta, y registramos la versión de la app y las fechas de registro y actualización'
                ]
            }
        },
        {
            'title': '2. Uso de la Información',
            'content': [
                'Proporcionar y mantener nuestros servicios',
                'Procesar transacciones',
                'Procesar recargas, retiros y otras integraciones con proveedores de pago o rampas',
                'Enviar actualizaciones importantes',
                'Mejorar nuestros servicios',
                'Personalizar y operar funciones de soporte, notificaciones y contenido dentro de la app',
                'Análisis operativo y estadístico para mejorar la experiencia del usuario',
                'Cumplir con obligaciones legales y regulatorias',
                'Verificar su identidad y prevenir fraudes',
                'Investigar y prevenir abusos, por ejemplo cuando otra persona intenta verificarse en nombre del titular de la cuenta',
                'Confirmar con su rostro que es usted, y no otra persona con acceso a su cuenta, antes de operaciones sensibles: recargas, retiros, envíos y pagos según su nivel de riesgo, recibir transferencias bancarias en cuentas personales y autorizar nóminas',
                'Cumplir con requisitos de KYC/AML',
                'Detectar que una misma persona verifique varias cuentas o vuelva a registrarse tras una suspensión, comparando los rostros de las verificaciones de identidad',
                'Determinar la elegibilidad geográfica de funciones sujetas a reglas de emisores terceros, usando su país de residencia estimado a partir de la ubicación de su dispositivo, cuando la ha compartido, y de sus direcciones IP, el país de la dirección IP desde la que se conecta y, si no contamos con otro dato, el país de su número de teléfono verificado',
                'Confirmar que Bre-B está disponible en su ubicación al solicitarlo y al usarlo, mediante la ubicación precisa del dispositivo en ese momento, la verificación de integridad de la app (Apple o Google) y el país de su dirección IP',
                'En Comprar, mostrarle tiendas según la ciudad detectada o seleccionada, calcular el precio de envío según las tarifas de la tienda y facilitar la entrega con la dirección o el punto del mapa y la referencia que usted indique. Si proporciona coordenadas y contamos con datos geográficos de referencia, realizamos comprobaciones aproximadas de distancia respecto de las ciudades configuradas; estas comprobaciones no garantizan que el punto esté dentro de una zona exacta de cobertura',
                'Revisar automáticamente los productos y las opiniones de Comprar antes de mostrarlos',
                'Detectar abuso, proteger cuentas, evaluar integridad del dispositivo y monitorear riesgos de seguridad'
            ]
        },
        {
            'title': '3. Compartir Información',
            'content': [
                'Cuando es requerido por ley',
                'Para proteger nuestros derechos',
                'Con su consentimiento explícito',
                'Con proveedores de servicios de verificación KYC y cumplimiento regulatorio',
                'Con Amazon Web Services (AWS), que analiza la verificación con su rostro y compara las selfies de sus verificaciones de identidad. Confío las envía a AWS en la Unión Europea (Irlanda); AWS puede conservar y usar esos datos conforme a sus propios términos. AWS no entrega el video a Confío; solo imágenes de la verificación, que Confío guarda en Suiza',
                'Con proveedores de recargas, retiros, pagos, transferencias y conversión de activos cuando sea necesario para ejecutar una operación solicitada por usted',
                'Con los proveedores de sus recargas, retiros y cuentas locales, su número de contacto y su dirección declarada. Si los cambia en la app, enviamos el cambio a esos proveedores para actualizar sus datos',
                'Con proveedores de infraestructura, almacenamiento, autenticación, notificaciones push y seguridad que actúan como encargados del tratamiento',
                'Con autoridades regulatorias, judiciales o administrativas cuando sea necesario',
                'Con proveedores de pago, bancos o autoridades que lo requieran, los registros de verificación de ubicación de Bre-B como evidencia de cumplimiento',
                'En Comprar, los datos del pedido y de entrega (país, ciudad, dirección, coordenadas cuando las indica, referencia y teléfono) son accesibles desde la cuenta compradora y desde la cuenta de la tienda; si una cuenta pertenece a un negocio, pueden consultarlos su titular y las personas autorizadas a ver sus transacciones. La tienda también recibe el nombre de pila de la persona que creó el pedido, o «Cliente» si no consta ese nombre, para preparar y coordinar la entrega. La tienda puede abrir el punto de entrega en Yango u otra aplicación de mapas, o compartir mediante la aplicación que elija el producto y la cantidad del pedido, la dirección, la referencia, el teléfono y un enlace de Google Maps con las coordenadas; la persona que consulta el pedido desde la cuenta compradora también puede abrir el punto en una aplicación de mapas. Esas aplicaciones reciben los datos que se les envían mediante estas acciones. Las tiendas no reciben su libreta de direcciones ni la ubicación con la que Comprar busca su ciudad',
                'Los pagos de Comprar se registran en BNB Chain, una blockchain pública. Cualquier persona puede consultar los identificadores de los pedidos en la cadena, las direcciones de billetera del comprador y de la tienda, los importes y los estados del pago. Estos registros son permanentes y Confío no puede eliminarlos. La dirección de entrega, las coordenadas, el teléfono, la referencia y el texto del reclamo no se incluyen en esas operaciones en la cadena',
                'Al mostrar los mapas integrados de Comprar, Apple Maps en iOS o Google Maps en Android reciben las coordenadas necesarias para representar la zona y el punto de entrega, aunque no pulse «Abrir en mapas». El selector también puede mostrar la ubicación del dispositivo si ha concedido permiso',
                'En Comprar, los miembros que consultan una tienda pueden ver su nombre, descripción, país, ciudad, productos, precios de envío, estado, calificación, número de calificaciones y pedidos completados, así como el nombre de pila del titular o, si no consta, su nombre de usuario',
                'Las calificaciones de los pedidos, el producto comprado y la fecha de la calificación son visibles para otros miembros; el texto de la opinión se muestra después de aprobarse su revisión automática. La autoría se muestra con el nombre de usuario de Comunidad o un seudónimo de la persona que creó el pedido, incluso si otra persona autorizada de la cuenta compradora envió la opinión. No usamos el campo de nombre real para esa autoría, aunque un nombre de usuario elegido por la persona puede identificarla',
                'Con OpenAI (Estados Unidos), que revisa automáticamente el texto y las fotos que usted publica en Comunidad, sus comentarios y su foto de perfil, junto con la publicación o el comentario al que responde, antes de mostrarlos a otros miembros y de nuevo si otros miembros los reportan; que recibe el título, la categoría, el precio, la descripción y las fotos de los productos enviados a revisión en Comprar, y el texto de las opiniones junto con su número de estrellas, el nombre de la tienda y el título del producto comprado, para revisar los productos y los textos de las opiniones antes de publicarlos; y que procesa los mensajes, audios y fotos que usted envía a Confio Assistant para responderle'
            ]
        },
        {
            'title': '4. Seguridad',
            'content': [
                'Encriptación de datos',
                'Acceso restringido a la información',
                'Monitoreo regular de seguridad',
                'Actualizaciones de seguridad',
                'Almacenamiento seguro de documentos KYC',
                'Su imagen de referencia y las imágenes de sus verificaciones con su rostro se guardan cifradas en Suiza, con acceso restringido al equipo de seguridad y cumplimiento',
                'Verificación de identidad mediante proveedores certificados',
                'Controles antifraude, registros de sesión, monitoreo de dispositivos y verificaciones de integridad'
            ]
        },
        {
            'title': '5. Sus Derechos',
            'content': [
                'Acceder a su información',
                'Corregir datos inexactos',
                'Solicitar la eliminación de datos',
                'Oponerse al procesamiento',
                'Exportar sus datos',
                'Solicitar información sobre el uso de sus datos KYC y de seguridad',
                'Oponerse al uso de su rostro. Como la verificación con su rostro protege su dinero, sin ella no podremos habilitar las operaciones que la requieren'
            ]
        },
        {
            'title': '6. Retención de Datos',
            'content': [
                'Conservamos datos personales, transaccionales, de seguridad y de soporte durante el tiempo necesario para prestar el servicio, proteger la plataforma y cumplir con obligaciones legales o regulatorias',
                'Los datos KYC/AML y los registros vinculados a transacciones pueden conservarse por el tiempo requerido por la regulación aplicable, incluyendo al menos 5 años después de la última transacción cuando corresponda',
                'Podemos conservar registros antifraude, seguridad, auditoría y cumplimiento por el tiempo necesario para investigar incidentes, prevenir abuso y atender requerimientos legales',
                'Conservamos su imagen de referencia junto con sus datos KYC y por el mismo plazo. El resultado de cada verificación con su rostro se conserva como registro de seguridad y auditoría. Las imágenes de cada verificación, aprobada o rechazada, se eliminan a los 12 meses, porque los reportes de fraude y las consultas de socios y autoridades suelen llegar meses después de la operación. Si su cuenta tiene o ha tenido una sanción, o está vinculada a un caso o una alerta de fraude o cumplimiento que no haya sido descartado, incluidas las alertas automáticas de nuestros sistemas de seguridad y los requerimientos de un socio o de una autoridad, sus imágenes se conservan junto con sus datos KYC para investigar el caso. Confío no conserva el video',
                'Cuando verifica un documento, comparamos la selfie de esa verificación con la de su verificación anterior para confirmar que ambos documentos son de la misma persona. Si nuestro proveedor de verificación detecta que su rostro ya fue aprobado en otra cuenta, busca ese rostro entre las verificaciones aprobadas y, si corresponde a otra persona usuaria, revisamos el caso antes de permitir salidas de fondos. Si su cuenta es suspendida de forma permanente, pedimos a ese proveedor que bloquee su rostro para que no pueda verificar una cuenta nueva con otro documento, y retiramos ese bloqueo si la suspensión se levanta',
                'Conservamos cada verificación de ubicación de Bre-B (resultado, dirección IP y su país, coordenadas, precisión y hora de la lectura) como registro de cumplimiento y auditoría. No rastreamos su ubicación en segundo plano',
                'En Comprar, los datos de entrega de cada pedido (dirección, punto en el mapa, referencia y teléfono) se conservan con el pedido como registro de la transacción. Las direcciones de su libreta incluyen dirección, coordenadas cuando las indica, teléfono y referencia; al borrar una entrada, deja de aparecer y de estar disponible para seleccionarla, pero sus datos permanecen almacenados como una entrada marcada como eliminada, y borrarla no elimina ni modifica los datos de entrega conservados en pedidos anteriores. Conservamos cada lectura de ubicación con la que Comprar buscó su ciudad como registro, igual que las de Bre-B',
                'En Comunidad, lo que usted elimina y el contenido de una cuenta eliminada dejan de mostrarse y se eliminan, incluidos sus textos y fotos. El contenido que retiramos por moderación se conserva de forma privada hasta 90 días para atender reportes y apelaciones, y luego se eliminan sus textos y fotos; conservamos solo el registro de la decisión de moderación. Las fotos que sube y no llegan a publicarse se eliminan a los 7 días'
            ]
        },
        {
            'title': '7. Contacto',
            'content': {
                'email': 'privacy@confio.lat',
                'telegram': 'https://t.me/confio4world'
            }
        }
    ]
}

DELETION = {
    'title': 'Eliminación de Datos',
    'version': '1.2.1',
    'last_updated': '2026-10-06',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Proceso de Eliminación',
            'content': [
                'Enviar un email a privacy@confio.lat',
                'Incluir "Solicitud de Eliminación de Datos" en el asunto',
                'Proporcionar su dirección de correo electrónico registrada',
                'Confirmar su identidad',
                'Podemos solicitar información adicional para validar la titularidad de la cuenta y prevenir eliminaciones fraudulentas'
            ]
        },
        {
            'title': '2. Datos que se Eliminarán',
            'content': [
                'Cuando la ley y nuestras obligaciones regulatorias lo permitan, eliminaremos o anonimizaremos datos de perfil, preferencias, información de contacto y otros datos no esenciales para cumplimiento',
                'También podremos desactivar su acceso, cerrar la cuenta y eliminar o desvincular configuraciones operativas asociadas a la cuenta',
                'Sus publicaciones, comentarios, fotos y foto de perfil en Comunidad dejan de mostrarse y se eliminan, incluidos sus textos y fotos; también puede eliminarlos usted mismo en cualquier momento desde la app',
                'Cuando técnicamente o legalmente no sea posible una eliminación inmediata, restringiremos el uso de los datos y los conservaremos solo para fines permitidos'
            ]
        },
        {
            'title': '3. Datos que no se Eliminarán',
            'content': [
                'Registros de transacciones en la blockchain',
                'Información que debamos conservar por ley, regulación, requerimientos fiscales, contables, KYC, AML, auditoría o prevención de fraude',
                'Registros de seguridad, sesiones, eventos de integridad, señales antifraude y evidencia necesaria para investigar abuso o incidentes',
                'Registros operativos o contractuales necesarios para resolver disputas, cumplir obligaciones pendientes o defender derechos legales'
            ]
        },
        {
            'title': '4. Tiempo de Procesamiento',
            'content': [
                'Procesaremos su solicitud dentro de un plazo razonable y conforme a la ley aplicable',
                'En casos complejos o cuando existan obligaciones regulatorias, verificaciones adicionales o sistemas de terceros involucrados, el proceso puede tardar más',
                'Recibirá una confirmación por email cuando la solicitud haya sido atendida o cuando podamos informarle qué datos deben conservarse'
            ]
        },
        {
            'title': '5. Consecuencias',
            'content': [
                'No podrá acceder a sus datos eliminados',
                'Deberá crear una nueva cuenta para usar nuestros servicios',
                'Las transacciones en la blockchain son permanentes',
                'La eliminación de la cuenta no implica la eliminación automática de todos los registros regulatorios, antifraude o de seguridad que debamos conservar'
            ]
        },
        {
            'title': '6. Contacto',
            'content': {
                'email': 'privacy@confio.lat',
                'telegram': 'https://t.me/confio4world'
            }
        }
    ]
}
