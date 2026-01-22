#!/bin/bash
# Daphne health check script - auto-restarts on failure
# Runs every 2 minutes via daphne-healthcheck.timer

TIMEOUT=5
RESPONSE=$(curl -s -m $TIMEOUT -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/graphql/ 2>&1)

if [ "$RESPONSE" = "400" ] || [ "$RESPONSE" = "200" ]; then
    # 400 is expected for GET on GraphQL, 200 is also acceptable
    exit 0
else
    # Any other response or timeout is a failure - force kill and restart Daphne
    logger -t daphne-healthcheck "Daphne unresponsive (HTTP $RESPONSE), force-killing and restarting..."
    systemctl kill -s SIGKILL daphne.service
    systemctl start daphne.service
    exit 1
fi
