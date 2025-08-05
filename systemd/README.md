# Systemd Service Configuration for Confio

## Overview

This directory contains systemd service files for managing the Confio application stack. Systemd provides better security, resource management, and integration compared to supervisor.

## Services

### 1. confio-django.service
- **Purpose**: Runs the Django application with Gunicorn
- **Port**: Unix socket at `/run/confio/gunicorn.sock`
- **Workers**: 4 sync workers
- **Security**: Full systemd hardening with sandboxing

### 2. confio-daphne.service
- **Purpose**: WebSocket server for real-time features
- **Port**: 127.0.0.1:8001
- **Protocol**: ASGI for WebSocket support
- **Use Case**: P2P chat, live notifications

### 3. confio-celery-worker.service
- **Purpose**: Background task processing
- **Concurrency**: 4 workers
- **Queues**: default, high_priority, low_priority
- **Tasks**: Email sending, blockchain operations, data processing

### 4. confio-celery-beat.service
- **Purpose**: Scheduled task execution
- **Schedule**: Periodic tasks like cleanup, reports
- **Database**: Uses celerybeat-schedule.db

### 5. confio.target
- **Purpose**: Groups all services for unified control
- **Management**: Start/stop all services together

## Security Features

All services include systemd security hardening:
- `NoNewPrivileges`: Prevents privilege escalation
- `PrivateTmp`: Isolated temporary directories
- `ProtectSystem`: Read-only system directories
- `ProtectHome`: No access to user home directories
- `RestrictAddressFamilies`: Limited network access
- `SystemCallFilter`: Restricted system calls
- Resource limits for stability

## Management Commands

### Start all services
```bash
sudo systemctl start confio.target
```

### Stop all services
```bash
sudo systemctl stop confio.target
```

### Restart all services
```bash
sudo systemctl restart confio.target
```

### Check status
```bash
sudo systemctl status confio.target
```

### View logs
```bash
# All services
sudo journalctl -u confio.target -f

# Individual service
sudo journalctl -u confio-django -f
sudo journalctl -u confio-celery-worker -f
```

### Enable auto-start on boot
```bash
sudo systemctl enable confio.target
```

## Advantages over Supervisor

1. **Native Integration**: Part of the OS, no extra software needed
2. **Security**: Advanced sandboxing and isolation features
3. **Resource Management**: CPU, memory, and I/O limits
4. **Dependencies**: Proper service ordering and dependencies
5. **Logging**: Centralized with journald
6. **Monitoring**: Built-in health checks and auto-restart
7. **Cgroups**: Process grouping and resource accounting

## Troubleshooting

### Service won't start
```bash
sudo journalctl -xe -u confio-django
```

### Permission issues
Ensure the confio user owns:
- `/opt/confio`
- `/var/log/confio`
- `/var/run/celery`
- `/run/confio`

### Database connection
Check PostgreSQL and Redis are running:
```bash
sudo systemctl status postgresql-15
sudo systemctl status redis6
```

### Reload after config changes
```bash
sudo systemctl daemon-reload
sudo systemctl restart confio.target
```