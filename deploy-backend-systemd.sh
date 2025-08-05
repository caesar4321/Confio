#!/bin/bash

# Deploy Confio backend with systemd services
set -e

# Configuration
EC2_IP="51.96.174.134"
EC2_USER="ec2-user"
KEY_PATH="~/.ssh/confio-key.pem"
PROJECT_DIR="/Users/julian/Confio"
REMOTE_DIR="/opt/confio"

echo "🚀 Starting Confio backend deployment with systemd..."

# Create deployment package
echo "📦 Creating deployment package..."
cd $PROJECT_DIR

# Exclude unnecessary files
tar -czf /tmp/confio-backend.tar.gz \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='myvenv*' \
    --exclude='node_modules' \
    --exclude='.git' \
    --exclude='apps/node_modules' \
    --exclude='web/node_modules' \
    --exclude='prover-service/node_modules' \
    --exclude='*.env' \
    --exclude='db.sqlite3' \
    .

echo "📤 Uploading to EC2..."
scp -i $KEY_PATH /tmp/confio-backend.tar.gz $EC2_USER@$EC2_IP:/tmp/

# Upload systemd service files
echo "📤 Uploading systemd service files..."
scp -i $KEY_PATH -r systemd/* $EC2_USER@$EC2_IP:/tmp/

# Deploy on server
echo "🔧 Setting up backend services..."
ssh -i $KEY_PATH $EC2_USER@$EC2_IP << 'ENDSSH'
    set -e
    
    echo "Installing system dependencies..."
    sudo yum update -y
    sudo yum groupinstall -y "Development Tools"
    sudo yum install -y python3.11 python3.11-devel postgresql15 postgresql15-devel redis6 nginx git
    
    # Create application user
    if ! id -u confio > /dev/null 2>&1; then
        echo "Creating confio user..."
        sudo useradd -r -s /bin/bash -d /opt/confio confio
    fi
    
    # Create directory structure
    echo "Creating directory structure..."
    sudo mkdir -p /opt/confio
    sudo mkdir -p /var/log/confio
    sudo mkdir -p /var/run/celery
    sudo mkdir -p /run/confio
    
    # Extract application
    echo "Extracting application..."
    sudo tar -xzf /tmp/confio-backend.tar.gz -C /opt/confio
    
    # Set up Python virtual environment
    echo "Setting up Python virtual environment..."
    sudo -u confio python3.11 -m venv /opt/confio/venv
    
    # Install Python dependencies
    echo "Installing Python dependencies..."
    sudo -u confio /opt/confio/venv/bin/pip install --upgrade pip
    sudo -u confio /opt/confio/venv/bin/pip install -r /opt/confio/requirements.txt
    sudo -u confio /opt/confio/venv/bin/pip install gunicorn daphne
    
    # Set permissions
    echo "Setting permissions..."
    sudo chown -R confio:confio /opt/confio
    sudo chown -R confio:confio /var/log/confio
    sudo chown -R confio:confio /var/run/celery
    sudo chown -R confio:confio /run/confio
    
    # Create environment file
    echo "Creating environment configuration..."
    sudo tee /opt/confio/.env > /dev/null << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings
DATABASE_URL=postgresql://confio:password@localhost/confio_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=False
ALLOWED_HOSTS=confio.app,www.confio.app,51.96.174.134
EOF
    
    sudo chown confio:confio /opt/confio/.env
    sudo chmod 600 /opt/confio/.env
    
    # Set up PostgreSQL
    echo "Setting up PostgreSQL..."
    sudo systemctl enable postgresql-15
    sudo systemctl start postgresql-15
    
    sudo -u postgres psql << EOF
CREATE USER confio WITH PASSWORD 'password';
CREATE DATABASE confio_db OWNER confio;
GRANT ALL PRIVILEGES ON DATABASE confio_db TO confio;
EOF
    
    # Set up Redis
    echo "Setting up Redis..."
    sudo systemctl enable redis6
    sudo systemctl start redis6
    
    # Run Django migrations
    echo "Running Django migrations..."
    sudo -u confio /opt/confio/venv/bin/python /opt/confio/manage.py migrate
    sudo -u confio /opt/confio/venv/bin/python /opt/confio/manage.py collectstatic --noinput
    
    # Install systemd services
    echo "Installing systemd services..."
    sudo cp /tmp/confio-django.service /etc/systemd/system/
    sudo cp /tmp/confio-daphne.service /etc/systemd/system/
    sudo cp /tmp/confio-celery-worker.service /etc/systemd/system/
    sudo cp /tmp/confio-celery-beat.service /etc/systemd/system/
    sudo cp /tmp/confio.target /etc/systemd/system/
    
    # Reload systemd and start services
    echo "Starting services..."
    sudo systemctl daemon-reload
    sudo systemctl enable confio.target
    sudo systemctl start confio.target
    
    # Configure nginx for backend
    sudo tee /etc/nginx/conf.d/confio-backend.conf > /dev/null << 'EOF'
upstream django {
    server unix:/run/confio/gunicorn.sock;
}

upstream daphne {
    server 127.0.0.1:8001;
}

server {
    listen 8000;
    server_name _;
    
    location /static/ {
        alias /opt/confio/staticfiles/;
    }
    
    location /media/ {
        alias /opt/confio/media/;
    }
    
    location /ws/ {
        proxy_pass http://daphne;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    
    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    
    sudo systemctl restart nginx
    
    # Check service status
    echo "Checking service status..."
    sudo systemctl status confio.target --no-pager
    
    echo "✅ Backend deployment complete!"
ENDSSH

echo ""
echo "========================================="
echo "✅ Confio backend deployed with systemd!"
echo "========================================="
echo ""
echo "Service Management Commands:"
echo "  Start all:    sudo systemctl start confio.target"
echo "  Stop all:     sudo systemctl stop confio.target"
echo "  Restart all:  sudo systemctl restart confio.target"
echo "  Status:       sudo systemctl status confio.target"
echo ""
echo "Individual Services:"
echo "  Django:       sudo systemctl status confio-django"
echo "  Daphne:       sudo systemctl status confio-daphne"
echo "  Celery:       sudo systemctl status confio-celery-worker"
echo "  Beat:         sudo systemctl status confio-celery-beat"
echo ""
echo "Logs:"
echo "  sudo journalctl -u confio-django -f"
echo "  sudo journalctl -u confio-daphne -f"
echo "  sudo journalctl -u confio-celery-worker -f"
echo ""

# Cleanup
rm -f /tmp/confio-backend.tar.gz