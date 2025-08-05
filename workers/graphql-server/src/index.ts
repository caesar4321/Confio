export interface Env {
  ENVIRONMENT: string;
}

interface LegalDocument {
  title: string;
  content: string;
  version: string;
  lastUpdated: string;
  language: string;
}

const documents: Record<string, Record<string, LegalDocument>> = {
  terms: {
    es: {
      title: 'Términos y Condiciones',
      content: `# Términos y Condiciones de Confío

## 1. Aceptación de los Términos

Al utilizar la aplicación Confío, usted acepta estos términos y condiciones en su totalidad. Si no está de acuerdo con estos términos, no debe utilizar nuestra aplicación.

## 2. Descripción del Servicio

Confío es una billetera digital que permite:
- Enviar y recibir dólares digitales (USDC)
- Convertir entre monedas locales y dólares digitales
- Realizar pagos P2P de forma segura

## 3. Registro y Cuenta

Para usar Confío, debe:
- Proporcionar información precisa y actualizada
- Mantener la seguridad de su cuenta
- Notificar inmediatamente cualquier uso no autorizado

## 4. Uso Aceptable

Usted se compromete a:
- No usar Confío para actividades ilegales
- No intentar hackear o dañar nuestros sistemas
- Cumplir con todas las leyes aplicables

## 5. Privacidad

Su privacidad es importante para nosotros. Consulte nuestra Política de Privacidad para entender cómo manejamos sus datos.

## 6. Limitación de Responsabilidad

Confío no será responsable por pérdidas indirectas o consecuenciales derivadas del uso de la aplicación.

## 7. Modificaciones

Nos reservamos el derecho de modificar estos términos en cualquier momento. Los cambios entrarán en vigor al publicarse en la aplicación.

## 8. Contacto

Para preguntas sobre estos términos, contáctenos en: soporte@confio.lat

**Última actualización: Agosto 2024**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'es'
    },
    en: {
      title: 'Terms and Conditions',
      content: `# Confío Terms and Conditions

## 1. Acceptance of Terms

By using the Confío application, you accept these terms and conditions in full. If you do not agree with these terms, you should not use our application.

## 2. Service Description

Confío is a digital wallet that allows:
- Send and receive digital dollars (USDC)
- Convert between local currencies and digital dollars
- Make P2P payments securely

## 3. Registration and Account

To use Confío, you must:
- Provide accurate and up-to-date information
- Maintain the security of your account
- Immediately notify any unauthorized use

## 4. Acceptable Use

You agree to:
- Not use Confío for illegal activities
- Not attempt to hack or damage our systems
- Comply with all applicable laws

## 5. Privacy

Your privacy is important to us. Please refer to our Privacy Policy to understand how we handle your data.

## 6. Limitation of Liability

Confío will not be liable for indirect or consequential losses arising from the use of the application.

## 7. Modifications

We reserve the right to modify these terms at any time. Changes will take effect upon publication in the application.

## 8. Contact

For questions about these terms, contact us at: support@confio.lat

**Last updated: August 2024**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'en'
    },
    ko: {
      title: '이용 약관',
      content: `# Confío 이용 약관

## 1. 약관 동의

Confío 애플리케이션을 사용함으로써 귀하는 이 약관에 전적으로 동의합니다. 이 약관에 동의하지 않으면 애플리케이션을 사용하지 마십시오.

## 2. 서비스 설명

Confío는 다음을 가능하게 하는 디지털 지갑입니다:
- 디지털 달러(USDC) 송수신
- 현지 통화와 디지털 달러 간 변환
- 안전한 P2P 결제

## 3. 등록 및 계정

Confío를 사용하려면:
- 정확하고 최신 정보를 제공해야 합니다
- 계정 보안을 유지해야 합니다
- 무단 사용을 즉시 알려야 합니다

## 4. 허용 가능한 사용

귀하는 다음에 동의합니다:
- 불법 활동에 Confío를 사용하지 않음
- 시스템을 해킹하거나 손상시키려 하지 않음
- 모든 해당 법률을 준수함

## 5. 개인정보 보호

귀하의 개인정보는 우리에게 중요합니다. 데이터 처리 방법을 이해하려면 개인정보 보호정책을 참조하십시오.

## 6. 책임 제한

Confío는 애플리케이션 사용으로 인한 간접적 또는 결과적 손실에 대해 책임지지 않습니다.

## 7. 수정

우리는 언제든지 이 약관을 수정할 권리를 보유합니다. 변경 사항은 애플리케이션에 게시되면 즉시 효력을 발생합니다.

## 8. 연락처

약관에 대한 질문은 다음으로 문의하십시오: support@confio.lat

**최종 업데이트: 2024년 8월**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'ko'
    }
  },
  privacy: {
    es: {
      title: 'Política de Privacidad',
      content: `# Política de Privacidad de Confío

## 1. Información que Recopilamos

Recopilamos información que usted nos proporciona directamente:
- Nombre y apellido
- Número de teléfono
- Dirección de correo electrónico
- Información de verificación de identidad

## 2. Cómo Usamos su Información

Utilizamos su información para:
- Proporcionar y mantener nuestros servicios
- Verificar su identidad
- Prevenir fraudes y actividades ilegales
- Comunicarnos con usted sobre su cuenta

## 3. Compartir Información

No vendemos ni alquilamos su información personal. Podemos compartir información con:
- Proveedores de servicios que nos ayudan a operar
- Autoridades legales cuando sea requerido por ley

## 4. Seguridad

Implementamos medidas de seguridad técnicas y organizativas para proteger su información.

## 5. Sus Derechos

Usted tiene derecho a:
- Acceder a su información personal
- Corregir información inexacta
- Solicitar la eliminación de su cuenta

## 6. Contacto

Para preguntas sobre privacidad: privacidad@confio.lat

**Última actualización: Agosto 2024**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'es'
    },
    en: {
      title: 'Privacy Policy',
      content: `# Confío Privacy Policy

## 1. Information We Collect

We collect information you provide directly:
- First and last name
- Phone number
- Email address
- Identity verification information

## 2. How We Use Your Information

We use your information to:
- Provide and maintain our services
- Verify your identity
- Prevent fraud and illegal activities
- Communicate with you about your account

## 3. Information Sharing

We do not sell or rent your personal information. We may share information with:
- Service providers who help us operate
- Legal authorities when required by law

## 4. Security

We implement technical and organizational security measures to protect your information.

## 5. Your Rights

You have the right to:
- Access your personal information
- Correct inaccurate information
- Request deletion of your account

## 6. Contact

For privacy questions: privacy@confio.lat

**Last updated: August 2024**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'en'
    },
    ko: {
      title: '개인정보 보호정책',
      content: `# Confío 개인정보 보호정책

## 1. 수집하는 정보

직접 제공하는 정보를 수집합니다:
- 이름과 성
- 전화번호
- 이메일 주소
- 신원 확인 정보

## 2. 정보 사용 방법

다음을 위해 정보를 사용합니다:
- 서비스 제공 및 유지
- 신원 확인
- 사기 및 불법 활동 방지
- 계정에 대한 연락

## 3. 정보 공유

개인정보를 판매하거나 임대하지 않습니다. 다음과 정보를 공유할 수 있습니다:
- 운영을 돕는 서비스 제공자
- 법적 요구 시 법적 당국

## 4. 보안

정보 보호를 위한 기술적, 조직적 보안 조치를 구현합니다.

## 5. 귀하의 권리

귀하는 다음 권리가 있습니다:
- 개인정보 접근
- 부정확한 정보 수정
- 계정 삭제 요청

## 6. 연락처

개인정보 보호 관련 질문: privacy@confio.lat

**최종 업데이트: 2024년 8월**`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'ko'
    }
  },
  deletion: {
    es: {
      title: 'Política de Eliminación de Datos',
      content: `# Política de Eliminación de Datos

## Cómo Solicitar la Eliminación de su Cuenta

Para solicitar la eliminación de su cuenta y datos personales:

1. **Envíe un correo a:** eliminar@confio.lat
2. **Incluya:** Su número de teléfono registrado
3. **Tiempo de procesamiento:** 30 días hábiles

## Qué Información se Elimina

- Información personal identificable
- Historial de transacciones personales
- Preferencias y configuraciones de cuenta

## Qué Información se Retiene

Por requisitos legales, retenemos:
- Registros de transacciones anonimizados
- Información necesaria para cumplimiento regulatorio

## Consecuencias de la Eliminación

- No podrá acceder a su cuenta
- No podrá recuperar su historial de transacciones
- La eliminación es permanente e irreversible

**Para más información:** soporte@confio.lat`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'es'
    },
    en: {
      title: 'Data Deletion Policy',
      content: `# Data Deletion Policy

## How to Request Account Deletion

To request deletion of your account and personal data:

1. **Send an email to:** delete@confio.lat
2. **Include:** Your registered phone number
3. **Processing time:** 30 business days

## What Information is Deleted

- Personally identifiable information
- Personal transaction history
- Account preferences and settings

## What Information is Retained

For legal requirements, we retain:
- Anonymized transaction records
- Information necessary for regulatory compliance

## Consequences of Deletion

- You will not be able to access your account
- You will not be able to recover your transaction history
- Deletion is permanent and irreversible

**For more information:** support@confio.lat`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'en'
    },
    ko: {
      title: '데이터 삭제 정책',
      content: `# 데이터 삭제 정책

## 계정 삭제 요청 방법

계정 및 개인 데이터 삭제를 요청하려면:

1. **이메일 보내기:** delete@confio.lat
2. **포함 사항:** 등록된 전화번호
3. **처리 시간:** 영업일 기준 30일

## 삭제되는 정보

- 개인 식별 정보
- 개인 거래 내역
- 계정 환경설정 및 설정

## 보관되는 정보

법적 요구사항으로 보관:
- 익명화된 거래 기록
- 규제 준수에 필요한 정보

## 삭제의 결과

- 계정에 접근할 수 없습니다
- 거래 내역을 복구할 수 없습니다
- 삭제는 영구적이며 되돌릴 수 없습니다

**자세한 정보:** support@confio.lat`,
      version: '1.0',
      lastUpdated: '2024-08-04',
      language: 'ko'
    }
  }
};

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
          'Access-Control-Max-Age': '86400',
        }
      });
    }

    // Handle GraphQL endpoint
    if (url.pathname === '/graphql' || url.pathname === '/graphql/') {
      if (request.method === 'GET') {
        return new Response(JSON.stringify({ 
          message: 'GraphQL endpoint is running. Send POST requests with your queries.' 
        }), {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          }
        });
      }

      if (request.method === 'POST') {
        try {
          const body = await request.json() as any;
          const { query, variables = {} } = body;

          // Parse the query to handle legalDocument requests
          if (query.includes('legalDocument')) {
            const docType = variables.docType || 'terms';
            const language = variables.language || 'es';

            const docData = documents[docType]?.[language] || documents[docType]?.['es'];

            if (docData) {
              return new Response(JSON.stringify({
                data: {
                  legalDocument: docData
                }
              }), {
                headers: {
                  'Content-Type': 'application/json',
                  'Access-Control-Allow-Origin': '*',
                  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
                }
              });
            } else {
              return new Response(JSON.stringify({
                errors: [{
                  message: `Document type "${docType}" not found`,
                  extensions: { code: 'DOCUMENT_NOT_FOUND' }
                }]
              }), {
                status: 404,
                headers: {
                  'Content-Type': 'application/json',
                  'Access-Control-Allow-Origin': '*',
                }
              });
            }
          }

          return new Response(JSON.stringify({
            errors: [{
              message: 'Query not supported',
              extensions: { code: 'UNSUPPORTED_QUERY' }
            }]
          }), {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
            }
          });

        } catch (error) {
          return new Response(JSON.stringify({
            errors: [{
              message: 'Invalid request body',
              extensions: { code: 'INVALID_REQUEST' }
            }]
          }), {
            status: 400,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
            }
          });
        }
      }
    }

    // Pass through other requests
    return new Response('Not Found', { status: 404 });
  },
};