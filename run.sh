#!/bin/bash

# Auto-restart wrapper for mqtt-music-viz
# This script will automatically restart the app when config.yaml changes

echo "🎵 MQTT Music Visualiser - Auto-restart enabled"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

while true; do
    echo ""
    echo "$(date '+%H:%M:%S') - Starting application..."
    
    uv run python app.py
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ] || [ $EXIT_CODE -eq 143 ] || [ $EXIT_CODE -eq 15 ]; then
        # Clean shutdown (SIGTERM) - restart
        echo ""
        echo "$(date '+%H:%M:%S') - Configuration changed, restarting in 1 second..."
        sleep 1
    else
        # Error exit - stop
        echo ""
        echo "$(date '+%H:%M:%S') - Application exited with error code $EXIT_CODE"
        echo "Stopping auto-restart. Fix the error and restart manually."
        exit $EXIT_CODE
    fi
done
