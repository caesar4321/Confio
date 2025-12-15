"""
Legal documents content in Spanish. These are the legally binding versions of our legal documents.
Each document is a dictionary with sections, where each section has a title and content.
"""

TERMS = {
    'title': 'Términos de Servicio',
    'version': '1.1.0',
    'last_updated': '2025-12-11',
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
                {'term': 'Monedas', 'definition': 'Incluye cUSD, CONFIO y cualquier otra moneda soportada.'}
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
            'title': '5. Limitaciones de Responsabilidad',
            'content': [
                'Pérdidas debido a errores del usuario',
                'Problemas de conectividad',
                'Fluctuaciones en el valor de las monedas',
                'Acciones de terceros'
            ]
        },
        {
            'title': '6. Restricciones Geográficas',
            'content': [
                'La participación en la preventa de monedas y ciertos servicios financieros de Confío está estrictamente prohibida para:',
                'Residentes o ciudadanos de los Estados Unidos de América (US)',
                'Residentes o ciudadanos de Corea del Sur (KR)'
            ]
        },
        {
            'title': '7. Modificaciones',
            'content': 'Nos reservamos el derecho de modificar estos términos en cualquier momento. Los cambios entrarán en vigor al publicarlos en nuestro sitio web.'
        },
        {
            'title': '8. Contacto',
            'content': {
                'email': 'legal@confio.lat',
                'telegram': 'https://t.me/confio4world'
            }
        }
    ]
}

PRIVACY = {
    'title': 'Política de Privacidad',
    'version': '1.2.0',
    'last_updated': '2025-12-14',
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
                    'Información de transacciones'
                ],
                'kyc_info': [
                    'Fecha de nacimiento',
                    'Número de identificación (cédula, DNI, pasaporte)',
                    'Fotografía de documento de identidad',
                    'Documento de identidad escaneado o fotografiado',
                    'Selfie con documento de identidad',
                    'Información de dirección residencial',
                    'Información de fuente de fondos'
                ],
                'device_info': [
                    'Sistema operativo',
                    'Versiones de software y hardware',
                    'Dirección IP',
                    'Ubicación',
                    'ID del dispositivo',
                    'ID de Publicidad (Advertising ID)',
                    'Configuración de notificaciones',
                    'Última hora activa y registros de actividad'
                ]
            }
        },
        {
            'title': '2. Uso de la Información',
            'content': [
                'Proporcionar y mantener nuestros servicios',
                'Procesar transacciones',
                'Enviar actualizaciones importantes',
                'Mejorar nuestros servicios',
                'Análisis estadístico para mejorar la experiencia del usuario',
                'Cumplir con obligaciones legales y regulatorias',
                'Verificar su identidad y prevenir fraudes',
                'Cumplir con requisitos de KYC/AML'
            ]
        },
        {
            'title': '3. Compartir Información',
            'content': [
                'Cuando es requerido por ley',
                'Para proteger nuestros derechos',
                'Con su consentimiento explícito',
                'Con proveedores de servicios de verificación KYC',
                'Con proveedores de servicios de análisis (como Firebase Analytics de Google) para entender el uso de la aplicación y mejorar nuestros servicios',
                'Con autoridades regulatorias cuando sea necesario'
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
                'Verificación de identidad mediante proveedores certificados'
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
                'Solicitar información sobre el uso de sus datos KYC'
            ]
        },
        {
            'title': '6. Retención de Datos KYC',
            'content': [
                'El tiempo requerido por las regulaciones aplicables',
                'Un mínimo de 5 años después de la última transacción',
                'El tiempo necesario para cumplir con obligaciones legales'
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
    'version': '1.0.0',
    'last_updated': '2025-05-02',
    'is_legally_binding': True,
    'sections': [
        {
            'title': '1. Proceso de Eliminación',
            'content': [
                'Enviar un email a privacy@confio.lat',
                'Incluir "Solicitud de Eliminación de Datos" en el asunto',
                'Proporcionar su dirección de correo electrónico registrada',
                'Confirmar su identidad'
            ]
        },
        {
            'title': '2. Datos que se Eliminarán',
            'content': [
                'Información de la cuenta',
                'Historial de transacciones',
                'Preferencias de usuario',
                'Datos de contacto'
            ]
        },
        {
            'title': '3. Datos que no se Eliminarán',
            'content': [
                'Registros de transacciones en la blockchain',
                'Información requerida por ley',
                'Datos necesarios para prevenir fraudes'
            ]
        },
        {
            'title': '4. Tiempo de Procesamiento',
            'content': [
                'Procesaremos su solicitud dentro de los 30 días hábiles',
                'Recibirá una confirmación por email cuando se complete'
            ]
        },
        {
            'title': '5. Consecuencias',
            'content': [
                'No podrá acceder a sus datos eliminados',
                'Deberá crear una nueva cuenta para usar nuestros servicios',
                'Las transacciones en la blockchain son permanentes'
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
