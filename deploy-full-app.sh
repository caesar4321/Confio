#!/bin/bash

# Full deployment script for Confio app (Django + React)
set -e

# Configuration
EC2_IP="51.96.174.134"
EC2_USER="ec2-user"
KEY_PATH="~/.ssh/confio-key.pem"
PROJECT_DIR="/Users/julian/Confio"
REMOTE_DIR="/opt/confio"

echo "🚀 Starting full Confio deployment to EC2..."

# Expand the key path
KEY_PATH=$(eval echo $KEY_PATH)

# Check if key exists
if [ ! -f "$KEY_PATH" ]; then
    echo "❌ SSH key not found at $KEY_PATH"
    echo "Please ensure you have the confio-key.pem file in your ~/.ssh/ directory"
    exit 1
fi

# Build React app
echo "📦 Building React app with FriendlyApp..."
cd $PROJECT_DIR/web
npm run build
if [ $? -ne 0 ]; then
    echo "❌ React build failed. Please fix errors and try again."
    exit 1
fi

# Create deployment package
echo "📦 Creating deployment package..."
cd $PROJECT_DIR

# Create a temporary directory for the deployment
TEMP_DIR=$(mktemp -d)
echo "Using temp directory: $TEMP_DIR"

# Copy necessary files
echo "Copying project files..."
# Copy only existing directories (all Django apps)
for dir in config users p2p_exchange presale blockchain contracts prover payments achievements auth conversion exchange_rates notifications security send telegram_verification usdc_transactions; do
    if [ -d "$dir" ]; then
        cp -r "$dir" $TEMP_DIR/
    fi
done

# Copy templates, static and build
if [ -d "templates" ]; then cp -r templates $TEMP_DIR/; fi
if [ -d "static" ]; then cp -r static $TEMP_DIR/; fi
if [ -d "web/build" ]; then 
    mkdir -p $TEMP_DIR/web
    cp -r web/build $TEMP_DIR/web/
fi

# Include .well-known for Universal Links / App Links
if [ -d "web/.well-known" ]; then
    mkdir -p $TEMP_DIR/web
    cp -r web/.well-known $TEMP_DIR/web/
fi

# Copy essential files
cp manage.py requirements.txt $TEMP_DIR/
if [ -f "db.sqlite3" ]; then cp db.sqlite3 $TEMP_DIR/; fi

# Create the tarball
cd $TEMP_DIR
tar -czf /tmp/confio-full.tar.gz .
cd -

# Clean up temp directory
rm -rf $TEMP_DIR

echo "📤 Uploading to EC2..."
scp -o StrictHostKeyChecking=no -i $KEY_PATH /tmp/confio-full.tar.gz $EC2_USER@$EC2_IP:/tmp/

# Create nginx configuration
cat > /tmp/nginx-confio-full.conf << 'EOF'
# Nginx configuration for Confio full app

upstream django {
    server unix:/run/gunicorn/socket;
}

server {
    listen 80;
    server_name confio.lat www.confio.lat;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;

    # Well-known endpoints for iOS/Android app linking
    # Serve both extensionless AASA and assetlinks.json with correct content-type
    location = /.well-known/apple-app-site-association {
        alias /opt/confio/web/.well-known/apple-app-site-association;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*" always;
        try_files $uri =404;
    }
    location = /apple-app-site-association {
        alias /opt/confio/web/.well-known/apple-app-site-association;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*" always;
        try_files $uri =404;
    }
    location = /.well-known/assetlinks.json {
        alias /opt/confio/web/.well-known/assetlinks.json;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*" always;
        try_files $uri =404;
    }
    # Fallback for any other .well-known files (if added later)
    location ^~ /.well-known/ {
        alias /opt/confio/web/.well-known/;
        default_type application/json;
        add_header Access-Control-Allow-Origin "*" always;
        try_files $uri =404;
    }
    
    # Static files from React build
    location /static/ {
        alias /opt/confio/web/build/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # Media files
    location /media/ {
        alias /opt/confio/media/;
        expires 30d;
    }
    
    # Images from React build
    location /images/ {
        alias /opt/confio/web/build/images/;
        expires 30d;
    }
    
    # API endpoints
    location /graphql {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /admin {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    location /prover {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # React app - all other routes
    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

scp -o StrictHostKeyChecking=no -i $KEY_PATH /tmp/nginx-confio-full.conf $EC2_USER@$EC2_IP:/tmp/

# Deploy on server
echo "🔧 Setting up on EC2..."
ssh -o StrictHostKeyChecking=no -i $KEY_PATH $EC2_USER@$EC2_IP << 'ENDSSH'
    set -e
    
    echo "Installing system dependencies..."
    sudo yum update -y
    sudo yum groupinstall -y "Development Tools"
    sudo yum install -y wget nginx git postgresql15-devel openssl-devel bzip2-devel libffi-devel zlib-devel
    
    # Install Python 3.10 from source if not already installed
    if ! command -v python3.10 &> /dev/null; then
        echo "Installing Python 3.10 from source..."
        cd /tmp
        wget https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz
        tar -xzf Python-3.10.14.tgz
        cd Python-3.10.14
        ./configure --enable-optimizations
        sudo make altinstall
        cd /
        sudo rm -rf /tmp/Python-3.10.14*
    else
        echo "Python 3.10 is already installed"
    fi
    
    # Create application directory
    echo "Creating application directory..."
    sudo mkdir -p /opt/confio
    sudo mkdir -p /var/log/confio
    sudo mkdir -p /run/gunicorn
    
    # Extract application
    echo "Extracting application..."
    sudo tar -xzf /tmp/confio-full.tar.gz -C /opt/confio
    
    # Set initial permissions
    sudo chown -R ec2-user:ec2-user /opt/confio
    
    # Set up Python virtual environment
    echo "Setting up Python virtual environment..."
    cd /opt/confio
    python3.10 -m venv venv
    
    # Install Python dependencies
    echo "Installing Python dependencies..."
    /opt/confio/venv/bin/pip install --upgrade pip
    /opt/confio/venv/bin/pip install wheel
    /opt/confio/venv/bin/pip install gunicorn
    /opt/confio/venv/bin/pip install -r /opt/confio/requirements.txt
    
    # Create .env file
    echo "Creating environment configuration..."
    sudo tee /opt/confio/.env > /dev/null << 'EOF'
SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=False
ALLOWED_HOSTS=confio.lat,www.confio.lat,51.96.174.134,localhost
DATABASE_URL=sqlite:////opt/confio/db.sqlite3
STATIC_ROOT=/opt/confio/staticfiles
MEDIA_ROOT=/opt/confio/media
EOF
    
    # Collect static files
    echo "Collecting static files..."
    sudo /opt/confio/venv/bin/python /opt/confio/manage.py collectstatic --noinput
    
    # Run migrations
    echo "Running migrations..."
    sudo /opt/confio/venv/bin/python /opt/confio/manage.py migrate
    
    # Set permissions
    sudo chown -R nginx:nginx /opt/confio
    sudo chmod -R 755 /opt/confio
    
    # Create Gunicorn systemd service
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
    --bind unix:/run/gunicorn/socket \
    --error-logfile /var/log/confio/gunicorn-error.log \
    --access-logfile /var/log/confio/gunicorn-access.log \
    config.wsgi:application

[Install]
WantedBy=multi-user.target
EOF
    
    # Create Gunicorn socket
    sudo tee /etc/systemd/system/gunicorn.socket > /dev/null << 'EOF'
[Unit]
Description=Gunicorn socket for Confio

[Socket]
ListenStream=/run/gunicorn/socket

[Install]
WantedBy=sockets.target
EOF
    
    # Configure nginx
    echo "Configuring nginx..."
    sudo cp /tmp/nginx-confio-full.conf /etc/nginx/conf.d/confio.conf
    sudo rm -f /etc/nginx/conf.d/default.conf
    
    # Test nginx configuration
    sudo nginx -t
    
    # Set socket permissions
    sudo chown nginx:nginx /run/gunicorn
    
    # Start services
    echo "Starting services..."
    sudo systemctl daemon-reload
    sudo systemctl enable gunicorn.socket
    sudo systemctl enable gunicorn.service
    sudo systemctl enable nginx
    
    sudo systemctl start gunicorn.socket
    sudo systemctl start gunicorn.service
    sudo systemctl restart nginx
    
    # Check status
    echo "Checking service status..."
    sudo systemctl status gunicorn --no-pager
    sudo systemctl status nginx --no-pager
    
    echo "✅ Deployment complete!"
ENDSSH

echo ""
echo "========================================="
echo "✅ Confio app deployed successfully!"
echo "========================================="
echo "🌐 Website URL: http://$EC2_IP"
echo "🌐 Website URL: http://confio.lat (once DNS is configured)"
echo ""
echo "Service Management:"
echo "  Restart Django: ssh -i $KEY_PATH $EC2_USER@$EC2_IP 'sudo systemctl restart gunicorn'"
echo "  Restart Nginx:  ssh -i $KEY_PATH $EC2_USER@$EC2_IP 'sudo systemctl restart nginx'"
echo "  View logs:      ssh -i $KEY_PATH $EC2_USER@$EC2_IP 'sudo journalctl -u gunicorn -f'"
echo ""
echo "Next steps:"
echo "1. Update your .env file on the server with proper SECRET_KEY"
echo "2. Configure SSL with Let's Encrypt"
echo "3. Point your domain DNS to: $EC2_IP"
echo ""

# Cleanup
rm -f /tmp/confio-full.tar.gz
rm -f /tmp/nginx-confio-full.conf
