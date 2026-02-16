#!/bin/bash
# Monitor the active Storage Transfer Service job

PROJECT_ID="cloud-crate-485418"

echo "🔍 Finding active transfer operations..."

# Loop to monitor
while true; do
    # Get the latest operation details in JSON
    OP_JSON=$(gcloud transfer operations list \
        --project=$PROJECT_ID \
        --limit=1 \
        --format="json(name, metadata.status, metadata.counters.bytesCopiedToSink, metadata.counters.bytesFoundFromSource)")
    
    # Extract values using python for reliability (no jq dependency)
    read -r NAME STATUS COPIED TOTAL <<< $(echo $OP_JSON | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if not data:
        print('NONE NONE 0 0')
        sys.exit(0)
    op = data[0]
    meta = op.get('metadata', {})
    counters = meta.get('counters', {})
    print(f\"{op['name']} {meta.get('status', 'UNKNOWN')} {counters.get('bytesCopiedToSink', 0)} {counters.get('bytesFoundFromSource', 0)}\")
except Exception:
    print('ERROR ERROR 0 0')
")

    if [ "$NAME" == "NONE" ]; then
        echo "No active transfer operations found."
        exit 0
    fi

    # Convert to GB for display
    COPIED_GB=$(echo "scale=2; $COPIED / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "0")
    TOTAL_GB=$(echo "scale=2; $TOTAL / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "0")
    
    # Calculate percentage
    if [ "$TOTAL" -gt 0 ]; then
        PCT=$(echo "scale=2; $COPIED * 100 / $TOTAL" | bc 2>/dev/null || echo "0")
    else
        PCT="0"
    fi

    # Clear screen and print status
    clear
    echo "=================================================="
    echo "📦 Storage Transfer Service Monitor"
    echo "=================================================="
    echo "Operation: $NAME"
    echo "Status:    $STATUS"
    echo ""
    echo "Progress:  $COPIED_GB GB / $TOTAL_GB GB"
    echo "           ($PCT%)"
    echo ""
    
    # Draw simple progress bar
    BAR_LEN=$(echo "$PCT / 2" | bc 2>/dev/null | cut -d. -f1)
    if [ -z "$BAR_LEN" ]; then BAR_LEN=0; fi
    printf "["
    for ((i=0; i<BAR_LEN; i++)); do printf "#"; done
    for ((i=BAR_LEN; i<50; i++)); do printf " "; done
    printf "]\n"
    
    echo ""
    echo "Press Ctrl+C to stop monitoring."
    
    if [ "$STATUS" == "SUCCESS" ]; then
        echo ""
        echo "✅ Transfer Complete! You can now run ./deploy.sh"
        exit 0
    fi
    
    if [ "$STATUS" == "FAILED" ] || [ "$STATUS" == "ABORTED" ]; then
        echo ""
        echo "❌ Transfer Failed or Aborted."
        exit 1
    fi

    sleep 5
done
