#!/bin/bash
# rss-llm-worker-claude.sh — Mac, polls k-server, uses claude CLI
K_SERVER="${K_SERVER:-http://k-server.local:8180}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

echo "RSS LLM worker [claude CLI] (server=$K_SERVER)"

while true; do
    TASK=$(curl -sf "$K_SERVER/llm-queue/next")
    if [ -n "$TASK" ] && [ "$TASK" != "" ]; then
        ID=$(echo "$TASK" | jq -r '.id')
        MODE=$(echo "$TASK" | jq -r '.mode')
        SOURCE=$(echo "$TASK" | jq -r '.source_text')
        TITLE=$(echo "$TASK" | jq -r '.article_title')

        if [ "$MODE" = "translate" ]; then
            PROMPT="Přelož následující anotaci článku do češtiny. Stručně, 1-2 věty. Pouze překlad, žádný další text. Titulek: \"$TITLE\"

Text:
$SOURCE"
        else
            PROMPT="Shrň text článku do 2-3 vět v češtině. Buď výstižný. Pouze shrnutí, žádný další text. Titulek: \"$TITLE\"

Text:
$SOURCE"
        fi

        RESULT=$(echo "$PROMPT" | claude --print 2>/dev/null)

        if [ -n "$RESULT" ]; then
            curl -sf -X POST "$K_SERVER/llm-queue/$ID/result" \
                -H "Content-Type: application/json" \
                -d "{\"resultText\":$(echo "$RESULT" | jq -Rs .)}"
            echo "[$(date '+%H:%M:%S')] #$ID OK ($MODE)"
        else
            curl -sf -X POST "$K_SERVER/llm-queue/$ID/fail" \
                -H "Content-Type: application/json" \
                -d "{\"error\":\"claude CLI returned empty response\"}"
            echo "[$(date '+%H:%M:%S')] #$ID FAIL: empty response"
        fi
    fi
    sleep "$POLL_INTERVAL"
done
