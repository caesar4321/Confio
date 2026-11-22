#!/bin/bash
# Daphne health check script - auto-restarts on failure
# Runs every 2 minutes via daphne-healthcheck.timer

TIMEOUT=5
BOOT_GRACE=90 # Daphne takes 30-45 s to start listening
RESPONSE=$(curl -s -m $TIMEOUT -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/graphql/ 2>&1)

if [ "$RESPONSE" = "400" ] || [ "$RESPONSE" = "200" ]; then
    # 400 is expected for GET on GraphQL, 200 is also acceptable
    exit 0
else
    # A process that just started is still booting: killing it only restarts the
    # boot. Unknown start time or any other state falls through to the restart.
    STATE=$(systemctl show -p ActiveState --value daphne.service)
    STARTED=$(systemctl show -p ActiveEnterTimestampMonotonic --value daphne.service)
    read -r UPTIME _ < /proc/uptime
    if [ "$STATE" = "active" ] && [[ "$STARTED" =~ ^[1-9][0-9]*$ ]]; then
        AGE=$(( ${UPTIME%%.*} - STARTED / 1000000 ))
        if [ "$AGE" -ge 0 ] && [ "$AGE" -lt "$BOOT_GRACE" ]; then
            logger -t daphne-healthcheck "Daphne booting (${AGE}s, HTTP $RESPONSE), not restarting"
            exit 0
        fi
    fi

    # Any other response or timeout is a failure - force kill and restart Daphne
    logger -t daphne-healthcheck "Daphne unresponsive (HTTP $RESPONSE), force-killing and restarting..."
    systemctl kill -s SIGKILL daphne.service
    systemctl start daphne.service
    exit 1
fi
