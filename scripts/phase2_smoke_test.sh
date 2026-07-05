#!/bin/bash
# Phase 2 end-to-end smoke test
set -e
BASE=http://127.0.0.1:8765/api/v1

echo "=== 1. Create project + corpus ==="
PID=$(curl -sS -X POST "$BASE/projects" -H "Content-Type: application/json" -d '{"name":"Phase 2 Test","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
CID=$(curl -sS -X POST "$BASE/projects/$PID/corpora" -H "Content-Type: application/json" -d '{"name":"C","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "→ project=$PID corpus=$CID"

echo ""
echo "=== 2. Upload sample texts ==="
cat > /tmp/p2_1.txt <<'EOF'
However, the research approach was significant. The method demonstrated clear results.
Therefore, we conclude that the framework is valid. In other words, the data supports the theory.
The economy collapsed suddenly. The idea took root. Time flows like a river.
The dog was bitten by a snake. You must finish the work. The cat did not bark.
This is a great and wonderful day. The terrible disaster was awful. The meeting was held.
EOF
curl -sS -X POST "$BASE/corpora/$CID/documents" -F "files=@/tmp/p2_1.txt" | python3 -m json.tool | head -10

echo ""
echo "=== 3. N-grams (n=2) ==="
curl -sS -X POST "$BASE/corpora/$CID/ngrams" -H "Content-Type: application/json" -d '{"n":2,"min_freq":1,"min_range":1,"limit":5}' | python3 -m json.tool | head -25

echo ""
echo "=== 4. POS distribution ==="
curl -sS -X POST "$BASE/corpora/$CID/pos-analysis" -H "Content-Type: application/json" -d '{"n":1,"min_freq":1,"limit":10}' | python3 -m json.tool | head -25

echo ""
echo "=== 5. Grammar patterns (passive + modal + negation) ==="
curl -sS -X POST "$BASE/corpora/$CID/grammar" -H "Content-Type: application/json" -d '{"patterns":["passive_voice","modal","negation"],"limit":5}' | python3 -m json.tool | head -40

echo ""
echo "=== 6. Discourse (Hyland) ==="
curl -sS -X POST "$BASE/corpora/$CID/discourse" | python3 -m json.tool | head -30

echo ""
echo "=== 7. Vocabulary profile ==="
curl -sS -X POST "$BASE/corpora/$CID/vocab-profile" -H "Content-Type: application/json" -d '{"rare_threshold":1,"limit":20}' | python3 -m json.tool | head -25

echo ""
echo "=== 8. Sentiment ==="
curl -sS -X POST "$BASE/corpora/$CID/sentiment" | python3 -m json.tool | head -20

echo ""
echo "=== 9. Metaphor candidates ==="
curl -sS -X POST "$BASE/corpora/$CID/metaphor-candidates" -H "Content-Type: application/json" -d '{"limit":10}' | python3 -m json.tool | head -30

echo ""
echo "=== 10. AI tools (should include Phase 2 tools) ==="
curl -sS "$BASE/ai/tools" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data['tools']:
    print(f\"  {t['name']}\")
print(f'Total: {len(data[\"tools\"])} tools')
"

echo ""
echo "=== Phase 2 smoke test PASSED ==="
