#!/bin/bash

# Exit on error
set -e

# Configuration
DOMAIN="confio.lat"
LOG_FILE="deployment.log"

# Function to load environment variables
load_env() {
    if [ ! -f ".env" ]; then
        log "Error: .env file not found. Please create one with EXISTING_INSTANCE_IP."
        exit 1
    fi
    
    # Load .env file
    set -a
    source .env
    set +a
    
    # Check if EXISTING_INSTANCE_IP is set
    if [ -z "$EXISTING_INSTANCE_IP" ]; then
        log "Error: EXISTING_INSTANCE_IP not set in .env file."
        exit 1
    fi
}

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to check if a command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log "Error: $1 is required but not installed."
        exit 1
    fi
}

# Function to check if a file exists
check_file() {
    if [ ! -f "$1" ]; then
        log "Error: Required file $1 not found."
        exit 1
    fi
}

# Function to check if a directory exists
check_directory() {
    if [ ! -d "$1" ]; then
        log "Error: Required directory $1 not found."
        exit 1
    fi
}

# Function to check if instance exists and is reachable
check_instance_exists() {
    if [ -z "$EXISTING_INSTANCE_IP" ]; then
        log "Error: EXISTING_INSTANCE_IP must be set."
        exit 1
    fi
    
    log "Checking if instance $EXISTING_INSTANCE_IP is reachable..."
    if ! ssh -i ~/.ssh/id_ed25519_confio -o ConnectTimeout=5 -o BatchMode=yes ubuntu@$EXISTING_INSTANCE_IP "echo 'Instance is reachable'" &> /dev/null; then
        log "Error: Instance $EXISTING_INSTANCE_IP is not reachable via SSH."
        exit 1
    fi
    log "Instance is reachable via SSH."
}

# Function to check if DNS record exists
check_dns_exists() {
    if [ -z "$DOMAIN" ]; then
        log "Error: DOMAIN must be set."
        exit 1
    fi
}

# Function to check and setup SSH key
setup_ssh_key() {
    SSH_KEY_PATH="$HOME/.ssh/id_ed25519_confio"
    if [ ! -f "$SSH_KEY_PATH" ]; then
        log "Generating new SSH key for Confio..."
        ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N ""
    fi
    
    # Add key to SSH agent if not already added
    if ! ssh-add -l | grep -q "$(ssh-keygen -l -f "$SSH_KEY_PATH" | awk '{print $2}')"; then
        ssh-add "$SSH_KEY_PATH"
    fi
    
    # Check if we can SSH without password
    if ! ssh -o BatchMode=yes -i "$SSH_KEY_PATH" "ubuntu@$EXISTING_INSTANCE_IP" true 2>/dev/null; then
        log "SSH key not yet set up on the instance."
        log "Please follow these steps to set up SSH key authentication:"
        log "1. Copy your public key to the instance:"
        log "   cat ${SSH_KEY_PATH}.pub | ssh ubuntu@$EXISTING_INSTANCE_IP 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'"
        log "2. Set proper permissions on the remote:"
        log "   ssh ubuntu@$EXISTING_INSTANCE_IP 'chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys'"
        log "3. Try to SSH into the instance:"
        log "   ssh -i $SSH_KEY_PATH ubuntu@$EXISTING_INSTANCE_IP"
        log ""
        log "After completing these steps, run this script again."
        exit 1
    else
        log "SSH key already set up on the instance."
    fi
}

# Function to rollback changes in case of failure
rollback() {
    log "Rolling back changes due to deployment failure..."
    # Add rollback steps here if needed
    exit 1
}

# Main deployment function
deploy() {
    log "Starting deployment checks..."
    
    # Load environment variables
    load_env
    
    # Check required commands
    check_command ssh
    check_command scp
    check_command rsync
    
    # Check required files
    check_file "web/package.json"
    check_file "web/yarn.lock"
    check_file "requirements.txt"
    check_file "nginx.conf"
    check_file "supervisord.conf"
    check_file "manage.py"
    
    # Check required directories
    check_directory "web"
    check_directory "static"
    check_directory "templates"
    check_directory "config"
    check_directory "apps"
    
    # Check instance and domain
    check_instance_exists
    check_dns_exists
    
    # Setup SSH key
    setup_ssh_key
    
    log "All pre-deployment checks passed."
    
    # Build web assets
    log "Building web assets..."
    cd web
    if ! yarn install; then
        log "Error: Failed to install web dependencies."
        rollback
    fi
    if ! yarn build; then
        log "Error: Failed to build web assets."
        rollback
    fi
    cd ..
    
    # Create necessary directories on remote server
    log "Creating directories on remote server..."
    if ! ssh -i ~/.ssh/id_ed25519_confio ubuntu@$EXISTING_INSTANCE_IP "sudo mkdir -p /var/www/html /var/www/confio/templates /var/www/confio/venv /var/www/confio/config /var/www/confio/apps /var/www/confio/users && \
        sudo chown -R ubuntu:ubuntu /var/www/html /var/www/confio"; then
        log "Error: Failed to create directories on remote server."
        rollback
    fi
    
    # Copy files to remote server
    log "Copying files to remote server..."
    if ! rsync -avz --exclude 'node_modules' --exclude '.git' web/build/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/html/; then
        log "Error: Failed to copy web build files."
        rollback
    fi
    if ! rsync -avz static/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/html/static/; then
        log "Error: Failed to copy static files."
        rollback
    fi
    if ! rsync -avz templates/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/templates/; then
        log "Error: Failed to copy template files."
        rollback
    fi
    if ! rsync -avz config/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/config/; then
        log "Error: Failed to copy config files."
        rollback
    fi
    if ! rsync -avz apps/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/apps/; then
        log "Error: Failed to copy app files."
        rollback
    fi
    if ! rsync -avz users/ ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/users/; then
        log "Error: Failed to copy user files."
        rollback
    fi
    if ! scp manage.py ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/; then
        log "Error: Failed to copy manage.py."
        rollback
    fi
    if ! scp requirements.txt ubuntu@$EXISTING_INSTANCE_IP:/var/www/confio/; then
        log "Error: Failed to copy requirements.txt."
        rollback
    fi
    if ! scp nginx.conf ubuntu@$EXISTING_INSTANCE_IP:/tmp/nginx.conf; then
        log "Error: Failed to copy nginx.conf."
        rollback
    fi
    if ! scp supervisord.conf ubuntu@$EXISTING_INSTANCE_IP:/tmp/supervisord.conf; then
        log "Error: Failed to copy supervisord.conf."
        rollback
    fi
    
    # Install system packages and configure services
    log "Installing system packages and configuring services..."
    if ! ssh -i ~/.ssh/id_ed25519_confio ubuntu@$EXISTING_INSTANCE_IP "
        # Update package lists with reduced output
        sudo apt-get update -qq && \
        
        # Install packages one at a time to reduce memory usage
        for pkg in python3-pip python3-venv supervisor nginx postgresql postgresql-contrib postgis python3-psycopg2 libpq-dev; do
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \$pkg
        done && \
        
        # Set up Python environment
        sudo python3 -m venv /var/www/confio/venv && \
        sudo /var/www/confio/venv/bin/pip install --no-cache-dir -r /var/www/confio/requirements.txt && \
        sudo chown -R ubuntu:ubuntu /var/www/confio/venv && \
        
        # Collect static files
        cd /var/www/confio && \
        /var/www/confio/venv/bin/python manage.py collectstatic --noinput && \
        
        # Configure services
        sudo cp /tmp/nginx.conf /etc/nginx/nginx.conf && \
        sudo cp /tmp/supervisord.conf /etc/supervisor/conf.d/confio.conf && \
        sudo chown -R www-data:www-data /var/www/html /var/www/confio && \
        
        # Restart services
        sudo systemctl restart supervisor && \
        sudo systemctl restart nginx"; then
        log "Error: Failed to install packages or configure services."
        rollback
    fi
    
    log "Deployment completed successfully!"
}

# Execute deployment
deploy 