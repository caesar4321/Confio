"""
Legal documents content in Spanish. These are the legally binding versions of our legal documents.
Each document is a dictionary with sections, where each section has a title and content.
"""

TERMS = {
    'title': 'Términos de Servicio',
    'version': '1.3.0',
    'last_updated': '2026-07-04',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Introducción',
            'content': 'Bienvenido a Confío, la billetera abierta para la economía del dólar en América Latina. Al utilizar nuestros servicios, usted acepta estos términos. Por favor, léalos cuidadosamente.'
        },
        {
            'title': '2. Definiciones',
            'content': [
                {'term': 'Confío', 'definition': 'La plataforma y servicios proporcionados por Confío.'},
                {'term': 'Usuario', 'definition': 'Cualquier persona que utilice nuestros servicios.'},
                {'term': 'Servicios', 'definition': 'Incluye la billetera, transferencias y cualquier otra funcionalidad ofrecida por Confío.'},
                {'term': 'Monedas', 'definition': 'Incluye cUSD, CONFIO y cualquier otra moneda soportada.'},
                {'term': 'cUSD+', 'definition': 'Token que representa cUSD depositado en la función de ahorro con rendimiento, respaldado 1:1 por USDY de Ondo Finance.'},
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
                'Procesadas a través de la blockchain Algorand'
            ]
        },
        {
            'title': '5. Preventa y Token $CONFIO',
            'content': [
                'La preventa de $CONFIO da acceso a un token del ecosistema Confío y no representa acciones, participación societaria, dividendos ni derecho a utilidades, ingresos o activos de Confío.',
                'La compra de $CONFIO no constituye una cuenta de ahorro, depósito bancario, contrato de inversión, asesoría financiera ni oferta pública de valores.',
                'El valor, liquidez, disponibilidad y utilidad futura de $CONFIO pueden cambiar o no materializarse. No garantizamos apreciación, mercado secundario, listados ni recompra.',
                'Cualquier funcionalidad, beneficio o acceso futuro asociado a $CONFIO depende del desarrollo del producto, requisitos técnicos, cumplimiento normativo y decisiones operativas de Confío.',
                'Al participar en la preventa, usted declara que compra por su propio criterio y que entiende que puede perder la totalidad del valor entregado.'
            ]
        },
        {
            'title': '6. Ahorro con Rendimiento (cUSD+)',
            'content': [
                'Al usar la función de ahorro, su cUSD se convierte en cUSD+, un token respaldado 1:1 por USDY de Ondo Finance, un activo garantizado por bonos del Tesoro de los Estados Unidos y emitido por terceros.',
                'El rendimiento es variable, se genera a través de USDY y puede cambiar día a día. No es una tasa fija, no está garantizado y puede diferir del mostrado en la app.',
                'cUSD+ no es una cuenta de ahorro bancaria ni un depósito. No está protegido por seguros de depósito (como FDIC) ni por fondos de garantía estatales.',
                'La conversión entre cUSD y cUSD+ depende de contratos inteligentes y de emisores o proveedores terceros; en condiciones excepcionales de mercado o técnicas, los retiros podrían demorarse o verse afectados.',
                'Existen riesgos técnicos y de terceros, incluyendo errores en contratos inteligentes, cambios regulatorios y riesgo del emisor del activo de respaldo. En casos extremos puede perder parte o la totalidad del valor depositado.',
                'Las tasas mostradas ya descuentan la comisión de Confío; cualquier costo adicional de una operación se muestra antes de confirmarla.'
            ]
        },
        {
            'title': '7. Acciones de EE.UU. (Acciones Tokenizadas)',
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
            'title': '8. Limitaciones de Responsabilidad',
            'content': [
                'Pérdidas debido a errores del usuario',
                'Problemas de conectividad',
                'Fluctuaciones en el valor de las monedas',
                'Variaciones de rendimiento o de precio en cUSD+, USDY o acciones tokenizadas',
                'Actos u omisiones de emisores o proveedores terceros de los activos subyacentes',
                'Acciones de terceros'
            ]
        },
        {
            'title': '9. Restricciones Geográficas',
            'content': [
                'La participación en la preventa de monedas y ciertos servicios financieros de Confío está estrictamente prohibida para:',
                'Residentes o ciudadanos de los Estados Unidos de América (US)',
                'Residentes o ciudadanos de Corea del Sur (KR)',
                'Estas restricciones aplican también al ahorro con rendimiento (cUSD+) y a las acciones tokenizadas, cuya disponibilidad puede variar según su jurisdicción.'
            ]
        },
        {
            'title': '10. Cumplimiento del Usuario',
            'content': [
                'Usted es responsable de verificar que el uso de Confío, la compra de $CONFIO y el uso de las funciones de ahorro e inversión estén permitidos en su jurisdicción.',
                'Podemos rechazar, limitar o cancelar acceso a servicios, a la preventa o a las funciones de ahorro e inversión si detectamos restricciones regulatorias, sanciones, fraude, suplantación o incumplimiento de estos términos.',
                'Podemos solicitar verificaciones adicionales de identidad, origen de fondos o residencia antes o después de permitir el uso de ciertas funciones.'
            ]
        },
        {
            'title': '11. Modificaciones',
            'content': 'Nos reservamos el derecho de modificar estos términos en cualquier momento. Los cambios entrarán en vigor al publicarlos en nuestro sitio web.'
        },
        {
            'title': '12. Contacto',
            'content': {
                'email': 'legal@confio.lat',
                'telegram': 'https://t.me/confio4world'
            }
        }
    ]
}

PRIVACY = {
    'title': 'Política de Privacidad',
    'version': '1.3.0',
    'last_updated': '2026-03-19',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Información que Recopilamos',
            'content': {
                'personal_info': [
                    'Nombre completo',
                    'Dirección de correo electrónico',
                    'Número de teléfono',
                    'Direcciones de billetera',
                    'Información de transacciones',
                    'Información de cuenta y perfil, incluyendo identificadores internos, país de teléfono y nombre de usuario'
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
                'device_info': [
                    'Sistema operativo',
                    'Versiones de software y hardware',
                    'Dirección IP',
                    'Ubicación',
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
                    'Reacciones, suscripciones a canales y otra interacción con contenido publicado en la plataforma'
                ],
                'business_and_payroll': [
                    'Datos de negocios, roles de empleados, permisos, notas internas y configuraciones operativas',
                    'Destinatarios de nómina, corridas de nómina, montos, comisiones, estado de pagos y metadatos asociados'
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
                'Cumplir con requisitos de KYC/AML',
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
                'Con proveedores de recargas, retiros, pagos, transferencias y conversión de activos cuando sea necesario para ejecutar una operación solicitada por usted',
                'Con proveedores de infraestructura, almacenamiento, autenticación, notificaciones push y seguridad que actúan como encargados del tratamiento',
                'Con autoridades regulatorias, judiciales o administrativas cuando sea necesario'
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
                'Solicitar información sobre el uso de sus datos KYC y de seguridad'
            ]
        },
        {
            'title': '6. Retención de Datos',
            'content': [
                'Conservamos datos personales, transaccionales, de seguridad y de soporte durante el tiempo necesario para prestar el servicio, proteger la plataforma y cumplir con obligaciones legales o regulatorias',
                'Los datos KYC/AML y los registros vinculados a transacciones pueden conservarse por el tiempo requerido por la regulación aplicable, incluyendo al menos 5 años después de la última transacción cuando corresponda',
                'Podemos conservar registros antifraude, seguridad, auditoría y cumplimiento por el tiempo necesario para investigar incidentes, prevenir abuso y atender requerimientos legales'
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
    'version': '1.1.0',
    'last_updated': '2026-03-19',
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
