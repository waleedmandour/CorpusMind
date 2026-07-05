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

### Arabic NLP (Phase 3+, optional install via `pip install -e ".[arabic]"`)

| Package | License | Purpose |
| --- | --- | --- |
| (future) [CAMeL Tools](https://camel-tools.readthedocs.io/) | MIT | Arabic morphology, NER, sentiment, dialect ID |
| (future) [SinaTools](https://github.com/SinaTools/) | Apache-2.0 | Arabic NLP toolkit |
| (future) [Farasa](https://farasa.qcri.org/) | MIT | Arabic segmentation / POS / lemmatization |

### Statistics

| Package | License | Purpose |
| --- | --- | --- |
| [numpy](https://numpy.org/) | BSD-3-Clause | Numerical computing |
| [scipy](https://scipy.org/) | BSD-3-Clause | Scientific computing |
| [statsmodels](https://www.statsmodels.org/) | BSD-3-Clause | Statistical models |
| [pingouin](https://pingouin-stats.org/) | Apache-2.0 | Statistical tests (§9.21) |

### Storage

| Package | License | Purpose |
| --- | --- | --- |
| [sqlalchemy](https://www.sqlalchemy.org/) | MIT | SQL ORM |
| [aiosqlite](https://aiosqlite.omnilib.dev/) | MIT | Async SQLite driver |

### Vision (Phase 4+, optional install via `pip install -e ".[vision]"`)

| Package | License | Purpose |
| --- | --- | --- |
| (future) [opencv-python](https://opencv.org/) | Apache-2.0 | Computer vision |
| [pillow](https://python-pillow.org/) | MIT-CMU | Image processing |

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
