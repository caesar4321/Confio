#!/bin/bash

# Simplified deployment script for Confio (Django + React)
set -e

# Configuration
EC2_IP="51.96.174.134"
EC2_USER="ec2-user"
KEY_PATH="~/.ssh/confio-key.pem"
PROJECT_DIR="/Users/julian/Confio"

echo "🚀 Starting simplified Confio deployment..."

# Expand the key path
KEY_PATH=$(eval echo $KEY_PATH)

# Build React app
echo "📦 Building React app..."
cd $PROJECT_DIR/web
npm run build

# Create minimal requirements without pysui
echo "📦 Creating minimal requirements..."
cat > /tmp/requirements-minimal.txt << 'EOF'
Django>=5.1,<5.3
gunicorn==20.1.0
whitenoise==6.9.0
django-redis==5.4.0
redis==6.2.0
channels==4.0.0
channels-redis==4.2.0
daphne==4.1.2
graphene-django==3.2.3
django-graphql-jwt==0.4.0
psycopg-binary==3.2.6
python-decouple==3.8
python-dotenv==1.0.0
firebase-admin==6.7.0
boto3==1.37.34
geopy==2.4.1
user_agents==2.2.0
django-leaflet==0.31.0
django-import-export==4.3.7
django-graphql-geojson==0.1.4
graphene-gis==0.0.8
celery==5.5.1
azure-cognitiveservices-vision-face==0.6.1
google-api-python-client==2.167.0
flask==2.0.1
EOF

# Deploy on server
echo "🔧 Deploying to EC2..."
ssh -o StrictHostKeyChecking=no -i $KEY_PATH $EC2_USER@$EC2_IP << 'ENDSSH'
    set -e
    
    echo "Setting up deployment..."
    
    # Stop any existing services
    sudo systemctl stop gunicorn 2>/dev/null || true
    sudo systemctl stop nginx 2>/dev/null || true
    
    # Clean previous deployment
    sudo rm -rf /opt/confio
    sudo mkdir -p /opt/confio
    
    echo "Deployment directory ready"
ENDSSH

# Upload files
echo "📤 Uploading application files..."
cd $PROJECT_DIR

# Create deployment package with only essential files
mkdir -p /tmp/confio-minimal
cp -r config users p2p_exchange presale blockchain contracts prover payments /tmp/confio-minimal/ 2>/dev/null || true
cp -r achievements auth conversion exchange_rates notifications security send telegram_verification usdc_transactions /tmp/confio-minimal/ 2>/dev/null || true
cp -r templates static /tmp/confio-minimal/ 2>/dev/null || true
cp -r web/build /tmp/confio-minimal/web/ 2>/dev/null || true
cp manage.py requirements.txt /tmp/confio-minimal/
cd /tmp/confio-minimal
tar -czf /tmp/confio-deploy.tar.gz .
cd -

scp -o StrictHostKeyChecking=no -i $KEY_PATH /tmp/confio-deploy.tar.gz $EC2_USER@$EC2_IP:/tmp/
scp -o StrictHostKeyChecking=no -i $KEY_PATH /tmp/requirements-minimal.txt $EC2_USER@$EC2_IP:/tmp/

# Complete setup on server
ssh -o StrictHostKeyChecking=no -i $KEY_PATH $EC2_USER@$EC2_IP << 'ENDSSH'
    set -e
    
    echo "Extracting application..."
    sudo tar -xzf /tmp/confio-deploy.tar.gz -C /opt/confio
    
    echo "Setting up Python environment..."
    cd /opt/confio
    
    # Use Python 3.10 (already installed)
    sudo python3.10 -m venv venv
    
    # Install dependencies
    echo "Installing Python packages..."
    sudo /opt/confio/venv/bin/pip install --upgrade pip
    sudo /opt/confio/venv/bin/pip install wheel
    sudo /opt/confio/venv/bin/pip install -r /tmp/requirements-minimal.txt
    
    # Create .env file
    echo "Creating environment configuration..."
    sudo tee /opt/confio/.env > /dev/null << 'EOF'
SECRET_KEY=django-insecure-change-this-in-production-$(openssl rand -hex 32)
DEBUG=False
ALLOWED_HOSTS=51.96.174.134,confio.lat,www.confio.lat,localhost
DATABASE_URL=sqlite:////opt/confio/db.sqlite3
STATIC_ROOT=/opt/confio/staticfiles
MEDIA_ROOT=/opt/confio/media
EOF
    
    # Create database
    echo "Setting up database..."
    sudo /opt/confio/venv/bin/python /opt/confio/manage.py migrate --run-syncdb
    
    # Collect static files
    echo "Collecting static files..."
    sudo /opt/confio/venv/bin/python /opt/confio/manage.py collectstatic --noinput
    
    # Set permissions
    sudo chown -R nginx:nginx /opt/confio
    sudo chmod -R 755 /opt/confio
    
    # Create Gunicorn service
    echo "Creating Gunicorn service..."
    sudo tee /etc/systemd/system/gunicorn.service > /dev/null << 'EOF'
[Unit]
Description=Gunicorn daemon for Confio
After=network.target

[Service]
User=nginx
Group=nginx
WorkingDirectory=/opt/confio
ExecStart=/opt/confio/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:8000 \
    config.wsgi:application

[Install]
WantedBy=multi-user.target
EOF
    
    # Configure nginx
    echo "Configuring nginx..."
    sudo tee /etc/nginx/conf.d/confio.conf > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;
    
    location /static/ {
        alias /opt/confio/web/build/static/;
        expires 30d;
    }
    
    location /media/ {
        alias /opt/confio/media/;
    }
    
    location /images/ {
        alias /opt/confio/web/build/images/;
        expires 30d;
    }
    
    location /graphql {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    
    location /admin {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF
    
    # Remove default nginx config
    sudo rm -f /etc/nginx/conf.d/default.conf
    
    # Start services
    echo "Starting services..."
    sudo systemctl daemon-reload
    sudo systemctl enable gunicorn
    sudo systemctl start gunicorn
    sudo systemctl enable nginx
    sudo systemctl restart nginx
    
    echo "✅ Deployment complete!"
ENDSSH

echo ""
echo "========================================="
echo "✅ Confio deployed successfully!"
echo "========================================="
echo "🌐 Website: http://$EC2_IP"
echo ""

# Cleanup
rm -f /tmp/confio-deploy.tar.gz
rm -f /tmp/requirements-minimal.txt