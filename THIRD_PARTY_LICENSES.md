# Third-Party Licenses

This document tracks the licenses of every piece of software, model, wordlist,
and reference corpus that CorpusMind bundles, depends on, or invokes at
runtime. **Nothing may be bundled into a release build unless its license is
recorded here.** The build (Phase 1+) refuses to proceed if it finds an
unlicensed asset.

## Project license

CorpusMind itself is released under **AGPL-3.0-only**. See [LICENSE](LICENSE).

## License compatibility rationale

The AGPL-3.0 is a strong copyleft license. It is compatible with:

- **Permissive licenses** (MIT, BSD-2/3-Clause, Apache-2.0, ISC, MPL-2.0) —
  CorpusMind can bundle and link these without issue. The AGPL's copyleft
  applies to the *combination*, not the upstream permissive code.
- **Weak copyleft** (LGPL-2.1/3.0, MPL-2.0) — linkable as long as the
  weak-copyleft code remains replaceable by the user (which it is, in our
  setup).
- **Strong copyleft** (GPL-2.0/3.0, AGPL-3.0) — combinable only if the
  resulting combination is also AGPL-compatible. Our own AGPL-3.0 choice
  is the most permissive strong-copyleft option in this family.

The AGPL-3.0 is **incompatible** with:
- **GPL-2.0-only** code (rare in modern NLP/CV stacks)
- Code with **no license** (treat as all-rights-reserved — cannot bundle)
- Code with **no-commercial-use** clauses (cannot bundle in any context)

If a dependency's license changes to one of the above, it must be removed
from CorpusMind before the next release.

---

## Engine dependencies (Python)

The full dependency list is in [`engine/pyproject.toml`](engine/pyproject.toml).
Licenses below are as declared in each package's metadata at the time of the
Phase 0 release.

### Core framework

| Package | License | Purpose |
| --- | --- | --- |
| [fastapi](https://fastapi.tiangolo.com/) | MIT | Web framework |
| [uvicorn](https://www.uvicorn.org/) | BSD-3-Clause | ASGI server |
| [pydantic](https://docs.pydantic.dev/) | MIT | Data validation |
| [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | MIT | Settings management |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause | HTTP client for model providers |
| [anyio](https://anyio.readthedocs.io/) | MIT | Async compatibility layer |
| [tenacity](https://github.com/jd/tenacity) | Apache-2.0 | Retry logic |
| [structlog](https://www.structlog.org/) | MIT | Structured logging |

### NLP

| Package | License | Purpose |
| --- | --- | --- |
| [spaCy](https://spacy.io/) | MIT | General multilingual NLP |
| (future) [Stanza](https://stanfordnlp.github.io/stanza/) | Apache-2.0 | Multilingual NLP (Phase 1) |
| (future) [Trankit](https://github.com/nlp-uoregon/trankit) | Apache-2.0 | Multilingual NLP (Phase 1) |

### Arabic NLP (Phase 3, optional install via `pip install -e ".[arabic]"`)

| Package | License | Purpose |
| --- | --- | --- |
| [CAMeL Tools](https://camel-tools.readthedocs.io/) | MIT (package code, verified from the 1.6.0 source headers) + GPL-2.0-only (calima-msa-r13 morphology DB; verified 2026-10-07 from the LICENSE file shipped inside the DB - Version 2 only, no "or later") + CC BY 4.0 (Gulf/Levantine DBs) | Arabic morphology, NER, sentiment, dialect ID. **Note:** the morphology databases have their own licenses — calima-msa-r13 is GPL-2.0-only (derived from AraMorph 1.2.1, LDC), calima-glf-01 and calima-lev-01 are CC BY 4.0. See the data-pack row below for exactly what is and is not redistributed. |
| (future) [SinaTools](https://github.com/SinaTools/) | Apache-2.0 | Arabic NLP toolkit |
| (future) [Farasa](https://farasa.qcri.org/) | MIT | Arabic segmentation / POS / lemmatization |
| `pyrsistent` | MIT | Required by CAMeL Tools |
| `muddler` | MIT | Required by CAMeL Tools (database unpacking) |
| `cachetools` | MIT | Required by CAMeL Tools (analyzer caching) |
| `emoji` | MIT | Required by CAMeL Tools (charset detection) |
| `camel-kenlm`, `editdistance`, `dill`, `docopt`, `tabulate`, `future` | `editdistance` MIT; `docopt` MIT; `future` MIT; `tabulate` MIT; `dill` BSD-3-Clause; `camel-kenlm`: license NOT stated in the wheel metadata (verify against github.com/CAMeL-Lab/camel-kenlm before release) | Required by CAMeL Tools 1.6.0 (license fields read from the installed wheel metadata, 2026-10-07). NOTE: camel-tools 1.6.0 also declares `torch` and `transformers` as dependencies (for its neural components); neither is used by CorpusMind's morphology/dialect paths and NEITHER is bundled (excluded in the PyInstaller spec). |
| CAMeL Tools data pack (`calima-msa-r13` + `calima-egy-r13` morphology DBs, `calima-glf-01` + `calima-lev-01` dialect DBs, `dialectid-model6` dialect-ID model) | `calima-msa-r13` and `calima-egy-r13`: **GPL-2.0-only** - VERIFIED 2026-10-07 (msa) and 2026-10-08 (egy, by reading the LICENSE file shipped inside the downloaded pack): the grant says "GNU GENERAL PUBLIC LICENSE Version 2" and "as published by the Free Software Foundation version 2", with **no "or later"** clause anywhere in the grant; the msa DB is derived from AraMorph 1.2.1 (LDC) plus QAMUS LLC / University of Pennsylvania / Jon Dehdari portions. `calima-glf-01` and `calima-lev-01`: **CC BY 4.0** (verified 2026-10-08 from the Creative Commons Attribution LICENSE file shipped inside each downloaded pack). `dialectid-model6`: **MIT** per the camel_tools data catalogue (`catalogue-1.6.json`, retrieved live by `camel_data` on 2026-10-07); no licence file ships inside the model pack itself. | **What IS redistributed:** by default, NOTHING from this data pack ships with the desktop bundle - the pack is GPL-2.0-only data, so the default distribution avoids those obligations entirely and an unprovisioned app answers HTTP 503 with an install hint. The optional in-app **Arabic data pack installer** (Settings, or the button in the 503 card) downloads the five pinned packages (v1.2.11: the MSA morphology DB, the Egyptian/Gulf/Levantine dialect DBs, and the dialect-ID model) directly from CAMeL Lab's official GitHub releases (`github.com/CAMeL-Lab/camel-tools-data`), verifies size + SHA256 against digests pinned from the observed release assets, and installs them into the user's own data directory (`~/.camel_tools` unless `CAMELTOOLS_DATA` is set). That is a user-initiated download from the upstream source, not a redistribution by CorpusMind. Maintainers CAN produce a data-bundled build by setting `CORPUSMIND_BUNDLE_CAMEL_DATA=1` at build time; such a build redistributes the datasets above and must therefore satisfy GPL-2.0-only obligations for the GPL-2.0-only DBs it bundles (keep the bundled LICENSE files, provide the corresponding source, i.e. the DBs themselves, and carry these notices). **What is NOT redistributed (in any build):** torch / transformers (excluded from the bundle; the morphology and dialect-ID paths are non-neural), all other catalogue packages (NER, sentiment, disambiguation models, `morphology-db-msa-s31`), and the `dialectid` ARPA language-model files are only present as part of `dialectid-model6` when the user installs that package. |

### Statistics

| Package | License | Purpose |
| --- | --- | --- |
| [numpy](https://numpy.org/) | BSD-3-Clause | Numerical computing |
| [scipy](https://scipy.org/) | BSD-3-Clause | Scientific computing |

### Storage

| Package | License | Purpose |
| --- | --- | --- |
| [sqlalchemy](https://www.sqlalchemy.org/) | MIT | SQL ORM |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | MIT | Async SQLite driver |

### Engine runtime utilities (added in Issue 25 sync, v1.1.0)

| Package | License | Purpose |
| --- | --- | --- |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | MIT | HTML parsing (archive ingestion) |
| [lxml](https://lxml.de/) | BSD-3-Clause | XML/HTML parsing |
| [charset-normalizer](https://github.com/Ousret/charset_normalizer) | MIT | Text encoding detection |
| [langdetect](https://github.com/Mimino667/langdetect) | Apache-2.0 | Language detection |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | DOCX ingestion/export |
| [openpyxl](https://openpyxl.readthedocs.io/) | MIT | XLSX export |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause | PDF ingestion |
| [reportlab](https://www.reportlab.com/) | BSD-3-Clause | PDF export |
| [websockets](https://websockets.readthedocs.io/) | BSD-3-Clause | WebSocket support (uvicorn) |
| [python-multipart](https://github.com/kludex/python-multipart) | Apache-2.0 | Multipart upload parsing |
| [openapi-core](https://github.com/openapi-generators/openapi-core) | BSD-3-Clause | OpenAPI validation (tests) |
| [cryptography](https://cryptography.io/) | Apache-2.0 OR BSD-3-Clause | AES-256-GCM at-rest encryption |
| [tenacity](https://tenacity.readthedocs.io/) | Apache-2.0 | Retry logic |
| [structlog](https://www.structlog.org/) | MIT/Apache-2.0 | Structured logging |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause | Async HTTP client (providers) |
| [camel-tools](https://camel.abudhabi.nyu.edu/) | Apache-2.0 | Arabic NLP toolkit |

### Vision (Phase 4+, optional install via `pip install -e ".[vision]"`)

| Package | License | Purpose |
| --- | --- | --- |
| [opencv-python](https://opencv.org/) | Apache-2.0 | Computer vision (release build dependency) |
| [pillow](https://python-pillow.org/) | MIT-CMU | Image processing |

### Persuasion Index (v1.2.7, optional install via `pip install -e ".[persuasion]"`)

| Package | License | Purpose |
| --- | --- | --- |
| [persuasion-index](https://github.com/krystalgong/Persuasion_Index_Code) | Apache-2.0 | 15-dimension persuasive-language scoring (Wang & Gong 2026, EMNLP). Pinned main dependency since v1.2.8 — the packaged engine ships the lens. |
| pandas, wordfreq, vaderSentiment | BSD-3 / CC-BY-SA-style data terms / MIT | Transitive dependencies of persuasion-index (see upstream THIRD_PARTY_RESOURCES.md for its optional LIWC/concreteness/NRC-VAD resources, which CorpusMind does NOT bundle) |

### Student Mode classroom stack (v1.2.9)

| Package | License | Purpose |
| --- | --- | --- |
| [Caddy](https://caddyserver.com/) (pinned 2.10.0) | Apache-2.0 | Classroom reverse proxy + static PWA server for Student Mode (teacher-as-server). Fetched per-build by `scripts/fetch_caddy.py` and verified against the release's official sha512 checksums; bundled inside the engine's PyInstaller onedir. Its local CA (`tls internal`) issues the classroom HTTPS certificate. |

---

## Web dependencies (Node.js)

The full dependency list is in [`web/package.json`](web/package.json).

### Runtime

| Package | License | Purpose |
| --- | --- | --- |
| [react](https://react.dev/) | MIT | UI library |
| [react-dom](https://react.dev/) | MIT | React DOM renderer |
| [@tanstack/react-query](https://tanstack.com/query/latest) | MIT | Server state |
| [zustand](https://zustand-demo.pmnd.rs/) | MIT | Client state |
| [clsx](https://github.com/lukeed/clsx) | MIT | Conditional class names |

### Build-time / dev

| Package | License | Purpose |
| --- | --- | --- |
| [vite](https://vitejs.dev/) | MIT | Build tool |
| [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react) | MIT | React plugin |
| [typescript](https://www.typescriptlang.org/) | Apache-2.0 | Type system |
| [vite-plugin-pwa](https://vite-pwa-org.netlify.app/) | MIT | PWA support |
| [qrcode](https://github.com/soldair/node-qrcode) (web) | MIT | Student Mode classroom QR codes (join URL + certificate link) |
| [eslint](https://eslint.org/) | MIT | Linter |
| [@typescript-eslint/*](https://typescript-eslint.io/) | MIT | TypeScript ESLint plugin |
| [eslint-plugin-react-hooks](https://www.npmjs.com/package/eslint-plugin-react-hooks) | MIT | React hooks linting |
| [eslint-plugin-react-refresh](https://github.com/ArnaudBarre/eslint-plugin-react-refresh) | MIT | React Refresh linting |

---

## Desktop dependencies (Rust / Cargo)

The full dependency list is in [`desktop/src-tauri/Cargo.toml`](desktop/src-tauri/Cargo.toml).

| Crate | License | Purpose |
| --- | --- | --- |
| [tauri](https://tauri.app/) | Apache-2.0 OR MIT | Desktop application framework |
| [tauri-plugin-shell](https://v2.tauri.app/plugin/shell/) | Apache-2.0 OR MIT | Shell / sidecar management |
| [tauri-plugin-dialog](https://v2.tauri.app/plugin/dialog/) | Apache-2.0 OR MIT | Native dialogs |
| [tauri-plugin-fs](https://v2.tauri.app/plugin/fs/) | Apache-2.0 OR MIT | File system access |
| [tauri-plugin-http](https://v2.tauri.app/plugin/http/) | Apache-2.0 OR MIT | HTTP fetch from webview |
| [serde](https://serde.rs/) | Apache-2.0 OR MIT | Serialization |
| [serde_json](https://docs.rs/serde_json/) | Apache-2.0 OR MIT | JSON serialization |
| [log](https://docs.rs/log/) | Apache-2.0 OR MIT | Logging facade |
| [env_logger](https://docs.rs/env_logger/) | Apache-2.0 OR MIT | Log implementation |
| [thiserror](https://docs.rs/thiserror/) | Apache-2.0 OR MIT | Error derive macro |
| [tokio](https://tokio.rs/) | MIT | Async runtime |
| [reqwest](https://docs.rs/reqwest/) | Apache-2.0 OR MIT | HTTP client (blocking, for sidecar health-poll) |

---

## Local LLM runtimes (NOT bundled, user-installed)

These are not bundled with CorpusMind — the user installs them separately.
We list them here for completeness.

| Runtime | License | Notes |
| --- | --- | --- |
| [Ollama](https://ollama.com/) | MIT | Sidecar-able; supports OpenAI-compatible `/v1` |
| [LM Studio](https://lmstudio.ai/) | proprietary (free for personal/research use) | OpenAI-compatible server on `:1234/v1` |

---

## Models (NOT bundled, user-pulled via Ollama / LM Studio)

CorpusMind never bundles model weights. Users pull models via Ollama's or
LM Studio's own mechanisms. Each model carries its own license — the user
must accept it via the runtime's UI; CorpusMind does not intervene.

The default Phase 0 model recommendation (`llama3.2:3b`) is licensed under
the Llama 3.2 Community License, which has use-case restrictions for
>700M monthly active users. Researchers using CorpusMind for normal
academic work are well within the license's terms.

| Model | License | Notes |
| --- | --- | --- |
| **Gemma 4** (Google DeepMind, 2026) — `gemma4:e2b` / `:e4b` / `:12b` / `:26b` / `:31b` via Ollama | **Apache-2.0** (verified on the official model card, ai.google.dev/gemma/docs/core/model_card_4, retrieved 2026-10-07) | User-pulled via Ollama, never bundled. Catalogue entry added in v1.2.11 as a recommended grounded-assistant model for the new corpus languages (the model card documents "over 140 languages" pre-trained; the per-language coverage of ur/hi/fa is not enumerated in official docs, so no stronger claim is made). Its Apache-2.0 terms differ from CorpusMind's AGPL-3.0 — pulling and running it under your own Ollama instance is a separate act from redistributing CorpusMind. |

---

## v1.2.11 additions (language support)

| Component | License | How it ships / notes |
| --- | --- | --- |
| [Stanza](https://github.com/stanfordnlp/stanza) (tested with 1.15.0) | Apache-2.0 | OPTIONAL Python dependency (`[urdu-hindi-farsi]` extra) for ur/hi/fa POS/lemma/dependency parse. NOT bundled in the packaged app (its torch dependency is excluded by the PyInstaller spec); dev/desktop users install it separately and the models download on first use to `~/.cache/stanza`. The engine degrades to spaCy blank tokenization + bundled stopwords when absent, and the capability registry says so. |
| Stanza UD models for ur/hi/fa | data licensed per Stanza repo (models trained on UD treebanks, CC BY-SA 4.0 unless stated otherwise on the model card) | Download-on-demand by Stanza itself; never bundled. |
| [wordfreq](https://github.com/rspeer/wordfreq) 3.1.1 (Python package) | Apache-2.0 | Already a transitive dependency (persuasion-index); used in v1.2.11 to derive the ur/hi/fa keyness baselines. |
| wordfreq bundled frequency DATA (source of `urdu-freq-top1000.tsv`, `hindi-freq-top1000.tsv`, `farsi-freq-top1000.tsv`) | **CC BY-SA 4.0** (per the wordfreq 3.1.1 distribution statement: "it includes data files that may be redistributed under a Creative Commons Attribution-ShareAlike 4.0 license"; sources: Wikipedia, Leeds Internet Corpus, OPUS OpenSubtitles 2018, ParaCrawl, Google Books Ngrams) | The derived top-1000 TSVs ARE bundled under `reference-data/reference-corpora/{ur,hi,fa}/`, SHA-256-pinned in the reference-corpus registry, with attribution in each file header. Share-alike: treat the derived lists as CC BY-SA 4.0. |
| Noto Sans Devanagari (v2.007, hinted) | SIL Open Font License 1.1 | Bundled as web fonts (`web/public/fonts/`, license file alongside). |
| Noto Nastaliq Urdu (variable) | SIL Open Font License 1.1 | Bundled as a web font; the Nastaliq-capable Urdu face. |
| Noto Sans Arabic (variable) | SIL Open Font License 1.1 | Bundled as a web font; local Arabic/Persian fallback (offline-first). |
| [Amiri](https://github.com/aliftype/amiri) 1.000 | SIL Open Font License 1.1 | NOT bundled in the app; used only by `scripts/generate_arabic_guide_pdf.py` to render the Arabic User Guide PDF. |

---

## Reference corpora and wordlists (NOT bundled in Phase 0)

Phase 0 ships no reference corpora or wordlists. Phase 1 will add open
frequency-derived approximations. **The following may NOT be bundled
without confirmed rights:**

- **BNC** (British National Corpus) — restricted; requires institutional license.
- **COCA** (Corpus of Contemporary American English) — restricted; not redistributable.
- **EVP** (English Vocabulary Profile) — redistribution restrictions per §8.10.
- **Quranic Arabic Corpus** — usable as a specialized reference, not a general baseline.

Open-licensed alternatives will be sourced for Phase 1, with their licenses
recorded in this document before the build proceeds.

---

## Cloud API services (opt-in, NOT bundled)

### Google Gemini API

- **Used for:** Smart Troubleshooting error interpretation (optional)
- **What data is sent:** Error text only (error message, HTTP status code,
  endpoint path, and what the user was doing). **No corpus data is ever sent.**
- **Off by default:** The Gemini integration is disabled unless the user
  explicitly enters an API key in Settings or sets the
  `CORPUSMIND_GEMINI_API_KEY` environment variable.
- **API key storage:** If entered via the UI, the key is stored in-memory
  in the engine process only (never written to disk). If set via env var,
  it follows the user's environment configuration.
- **Google's terms:** https://ai.google.dev/terms
- **Privacy:** https://ai.google.dev/privacy
- **License:** Google Generative AI API is governed by Google's Terms of
  Service. The user is responsible for complying with Google's terms when
  using the Smart Troubleshooting interpretation feature.

---

## Updating this file

When adding a new dependency (Python, Node, or Rust):

1. Add the package to the appropriate table above.
2. Verify the license is compatible with AGPL-3.0-only (see "License
   compatibility rationale" above).
3. If the license has any special requirement (attribution, notice file,
   share-alike), record it here.
4. If you cannot verify the license, **do not add the dependency**. Open an
   issue instead.

When bundling a model, wordlist, or reference corpus:

1. Confirm redistribution rights in writing.
2. Add an entry in the relevant section above.
3. Update the build's license-gate check (Phase 1) to verify the asset's
   presence in this document.

This file is the project's legal defense. Treat it as such.
