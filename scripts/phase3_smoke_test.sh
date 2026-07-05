#!/bin/bash
# Phase 3 end-to-end Arabic smoke test
set -e
BASE=http://127.0.0.1:8765/api/v1

echo "=== 1. List Arabic backends ==="
curl -sS "$BASE/arabic/backends" | python3 -m json.tool

echo ""
echo "=== 2. Morphology analysis ==="
curl -sS -X POST "$BASE/arabic/analyze" -H "Content-Type: application/json" \
    -d '{"text":"الطلاب يدرسون في المكتبة الكبيرة","dialect":"msa"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Backend: {d[\"backend\"]}, Dialect: {d[\"detected_dialect\"]}, Tokens: {d[\"token_count\"]}')
for t in d['tokens'][:5]:
    print(f'  {t[\"text\"]:15s} → root={t[\"root\"]:10s} pattern={t[\"pattern\"]:20s} lemma={t[\"lemma\"]:15s} pos={t[\"pos\"]}')
"

echo ""
echo "=== 3. Root extraction ==="
curl -sS -X POST "$BASE/arabic/roots" -H "Content-Type: application/json" \
    -d '{"text":"يكتب الكاتب في المكتبة كتابا"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for r in d['roots']:
    print(f'  {r[\"token\"]:12s} → root={r[\"root\"]:10s} pattern={r[\"pattern\"]}')
"

echo ""
echo "=== 4. Buckwalter transliteration ==="
curl -sS -X POST "$BASE/arabic/buckwalter" -H "Content-Type: application/json" \
    -d '{"text":"الطلاب يدرسون في المكتبة"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Original (RTL): {d[\"original\"]}')
print(f'  Buckwalter (LTR): {d[\"buckwalter\"]}')
"

echo ""
echo "=== 5. Dediacritization ==="
curl -sS -X POST "$BASE/arabic/dediacritize" -H "Content-Type: application/json" \
    -d '{"text":"يَدْرُسُونَ فِي المَكْتَبَةِ"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Original: {d[\"original\"]}')
print(f'  Dediac:   {d[\"dediacritized\"]}')
"

echo ""
echo "=== 6. Normalization ==="
curl -sS -X POST "$BASE/arabic/normalize" -H "Content-Type: application/json" \
    -d '{"text":"هذا بيت كبيره"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  Original:   {d[\"original\"]}')
print(f'  Normalized: {d[\"normalized\"]}')
"

echo ""
echo "=== 7. Dialect ID (MSA text) ==="
curl -sS -X POST "$BASE/arabic/dialect" -H "Content-Type: application/json" \
    -d '{"text":"الطلاب يدرسون في المكتبة"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for dialect, prob in sorted(d['dialect_distribution'].items(), key=lambda x: -x[1]):
    print(f'  {dialect}: {prob*100:.1f}%')
"

echo ""
echo "=== 8. Dialect ID (Egyptian text) ==="
curl -sS -X POST "$BASE/arabic/dialect" -H "Content-Type: application/json" \
    -d '{"text":"انا عايز اروح المدرسة"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for dialect, prob in sorted(d['dialect_distribution'].items(), key=lambda x: -x[1]):
    print(f'  {dialect}: {prob*100:.1f}%')
"

echo ""
echo "=== 9. Register detection ==="
curl -sS -X POST "$BASE/arabic/register" -H "Content-Type: application/json" \
    -d '{"text":"قال المعلم للطلاب إن الاجتهاد طريق النجاح"}' \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for reg, prob in sorted(d['register_distribution'].items(), key=lambda x: -x[1]):
    print(f'  {reg}: {prob*100:.1f}%')
"

echo ""
echo "=== 10. AI tools (should include 5 Arabic tools) ==="
curl -sS "$BASE/ai/tools" | python3 -c "
import json, sys
data = json.load(sys.stdin)
arabic_tools = [t for t in data['tools'] if t['name'].startswith('arabic_')]
print(f'Arabic tools: {len(arabic_tools)}')
for t in arabic_tools:
    print(f'  {t[\"name\"]}')
print(f'Total tools: {len(data[\"tools\"])}')
"

echo ""
echo "=== Phase 3 Arabic smoke test PASSED ==="
