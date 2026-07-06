# Contributing to CorpusMind

**Authors:** Dr. Waleed Mandour (Sultan Qaboos University, ORCID: 0000-0002-9262-5993) and Prof. Wessam Ibrahim

Thank you for considering a contribution to CorpusMind. This document explains
how to set up a development environment, what we expect from contributions,
and how the review process works.

## Code of conduct

Be excellent to each other. Disagreements about methodology, statistics, or
frameworks are legitimate — personal attacks are not. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)
in spirit.

## Licensing — read this first

CorpusMind is released under **AGPL-3.0-only**. By contributing, you agree
that your contributions will be licensed under the same terms. You retain
your copyright, but you grant the project a license to use, modify, and
redistribute your contributions under AGPL-3.0-only.

We use the [Developer Certificate of Origin](https://developercertificate.org/)
(DCO) process: every commit must be signed off (`git commit -s`), which is
your attestation that you have the right to contribute the code under the
project's license.

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Development environment

### Prerequisites

- Python 3.12+
- Node.js 20+
- [Rust + Cargo](https://rustup.rs/) (only for desktop development)
- [Ollama](https://ollama.com/) or [LM Studio](https://lmstudio.ai/) for local LLM testing

### Set up the engine

```bash
cd engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/   # should pass: 23 tests
```

### Set up the web frontend

```bash
cd web
npm install
npm run dev      # serves on http://localhost:5173
npm run build    # production build, type-checks
```

### Set up the desktop shell (optional, requires Rust)

```bash
cd desktop/src-tauri
cargo check      # verify it compiles
cargo tauri dev  # run the full app (spawns engine sidecar + webview)
```

## Code style

### Python

- We use `ruff` for linting and formatting. The config is in
  `engine/pyproject.toml`.
- `mypy --strict` must pass on changed files.
- All public functions have type annotations.

### TypeScript

- We use `tsc --noEmit` for typechecking (run `npm run typecheck` in `web/`).
- ESLint config is in `web/package.json`.
- We use `clsx` for conditional class names — no template literals for classes.

## What we look for in a PR

### Methodology-touching changes

If your change affects anything documented in [docs/METHODOLOGY.md](../docs/METHODOLOGY.md)
— a formula, a default parameter, a citation — your PR **must**:

1. Update `docs/METHODOLOGY.md` to match the new behavior.
2. Update or add unit tests in `engine/tests/test_measures.py` that verify the
   new behavior against a hand-computed or published worked example.
3. Explain in the PR description why the change is methodologically sound,
   citing the literature if relevant.

This is non-negotiable. A wrong constant in a keyness formula is a silent,
serious validity bug, and the methodology doc + tests are our defense against
it.

### Privacy-touching changes

If your change affects data flow — what gets sent where, when, with what
consent — your PR must:

1. Update `docs/ARCHITECTURE.md` to reflect the new flow.
2. Verify that cloud routing is still opt-in and visibly indicated (§4
   Principle 1, §13.2).
3. Verify that the `CORPUSMIND_CLOUD_DISABLED_HARD` belt-and-suspenders switch
   still works.

### Arabic-touching changes

If your change touches the Arabic module (Phase 3+), verify against the
benchmarks in §17 of the build prompt. Arabic quality is a stated
differentiator, not an afterthought.

### Accessibility

All new UI must meet WCAG 2.1 AA. New interactive components must:

- Be operable by keyboard
- Have visible focus states
- Work in both LTR and RTL (test by flipping `dir` in the View ribbon tab)
- Use semantic HTML where possible (we don't ship ARIA when an element exists)

## Review process

1. Open a PR against `main`.
2. CI must pass (engine tests, web typecheck, web build).
3. A maintainer will review. Methodology-touching changes get extra scrutiny.
4. Once approved, squash-merge with a clean commit message.

## Reporting bugs

Use [GitHub Issues](https://github.com/waleedmandour/CorpusMind/issues).
Please include:

- CorpusMind version (from Settings → Engine)
- Engine version (from `GET /api/v1/version`)
- OS and OS version
- For engine bugs: the relevant snippet from `~/.corpusmind/logs/engine.stderr.log`
- For web bugs: the browser and version, and the browser console output
- For desktop bugs: the relevant snippet from the Tauri log
  (`~/.local/share/CorpusMind/logs/` on Linux,
  `~/Library/Application Support/CorpusMind/logs/` on macOS,
  `%APPDATA%\CorpusMind\logs\` on Windows)

## Roadmap

The phased roadmap is in [docs/AI_AGENT_BUILD_PROMPT.md §16](AI_AGENT_BUILD_PROMPT.md#16-phased-delivery-roadmap).
Phase 0 (foundations) is complete; Phase 1 (Suite A MVP) is next.
