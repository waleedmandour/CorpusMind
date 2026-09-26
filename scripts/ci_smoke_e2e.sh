#!/usr/bin/env bash
# End-to-end functional check against a RUNNING engine: ingest a tiny
# corpus and run the USAS, sentiment and persuasion lenses. Used locally
# to verify the bundled engine beyond resource availability.
set -euo pipefail
BASE="${1:-http://127.0.0.1:8799}"

PID=$(curl -fsS -X POST "$BASE/api/v1/projects" -H "Content-Type: application/json" \
  -d '{"name":"smoke-e2e","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
CID=$(curl -fsS -X POST "$BASE/api/v1/projects/$PID/corpora" -H "Content-Type: application/json" \
  -d '{"name":"smoke","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
printf 'The proposal was wonderful and persuasive. It is not convincing at all, unfortunately. Clearly the evidence is remarkable and the argument very strong.\n' > /tmp/smoke-e2e.txt
curl -fsS -X POST "$BASE/api/v1/corpora/$CID/documents" -F "files=@/tmp/smoke-e2e.txt;type=text/plain" >/dev/null
# wait for ingestion
for _ in $(seq 1 30); do
  N=$(curl -fsS "$BASE/api/v1/corpora/$CID/documents" | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d if isinstance(d,list) else d.get('documents',[])))" 2>/dev/null || echo 0)
  [ "$N" -ge 1 ] && break
  sleep 1
done

echo "--- USAS (taxonomy=usas) ---"
USAS_CODE=$(curl -s -o /tmp/usas.json -w "%{http_code}" -X POST "$BASE/api/v1/corpora/$CID/discourse" -H "Content-Type: application/json" -d '{"taxonomy":"usas"}')
python3 - "$USAS_CODE" <<'EOF'
import json, sys
code = int(sys.argv[1])
d = json.load(open("/tmp/usas.json"))
assert code == 200, f"USAS HTTP {code}: {d}"
assert d.get("taxonomy_key") == "usas" and d.get("categories"), d
print(f"OK usas: {len(d['categories'])} categories, unmatched={d.get('unmatched_percent')}%")
EOF

echo "--- Sentiment (layered) ---"
SENT_CODE=$(curl -s -o /tmp/sent.json -w "%{http_code}" -X POST "$BASE/api/v1/corpora/$CID/sentiment")
python3 - "$SENT_CODE" <<'EOF'
import json, sys
code = int(sys.argv[1])
d = json.load(open("/tmp/sent.json"))
assert code == 200, f"sentiment HTTP {code}: {d}"
assert d["method"] == "appraisal-nuanced-v1", d.get("method")
assert d["negative"] >= 1 and d["positive"] >= 1, d
assert d["appraisal"]["categories"]["engagement.proclaim"]["count"] >= 1, d["appraisal"]
print(f"OK sentiment: pos={d['positive']} neg={d['negative']} neu={d['neutral']} emotions={ {k:v for k,v in d['emotions'].items() if v} }")
EOF

echo "--- Persuasion lens ---"
PERS_CODE=$(curl -s -o /tmp/pers.json -w "%{http_code}" -X POST "$BASE/api/v1/corpora/$CID/discourse" -H "Content-Type: application/json" -d '{"taxonomy":"persuasion_gong2026"}')
python3 - "$PERS_CODE" <<'EOF'
import json, sys
code = int(sys.argv[1])
d = json.load(open("/tmp/pers.json"))
assert code == 200, f"persuasion HTTP {code}: {d}"
assert d.get("taxonomy_key") == "persuasion_gong2026", d
cats = d.get("categories", {})
assert len(cats) == 15, f"expected 15 dimensions, got {len(cats)}"
print(f"OK persuasion: 15 dimensions, scored_documents={d.get('scored_documents')}")
EOF

echo "E2E PASS: USAS + layered sentiment + persuasion all functional"
