#!/bin/bash
# Phase 4 Vision end-to-end smoke test
set -e
BASE=http://127.0.0.1:8765/api/v1

echo "=== 1. Create project + corpus + image set ==="
PID=$(curl -sS -X POST "$BASE/projects" -H "Content-Type: application/json" -d '{"name":"Vision Test","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
CID=$(curl -sS -X POST "$BASE/projects/$PID/corpora" -H "Content-Type: application/json" -d '{"name":"Images","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
ISET=$(curl -sS -X POST "$BASE/corpora/$CID/image-sets" -H "Content-Type: application/json" -d '{"name":"Test Set"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "→ project=$PID corpus=$CID image_set=$ISET"

echo ""
echo "=== 2. Generate + upload test image ==="
python3 -c "
from PIL import Image
import io
img = Image.new('RGB', (200, 200), (220, 50, 50))  # red
img.save('/tmp/test_red.png')
print('image created')
"
IMG=$(curl -sS -X POST "$BASE/image-sets/$ISET/images" -F "files=@/tmp/test_red.png" | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['id'])")
echo "→ image_id=$IMG"

echo ""
echo "=== 3. Get image analysis (colour + composition + OCR) ==="
curl -sS "$BASE/images/$IMG/analysis" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Dimensions: {d[\"dimensions\"]}')
print(f'  OCR engine: {d[\"analysis\"][\"ocr\"][\"engine\"]}')
print(f'  Dominant colour: {d[\"analysis\"][\"colours\"][\"dominant_colours\"][0][\"hex\"]}')
print(f'  Brightness: {d[\"analysis\"][\"colours\"][\"brightness\"]}')
print(f'  Salience centre: {d[\"analysis\"][\"composition\"][\"salience_centre\"]}')
print(f'  Info value (left/right): {d[\"analysis\"][\"composition\"][\"information_value\"][\"left\"]:.3f} / {d[\"analysis\"][\"composition\"][\"information_value\"][\"right\"]:.3f}')
"

echo ""
echo "=== 4. Visual Grammar analysis (Kress & van Leeuwen) ==="
curl -sS -X POST "$BASE/images/$IMG/visual-grammar" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Framework: {d[\"framework\"]}')
print(f'  Claims: {len(d[\"claims\"])}')
for c in d['claims'][:3]:
    print(f'    [{c[\"metafunction\"]}] {c[\"category\"]} (conf={c[\"confidence\"]})')
    print(f'      → {c[\"claim\"][:100]}...')
print(f'  Scores:')
for mf, s in d['scores'].items():
    print(f'    {mf}: {s[\"claim_count\"]} claims, avg conf {s[\"avg_confidence\"]}')
"

echo ""
echo "=== 5. Image-text alignment (flagship §9.8) ==="
curl -sS -X POST "$BASE/images/$IMG/align" -H "Content-Type: application/json" \
    -d '{"text":"A red square on the left side of the image"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Method: {d[\"method\"]}')
print(f'  Regions: {len(d[\"regions\"])} (3x3 grid)')
print(f'  Text spans: {len(d[\"spans\"])}')
print(f'  Alignments: {len(d[\"alignments\"])}')
for a in d['alignments'][:3]:
    print(f'    {a[\"region_id\"]} ↔ \"{a[\"span_text\"]}\" (conf={a[\"confidence\"]}) — {a[\"match_reason\"][:80]}')
print(f'  Cross-modal relations: {len(d[\"cross_modal_relations\"])}')
for r in d['cross_modal_relations']:
    print(f'    [{r[\"relation_type\"]}] {r[\"description\"][:80]}...')
"

echo ""
echo "=== Phase 4 Vision smoke test PASSED ==="
