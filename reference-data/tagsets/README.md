# Tagset data (semantic: USAS top-level lexicons)

Compact lexicons powering CorpusMind's **USAS** semantic tagset
(`reference-data/tagsets/usas-{en,ar}-top.tsv`).

## Provenance

Derived from the UCREL **Multilingual-USAS** lexicon collection:
https://github.com/UCREL/Multilingual-USAS

- `English/semantic_lexicon_en.tsv` → `usas-en-top.tsv` (46,147 lemmas)
- `Arabic/semantic_lexicon_arabic.tsv` → `usas-ar-top.tsv` (33,213 lemmas)

Processing (`scripts/build_usas_lexicons.py`): for each lemma, the first
semantic tag is taken and reduced to its **top-level letter** of the USAS
hierarchy (A–Z). Arabic lemmas are diacritics-stripped to match CAMeL
lemmas at query time. Duplicate lemmas keep their first (most common)
reading.

## Format

TSV, one row per lemma:

```
lemma<TAB>top<TAB>first_tag
the  Z  Z5
```

## License — CC BY-NC-SA 4.0

The upstream Multilingual-USAS lexicons are released under
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0
International** (see `LICENSE-USAS-CC-BY-NC-SA-4.0.txt`). These derived
files are distributed under the same terms:

- **Attribution** — cite the USAS taxonomy and the Multilingual-USAS
  resource (Bibliography below) in any publication using semantic tags
  computed by CorpusMind.
- **NonCommercial** — the lexicon data may not be used for commercial
  purposes. The corpus tags computed at analysis time are yours; the
  lexicon itself remains NC-licensed.
- **ShareAlike** — derivative lexicons must carry the same license.

## Bibliography

- Archer, D., Wilson, A., & Rayson, P. (2002). *Introduction to the USAS
  Category System*. UCREL, Lancaster University.
  https://ucrel.lancs.ac.uk/usas/
- Rayson, P., Archer, D., Baron, A., Culpeper, J., & Smith, N. (2007).
  The Tagged Lancaster-Oslo/Bergen Corpus and the UCREL Semantic
  Analysis System. *Beyond the Wonderland IV*.
