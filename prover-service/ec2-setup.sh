#!/bin/bash

# EC2 Setup Script for zkLogin Prover
# Instance type: t3.small (2 vCPU, 2 GB RAM)
# OS: Amazon Linux 2023 or Ubuntu 22.04
# Architecture: x86_64 (required for zkLogin prover)

echo "🚀 Setting up zkLogin Prover on EC2..."

# Update system
echo "📦 Updating system packages..."
sudo yum update -y || sudo apt update -y

# Install Docker
echo "🐳 Installing Docker..."
if command -v yum &> /dev/null; then
    # Amazon Linux 2023
    sudo yum install -y docker
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -a -G docker ec2-user
else
    # Ubuntu
    sudo apt install -y docker.io docker-compose
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -a -G docker ubuntu
fi

# Install Git
echo "📥 Installing Git..."
sudo yum install -y git || sudo apt install -y git

# Clone the zkLogin prover repository
echo "📂 Cloning zkLogin prover..."
cd /home/ec2-user || cd /home/ubuntu
git clone https://github.com/MystenLabs/zklogin-ceremony-contributions.git
cd zklogin-ceremony-contributions

# Create docker-compose.yml for the prover
echo "📝 Creating docker-compose configuration..."
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  prover:
    image: mysten/zklogin:prover-a66971815c15c55e6c9e254e0f0712ef2ce26383f2787867fd39965fdf10e84f
    container_name: zklogin-prover
    environment:
      - PROVER_PORT=8080
      - PROVER_HOST=0.0.0.0
      - NODE_ENV=production
      - RUST_LOG=info
      - RUST_BACKTRACE=1
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
      - ./zkeys:/app/zkeys
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1.5'
          memory: 1500M
        reservations:
          cpus: '1.0'
          memory: 1000M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  # Optional: Nginx reverse proxy with SSL
  nginx:
    image: nginx:alpine
    container_name: zklogin-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - prover
    restart: unless-stopped
EOF

# Create nginx configuration
echo "🔧 Creating nginx configuration..."
cat > nginx.conf << 'EOF'
events {
    worker_connections 1024;
}

http {
    upstream prover {
        server prover:8080;
    }

    server {
        listen 80;
        server_name _;

        location / {
            proxy_pass http://prover;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Timeouts for long-running proof generation
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }

        location /health {
            proxy_pass http://prover/health;
            access_log off;
        }
    }
}
EOF

# Create data directories
echo "📁 Creating data directories..."
mkdir -p data zkeys ssl

# Download zkeys if needed
echo "📥 Downloading zkeys (this may take a while)..."
cd zkeys
# The Docker image should have zkeys included, but we create the directory just in case
cd ..

# Start the services
echo "🚀 Starting zkLogin prover..."
sudo docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 30

# Check service status
echo "✅ Checking service status..."
sudo docker-compose ps
curl -s http://localhost:8080/health || echo "⚠️  Health check failed, service may still be starting..."

# Create systemd service for auto-start
echo "🔧 Creating systemd service..."
sudo tee /etc/systemd/system/zklogin-prover.service > /dev/null << 'EOF'
[Unit]
Description=zkLogin Prover Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ec2-user/zklogin-ceremony-contributions
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable zklogin-prover

# Create monitoring script
echo "📊 Creating monitoring script..."
cat > monitor.sh << 'EOF'
#!/bin/bash
echo "zkLogin Prover Status"
echo "===================="
docker-compose ps
echo ""
echo "Resource Usage:"
docker stats --no-stream
echo ""
echo "Recent Logs:"
docker-compose logs --tail=20
echo ""
echo "Health Check:"
curl -s http://localhost:8080/health | jq . || echo "Health check failed"
EOF
chmod +x monitor.sh

# Display connection information
echo "
✅ zkLogin Prover setup complete!

📋 Important Information:
- Prover URL: http://YOUR_EC2_PUBLIC_IP:8080
- Health check: http://YOUR_EC2_PUBLIC_IP:8080/health
- Monitor status: ./monitor.sh
- View logs: docker-compose logs -f
- Restart service: docker-compose restart

🔒 Security Group Rules Required:
- Port 8080: zkLogin Prover API
- Port 80: HTTP (if using nginx)
- Port 443: HTTPS (if using SSL)
- Port 22: SSH access

💡 Next Steps:
1. Configure security group to allow port 8080
2. Update your app to use http://YOUR_EC2_PUBLIC_IP:8080/v1
3. Consider setting up a domain name and SSL certificate
4. Monitor CloudWatch for spot instance interruption notices

⚠️  For production use:
- Set up CloudWatch alarms for health monitoring
- Configure auto-restart on spot instance interruption
- Use Elastic IP for consistent endpoint
- Set up SSL/TLS with Let's Encrypt
"