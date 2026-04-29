#!/bin/bash
# rss-llm-worker.sh — Mac, polls k-server for LLM tasks
K_SERVER="${K_SERVER:-https://k-server.local/api/rss}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY}"
MODEL="${LLM_MODEL:-claude-haiku-4-5-20251001}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

echo "RSS LLM worker (server=$K_SERVER, model=$MODEL)"

while true; do
    TASK=$(curl -sf "$K_SERVER/llm-queue/next")
    if [ -n "$TASK" ] && [ "$TASK" != "" ]; then
        ID=$(echo "$TASK" | jq -r '.id')
        MODE=$(echo "$TASK" | jq -r '.mode')
        SOURCE=$(echo "$TASK" | jq -r '.source_text')
        TITLE=$(echo "$TASK" | jq -r '.article_title')

        if [ "$MODE" = "translate" ]; then
            PROMPT="Přelož následující anotaci článku do češtiny. Stručně, 1-2 věty. Titulek: \"$TITLE\"\n\nText:\n$SOURCE"
        else
            PROMPT="Shrň text článku do 2-3 vět v češtině. Buď výstižný. Titulek: \"$TITLE\"\n\nText:\n$SOURCE"
        fi

        RESPONSE=$(curl -sf "https://api.anthropic.com/v1/messages" \
            -H "x-api-key: $ANTHROPIC_API_KEY" \
            -H "anthropic-version: 2023-06-01" \
            -H "content-type: application/json" \
            -d "{\"model\":\"$MODEL\",\"max_tokens\":300,\"messages\":[{\"role\":\"user\",\"content\":$(printf '%s' "$PROMPT" | jq -Rs .)}]}")

        RESULT=$(echo "$RESPONSE" | jq -r '.content[0].text // empty')

        if [ -n "$RESULT" ]; then
            curl -sf -X POST "$K_SERVER/llm-queue/$ID/result" \
                -H "Content-Type: application/json" \
                -d "{\"resultText\":$(echo "$RESULT" | jq -Rs .)}"
            echo "[$(date '+%H:%M:%S')] #$ID OK ($MODE)"
        else
            ERROR=$(echo "$RESPONSE" | jq -r '.error.message // "unknown"')
            curl -sf -X POST "$K_SERVER/llm-queue/$ID/fail" \
                -H "Content-Type: application/json" \
                -d "{\"error\":$(echo "$ERROR" | jq -Rs .)}"
            echo "[$(date '+%H:%M:%S')] #$ID FAIL: $ERROR"
        fi
    fi
    sleep "$POLL_INTERVAL"
done
