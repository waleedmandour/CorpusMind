# Reference corpora & wordlists (§13.5)

This directory holds (or symlinks to) bundled reference corpora and wordlists
used by Suite A's keyness (§8.7) and vocabulary (§8.10) analyses.

## License gate — release-blocking

**Nothing may be bundled into a release build unless its license is recorded
in `THIRD_PARTY_LICENSES.md`.** The build refuses to proceed if it finds an
unlicensed asset here (Phase 1 implements this gate as a CI check).

## Layout

```
reference-corpora/
  en/                  # English reference corpora
    README.md          # which corpus, what license, what size
  ar/                  # Arabic reference corpora
    README.md
wordlists/
  en/                  # English wordlists (frequency bands, etc.)
  ar/                  # Arabic wordlists (roots, patterns, lemmas)
```

## Default policy

- **English reference corpus**: ship an open-frequency-corpus-derived approximation
  (e.g. derived from OpenSubtitles or similar CC-licensed data). Do NOT bundle
  the BNC or COCA without confirmed institutional licensing — they are not
  redistributable under permissive terms.
- **Arabic reference corpus**: ship an open Modern Standard Arabic frequency
  list derived from CC-licensed news corpora. Do NOT bundle the Quranic Arabic
  Corpus as the *default* reference — it is a specialized register, not a
  general-reference baseline. Offer it as an optional specialized reference.
- **CEFR wordlists (§8.10)**: ship an open frequency-band-based approximation
  by default. The English Vocabulary Profile (EVP) carries redistribution
  restrictions and MUST NOT be bundled without confirmed rights. Advanced
  users can plug in a licensed CEFR list via Settings → Vocabulary.

## Status (Phase 0)

Phase 0 ships only the directory layout and this README. The actual corpora
land in Phase 1 alongside the keyness / vocabulary features that consume them.
