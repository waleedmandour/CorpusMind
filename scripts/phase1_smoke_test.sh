#!/bin/bash
# Phase 1 end-to-end smoke test.
# Run after `corpusmind-engine` is up on :8765.
set -e

BASE=http://127.0.0.1:8765/api/v1

echo "=== 1. Create project ==="
PROJ=$(curl -sS -X POST "$BASE/projects" -H "Content-Type: application/json" \
    -d '{"name":"Test Project","language":"en"}')
echo "$PROJ"
PID=$(echo "$PROJ" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "→ project id: $PID"

echo ""
echo "=== 2. Create target + reference corpora ==="
TCID=$(curl -sS -X POST "$BASE/projects/$PID/corpora" -H "Content-Type: application/json" \
    -d '{"name":"Target Corpus","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
RCID=$(curl -sS -X POST "$BASE/projects/$PID/corpora" -H "Content-Type: application/json" \
    -d '{"name":"Reference Corpus","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "→ target corpus id: $TCID"
echo "→ reference corpus id: $RCID"

echo ""
echo "=== 3. Upload sample texts ==="
cat > /tmp/sample1.txt <<'EOF'
The quick brown fox jumps over the lazy dog. The dog was not amused.
Foxes are clever animals that live in forests. The dog is a loyal companion.
Quick thinking saved the day. The brown fox is a common sight in rural areas.
Dogs and foxes have a long history of interaction in folklore and literature.
EOF

cat > /tmp/sample2.txt <<'EOF'
The dog barked loudly at the stranger. Strangers are often met with suspicion.
Cats are independent creatures. The cat is a popular pet in many households.
Music brings people together. The concert was a great success last night.
Strangers became friends after a long conversation at the cafe.
EOF

curl -sS -X POST "$BASE/corpora/$TCID/documents" \
    -F "files=@/tmp/sample1.txt" -F "files=@/tmp/sample2.txt" \
    | python3 -m json.tool | head -20

curl -sS -X POST "$BASE/corpora/$RCID/documents" \
    -F "files=@/tmp/sample2.txt" \
    | python3 -m json.tool | head -10

echo ""
echo "=== 4. Concordance search for 'fox' ==="
curl -sS -X POST "$BASE/corpora/$TCID/concordance" -H "Content-Type: application/json" \
    -d '{"query":"fox","level":"lemma","window":5,"limit":5}' \
    | python3 -m json.tool | head -40

echo ""
echo "=== 5. Frequency (top 10 words) ==="
curl -sS -X POST "$BASE/corpora/$TCID/frequency" -H "Content-Type: application/json" \
    -d '{"unit":"word","min_freq":1,"limit":10}' \
    | python3 -m json.tool | head -25

echo ""
echo "=== 6. Collocations of 'fox' ==="
curl -sS -X POST "$BASE/corpora/$TCID/collocations" -H "Content-Type: application/json" \
    -d '{"node":"fox","level":"lemma","window":5,"min_freq":1}' \
    | python3 -m json.tool | head -30

echo ""
echo "=== 7. Keyness (target vs reference) ==="
curl -sS -X POST "$BASE/corpora/$TCID/keyness" -H "Content-Type: application/json" \
    -d "{\"reference_corpus_id\":\"$RCID\",\"min_freq\":1}" \
    | python3 -m json.tool | head -40

echo ""
echo "=== 8. Dispersion of 'the' ==="
curl -sS -X POST "$BASE/corpora/$TCID/dispersion" -H "Content-Type: application/json" \
    -d '{"term":"the","level":"word"}' \
    | python3 -m json.tool

echo ""
echo "=== 9. Export Excel (frequency) ==="
curl -sS -X POST "$BASE/corpora/$TCID/export/frequency.xlsx" \
    -H "Content-Type: application/json" \
    -d '{"unit":"word","limit":50}' \
    -o /tmp/freq.xlsx -w "%{http_code} %{size_download}\n"
ls -la /tmp/freq.xlsx

echo ""
echo "=== 10. Export PDF (methods section) ==="
curl -sS "$BASE/corpora/$TCID/methods.pdf" -o /tmp/methods.pdf -w "%{http_code} %{size_download}\n"
ls -la /tmp/methods.pdf

echo ""
echo "=== 11. AI tools list ==="
curl -sS "$BASE/ai/tools" | python3 -m json.tool

echo ""
echo "=== 12. List conversations ==="
curl -sS "$BASE/ai/conversations" | python3 -m json.tool | head -10

echo ""
echo "=== Phase 1 e2e smoke test PASSED ==="
echo "Project: $PID"
echo "Target corpus: $TCID"
echo "Reference corpus: $RCID"
