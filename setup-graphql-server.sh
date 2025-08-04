#!/bin/bash

# Setup GraphQL server on EC2
EC2_HOST="confio.lat"
SSH_KEY="/Users/julian/Confio/Sui custom prover.pem"

# Try different EC2 IPs since domain might be behind Cloudflare
EC2_IPS=("51.96.174.134" "3.79.239.174" "18.156.108.209")

echo "Setting up GraphQL server..."

# Find the correct EC2 IP
for IP in "${EC2_IPS[@]}"; do
    echo "Trying IP: $IP"
    if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no ec2-user@$IP "echo 'Connected'" 2>/dev/null; then
        EC2_IP=$IP
        echo "Connected to EC2 at $IP"
        break
    fi
done

if [ -z "$EC2_IP" ]; then
    echo "Could not connect to EC2. Please check:"
    echo "1. The EC2 instance is running"
    echo "2. The SSH key is correct"
    echo "3. The IP address is correct"
    echo "Attempting to get instance info from AWS..."
    
    # Try AWS CLI if available
    if command -v aws &> /dev/null; then
        aws ec2 describe-instances --filters "Name=tag:Name,Values=confio*" --query 'Reservations[*].Instances[*].[PublicIpAddress,State.Name,InstanceId]' --output text
    fi
    exit 1
fi

# Create GraphQL server script
cat << 'EOF' > /tmp/graphql_server.py
#!/usr/bin/env python3
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import traceback

class GraphQLHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            query = data.get('query', '')
            variables = data.get('variables', {})
            
            # Parse the query to extract the document type
            if 'legalDocument' in query:
                doc_type = variables.get('docType', 'terms')
                language = variables.get('language', 'es')
                
                documents = {
                    'terms': {
                        'es': {
                            'title': 'Términos y Condiciones',
                            'content': '''# Términos y Condiciones de Confío

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

**Última actualización: Agosto 2024**''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        },
                        'en': {
                            'title': 'Terms and Conditions',
                            'content': '''# Confío Terms and Conditions

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

**Last updated: August 2024**''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        }
                    },
                    'privacy': {
                        'es': {
                            'title': 'Política de Privacidad',
                            'content': '''# Política de Privacidad de Confío

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

**Última actualización: Agosto 2024**''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        },
                        'en': {
                            'title': 'Privacy Policy',
                            'content': '''# Confío Privacy Policy

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

**Last updated: August 2024**''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        }
                    },
                    'deletion': {
                        'es': {
                            'title': 'Política de Eliminación de Datos',
                            'content': '''# Política de Eliminación de Datos

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

**Para más información:** soporte@confio.lat''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        },
                        'en': {
                            'title': 'Data Deletion Policy',
                            'content': '''# Data Deletion Policy

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

**For more information:** support@confio.lat''',
                            'version': '1.0',
                            'lastUpdated': '2024-08-04'
                        }
                    }
                }
                
                # Get the document based on type and language
                doc_data = documents.get(doc_type, {}).get(language, documents.get(doc_type, {}).get('es', {}))
                
                if doc_data:
                    response = {
                        'data': {
                            'legalDocument': {
                                'title': doc_data['title'],
                                'content': doc_data['content'],
                                'version': doc_data['version'],
                                'lastUpdated': doc_data['lastUpdated'],
                                'language': language
                            }
                        }
                    }
                else:
                    response = {
                        'errors': [{
                            'message': f'Document type "{doc_type}" not found',
                            'extensions': {'code': 'DOCUMENT_NOT_FOUND'}
                        }]
                    }
            else:
                response = {
                    'errors': [{
                        'message': 'Query not supported',
                        'extensions': {'code': 'UNSUPPORTED_QUERY'}
                    }]
                }
            
            # Send response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            traceback.print_exc()
            error_response = {
                'errors': [{
                    'message': str(e),
                    'extensions': {'code': 'INTERNAL_SERVER_ERROR'}
                }]
            }
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(error_response).encode('utf-8'))

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        html = '''
        <html>
        <head><title>GraphQL Server</title></head>
        <body>
            <h1>GraphQL Server Running</h1>
            <p>Send POST requests to /graphql with your queries</p>
        </body>
        </html>
        '''
        self.wfile.write(html.encode('utf-8'))

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8001), GraphQLHandler)
    print('GraphQL server running on port 8001...')
    server.serve_forever()
EOF

# Copy GraphQL server to EC2
echo "Copying GraphQL server to EC2..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no /tmp/graphql_server.py ec2-user@$EC2_IP:/tmp/

# Setup and run GraphQL server on EC2
echo "Setting up GraphQL server on EC2..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@$EC2_IP << 'REMOTE_EOF'
# Stop any existing GraphQL server
sudo pkill -f "python.*graphql" || true
sudo pkill -f "python.*8001" || true

# Copy GraphQL server to /opt/confio
sudo cp /tmp/graphql_server.py /opt/confio/graphql_server.py
sudo chmod +x /opt/confio/graphql_server.py

# Create systemd service for GraphQL server
sudo tee /etc/systemd/system/confio-graphql.service > /dev/null << 'SERVICE_EOF'
[Unit]
Description=Confio GraphQL Server
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/confio
ExecStart=/usr/bin/python3 /opt/confio/graphql_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# Update nginx configuration to proxy GraphQL
sudo tee /etc/nginx/conf.d/confio.conf > /dev/null << 'NGINX_EOF'
server {
    listen 80;
    server_name confio.lat www.confio.lat;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name confio.lat www.confio.lat;

    ssl_certificate /etc/letsencrypt/live/confio.lat/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/confio.lat/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # GraphQL endpoint
    location /graphql {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
        
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
    }
    
    location /graphql/ {
        proxy_pass http://127.0.0.1:8001/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
        
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
    }

    # Main React app
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 10M;
}
NGINX_EOF

# Reload systemd and start services
sudo systemctl daemon-reload
sudo systemctl enable confio-graphql
sudo systemctl restart confio-graphql
sudo nginx -t && sudo systemctl reload nginx

# Check if services are running
sleep 2
echo "Checking services..."
sudo systemctl status confio-graphql --no-pager
echo ""
echo "Testing GraphQL endpoint..."
curl -s http://localhost:8001 | head -5
REMOTE_EOF

echo "GraphQL server setup complete!"
echo "Testing from local machine..."
curl -s https://confio.lat/graphql/ -X POST \
    -H "Content-Type: application/json" \
    -d '{"query": "{ legalDocument(docType: \"terms\") { title } }"}' | python3 -m json.tool