#!/bin/bash

# Deploy Confio web app to EC2 instance

# Configuration
EC2_IP="51.96.174.134"  # Your Elastic IP for confio instance
EC2_USER="ec2-user"
KEY_PATH="~/.ssh/confio-key.pem"
WEB_DIR="/Users/julian/Confio/web"
REMOTE_DIR="/var/www/confio"

echo "🚀 Starting deployment of Confio web app to EC2..."

# Build the React app if not already built
echo "📦 Building React app..."
cd $WEB_DIR
if [ ! -d "build" ] || [ "$1" == "--rebuild" ]; then
    npm run build
    if [ $? -ne 0 ]; then
        echo "❌ Build failed. Please fix errors and try again."
        exit 1
    fi
else
    echo "Using existing build. Run with --rebuild to force new build."
fi

# Copy deep link files to build directory
echo "📱 Copying deep link files..."
cp -r .well-known build/

echo "🔗 Connecting to EC2 instance..."

# Create deployment package
echo "📦 Creating deployment package..."
tar -czf /tmp/confio-web-build.tar.gz -C build .

# Copy nginx config
cp nginx-ec2.conf /tmp/nginx-confio.conf

echo "📤 Uploading files to EC2..."
# Upload build package
scp -i $KEY_PATH /tmp/confio-web-build.tar.gz $EC2_USER@$EC2_IP:/tmp/
scp -i $KEY_PATH /tmp/nginx-confio.conf $EC2_USER@$EC2_IP:/tmp/

# Deploy on server
echo "🔧 Setting up web server..."
ssh -i $KEY_PATH $EC2_USER@$EC2_IP << 'ENDSSH'
    # Install nginx if not already installed
    if ! command -v nginx &> /dev/null; then
        echo "Installing nginx..."
        sudo yum update -y
        sudo yum install -y nginx
    fi

    # Create web directory
    sudo mkdir -p /var/www/confio
    
    # Extract build files
    sudo tar -xzf /tmp/confio-web-build.tar.gz -C /var/www/confio
    
    # Set proper permissions
    sudo chown -R nginx:nginx /var/www/confio
    sudo chmod -R 755 /var/www/confio
    
    # Setup nginx config
    sudo cp /tmp/nginx-confio.conf /etc/nginx/conf.d/confio.conf
    
    # Remove default nginx config if exists
    sudo rm -f /etc/nginx/conf.d/default.conf
    
    # Test nginx configuration
    sudo nginx -t
    
    # Enable and restart nginx
    sudo systemctl enable nginx
    sudo systemctl restart nginx
    
    # Setup firewall rules (if firewall is enabled)
    sudo firewall-cmd --permanent --add-service=http 2>/dev/null || true
    sudo firewall-cmd --permanent --add-service=https 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
    
    # Clean up temp files
    rm /tmp/confio-web-build.tar.gz
    rm /tmp/nginx-confio.conf
    
    echo "✅ Deployment complete!"
ENDSSH

echo ""
echo "========================================="
echo "✅ Confio web app deployed successfully!"
echo "========================================="
echo "🌐 Website URL: http://$EC2_IP"
echo "🌐 Website URL: http://confio.app (once DNS is configured)"
echo ""
echo "Next steps:"
echo "1. Configure your domain DNS to point to: $EC2_IP"
echo "2. Set up SSL certificate with Let's Encrypt"
echo "3. Configure monitoring and backups"
echo ""

# Cleanup local temp files
rm -f /tmp/confio-web-build.tar.gz
rm -f /tmp/nginx-confio.conf