# Research: Replacing the Persuasion Index Framework

**Status:** Investigation report — no code changed in this document's scope.
**Date:** 2026-10-17
**Scope:** `Discourse → Persuasion Index` lens (`engine/discourse/service.py`, `engine/discourse/pi_resources.py`, `engine/api/phase2.py:persuasion_health`, `web/src/views/AnalysisView.tsx`, `web/src/components/PersuasionRadar.tsx`).
**Question:** The Persuasive Index lens "requires the user to download components in order to perform the analysis". Can the underlying framework (`persuasion-index==0.3.0`, Wang & Gong 2026) be replaced by another persuasion-discourse framework with quantitative analyses?

---

## 1. Executive summary

**Recommendation: keep `persuasion-index`. No alternative framework satisfies CorpusMind's constraints, and the premise — that components must be downloaded before the analysis can run — is only partially true and entirely fixable in the UI.**

The investigation surveyed every persuasion-analysis framework this project could realistically adopt (packaged or implementable): IBM Project Debater's early-access APIs, the Persuasion-For-Good strategy taxonomy and its classifiers, propaganda/persuasion-technique detection models (SemEval-2020/2021), LIWC, the Anthropic persuasion dataset, emerging academic rhetorical-appeal models on Hugging Face, and LLM-based classification through the engine's existing AI layer. Each fails one or more of the hard constraints listed in §3 — the most common failure being that the "framework" is actually a dataset plus a neural model that must be downloaded at runtime and retrained/finetuned to be trusted, which is precisely the download burden being complained about, at a hundred times the size.

Meanwhile, the current lens is uniquely well-suited to the app: it is a peer-reviewed (EMNLP 2026 main conference), Apache-2.0, fully deterministic implementation of 15 theory-guided dimensions over 55 inspectable sub-features. Its **core scoring runs entirely on the package's bundled lexicons** — in the packaged desktop app, the whole stack (package, lexicons, spaCy model, pandas, wordfreq, VADER) is bundled and the lens works **out of the box with zero downloads**. What triggers the "download components" impression is the resource-health panel, which always shows four license-restricted *optional* refinement files (two concreteness tables, NRC-VAD, LIWC) marked as missing, each with a step-by-step "How to enable" download guide. Those files refine specific sub-features; without them the affected sub-features degrade to neutral baselines and the lens still produces its complete 15-dimension, 0–100 profile.

The practical fix for the perception problem is a presentation change (§6, R2), not a framework swap. Additional zero-download value is available inside the current package: PI's `get_report()` UKP-weighted research profile is not yet surfaced by the UI (§6, R3).

---

## 2. How the lens works today, and what actually gets downloaded

### 2.1 The framework

`persuasion-index` (Gong, Wang, Xu & Mendelsohn, *Persuasion Index: A Theory-Guided Framework for Persuasion Analysis*, EMNLP 2026; arXiv:2606.14580; Apache-2.0) scores English argumentative text over 15 interpretable dimensions grouped by the Aristotelian triad — Logos (Evidence, Logic/Cohesion, Argumentation, Specificity, Opponent's View), Ethos (Authority/Credibility, Politeness, Commitment, Style) and Pathos (Sentiment, Impact, Engagement, Reciprocity, Scarcity/Urgency, Propaganda) — aggregated from 55 transparent sub-features built from lexicons and rule-based detectors. No neural network, no GPU, no API key. The package was evaluated by its authors on four public English argumentation datasets and ships a reproducibility contract (version + lexicon + resource configuration) that matches CorpusMind's citability requirements.

### 2.2 What is bundled vs. downloaded, per deployment shape

| Component | Desktop app (Tauri + PyInstaller) | Source install (`pip install -e .`) |
|---|---|---|
| `persuasion-index` + its bundled lexicons | Bundled (`engine/corpusmind-engine.spec` collects the package and its data files) | Installed automatically (main dependency, pinned `==0.3.0`) |
| `en_core_web_sm` spaCy model (NER sub-features) | Bundled | One command: `python -m spacy download en_core_web_sm` (already required by the engine itself) |
| Brysbaert single-word concreteness (.xlsx) | **Optional manual download** (openly licensed, fetched by `scripts/install_pi_resources.py --all-open`) | Same |
| Multi-word concreteness (.csv, OSF) | **Optional manual download** (open) | Same |
| NRC-VAD v2.1 unigrams | **Optional manual download** (provider forbids redistribution) | Same |
| LIWC dictionary | **Optional manual download** (paid license) | Same |

Hard dependencies of the lens that are always present: `pandas`, `wordfreq` (ships its own data), `vaderSentiment` — all bundled in the desktop build and installed transitively with pip.

### 2.3 What happens without the four optional files

The engine documents this honestly (`discourse/service.py`): NER-dependent sub-features read 0.0 without the spaCy model; LIWC cues and NRC-VAD valence/arousal/dominance fall back to neutral baselines; concreteness uses a 0.5 neutral fallback. **The lens always returns its complete 15-dimension schema** — the health endpoint (`GET /api/v1/discourse/persuasion/health`) reports `resources_required: false` and the UI panel says the affected sub-features "fall back to the package's neutral baselines; scores stay comparable when the same version and resource configuration is used."

### 2.4 Why users perceive a download requirement

Opening the lens shows the `pi-health-card`, which lists all five resources with four marked `○` (missing) — even on the desktop app where the spaCy model is present and only the four license-restricted files can ever be missing. Each missing row expands into "How to enable: 1. Download from the official source … 2. Place the file at … 3. Restart the engine". The panel is rendered *inside the results area*, directly above the radar, so it reads as a setup checklist gating the analysis rather than as optional enrichment metadata. The wording is accurate ("optional"), but the placement and visual weight make it feel mandatory. This — not an actual technical requirement — is what the task description picked up.

---

## 3. Hard constraints for any replacement

Any replacement framework must satisfy all of the following, derived from CorpusMind's architecture and its methodological contract:

1. **Quantitative output per document and corpus-level aggregation.** The Discourse tab's tables, radar, and comparison battery (LL, Log Ratio, %DIFF) consume per-category numeric scores; a purely qualitative or generative tool does not fit the data contract.
2. **Deterministic and reproducible.** Results feed YAML provenance records and methods.pdf exports that peer review can check. Non-deterministic inference undermines the app's core claim.
3. **Local-first, offline-friendly.** The whole product thesis is that analysis runs on the researcher's machine. A framework that must call a cloud API is disqualified; one that requires a one-time model download is tolerable only if that is explicit (cf. the Arabic data pack / Ollama patterns already in the app).
4. **Monologic documents, not dialogues.** Corpus texts are documents (essays, articles, speeches), not persuasion *dialogues* with turn-taking.
5. **License-compatible with an AGPL-3.0 app.** The framework's code must be usable by AGPL code (Apache/MIT/BSD are fine), and any data it needs must either be redistributable or honestly marked optional.
6. **Citable taxonomy.** Every lens names and cites its framework (PERSUASION_CITATION pattern); a framework without a peer-reviewed anchor cannot be reported.
7. **Maintained and packaged.** A single `pip install` (or bundling) must be enough; a research repo without releases is a liability, as the v1.2.8 packaging review demonstrated.

---

## 4. Alternatives surveyed

### 4.1 IBM Project Debater — argument quality / argument mining (early-access APIs)

**What it was:** IBM's Project Debater offered topic-independent argument mining (`arg-mining`), argument quality scoring (`arg-quality`, trained on the DARIA dataset of ~30k rated arguments), and stance classification as free research APIs with Python packages. The quality scores were the field's reference quantitative measure of argument strength.

**Status: not viable.** IBM's Debater Early Access Program was sunset in 2024 and API access was discontinued; the models were never open-sourced. The 2025 ArgMining workshop paper *"Reproducing the Argument Quality Prediction of Project Debater"* (Zelch, Hagen, Stein & Kiesel, Proc. 12th Argument Mining Workshop, 2025) exists precisely because the API is gone — the authors retrained a reproduction from the public DARIA data (r ≈ 0.9 with the original on external data). Using that reproduction would mean hosting or training a neural model: a research artifact, not a maintained package; it fails constraints 3, 6 and 7.

### 4.2 Persuasion-For-Good (Wang et al., ACL 2019) and its strategy classifiers

**What it is:** The canonical persuasion *dialogue* corpus (1,017 donation conversations) annotated with ~10–13 persuader/persuadee strategies (logical appeal, evidence-based appeal, authority appeal, personal credibility, emotion appeal, foot-in-the-door, reciprocity, plea, data/fact presentation, others' approval, …). Baseline and follow-up classifiers exist (CRF/logistic baselines in the paper; RoBERTa-class fine-tunes on Hugging Face, e.g. donation-outcome detectors).

**Why not:** The taxonomy is dialogic — strategies are *moves in a conversation* (e.g., "persuadee reconsideration"), several presuppose a turn sequence, and the classifiers consume dialogue context. CorpusMind analyzes monologic documents (constraint 4). The models are neural transformers requiring torch + runtime downloads (hundreds of MB, GPU-lean but CPU-slow on desktops), the dataset's license permits research use but not bundling into an AGPL desktop app, and there is no maintained packaged framework — only research code. This is the closest *scholarly* alternative and the one to revisit if a document-level persuasion-strategy taxonomy with an operationalized, redistributable lexicon ever appears, but today it does not meet constraints 1, 3, 4 and 7 simultaneously.

### 4.3 Persuasion/propaganda technique detection (SemEval-2020 Task 11; SemEval-2021 Task 6)

**What it is:** Da San Martino et al.'s line of work detects 14–23 named persuasion *techniques* (loaded language, appeal to fear, whataboutism, exaggeration/minimisation, flag-waving, …) in news text and, in the SemEval-2021 multimodal task, in memes. Transformer models are available on Hugging Face (QCRI and participant systems).

**Why not:** The technique taxonomies target *propaganda in news and memes*, not persuasion discourse in general — a corpus of academic writing or learner essays would score near-zero on most techniques, and the label set (flag-waving, whataboutism) does not map onto the rhetorical-strategy reading CorpusMind's users need. The models are neural (downloads, tokenizers, GPU-lean inference), the datasets are research-licensed, and the shared-task systems are unmodelled research code (constraint 7). A future *Vision-suite* complement (meme technique detection over images) is plausible, but that is an addition, not a replacement.

### 4.4 LIWC-22 (Pennebaker et al.)

LIWC remains the reference quantitative tool for psychological language categories and overlaps with PI's LIWC-derived sub-features. It is commercial, its dictionaries may not be redistributed or bundled, and it is a standalone product rather than an embeddable framework. CorpusMind already treats the user's own LIWC license as an optional PI refinement — the correct posture. Fails constraints 5 and 7 (as an in-app replacement).

### 4.5 Anthropic persuasion dataset (Hugging Face, CC-BY-NC-SA-4.0)

Human persuasiveness ratings for ~4k human- and Claude-written arguments on 75 claims, built to study AI persuasion (aligned with Salvi et al. 2025's findings that LLMs can out-persuade humans). It is a dataset for measuring *persuasiveness outcomes*, not an operationalized analysis framework; it cannot score a user's corpus without training a model, and its license forbids commercial use and does not permit bundling. Fails constraints 1, 3, 5, 6, 7.

### 4.6 Emerging academic models (rhetorical appeals, generalizable strategy annotation)

Recent work continues in this space — e.g., *"A Generalizable Rhetorical Strategy Annotation Model"* (arXiv:2510.15081, 2025) trains LLM-annotation pipelines for rhetorical strategies; several Hugging Face models classify rhetorical appeals in narrow domains (parliamentary "group appeals", political speeches). None ships as a package, all are domain-bounded, and most inherit non-commercial data licenses. Promising to watch; none adoptable today (constraints 6, 7).

### 4.7 LLM-based persuasion analysis through the engine's existing AI layer

The engine already runs grounded LLM analyses over eight discourse frameworks (`engine/multimodal/discourse_llm.py`, `reference-data/frameworks/aristotle-rhetoric.yaml`, `toulmin-argumentation.yaml`, …) and the Assistant can classify persuasion strategies on demand. This is *complementary*: an LLM lens gives interpretive depth but is non-deterministic, requires a model provider (local Ollama or opt-in cloud), and cannot anchor the reproducible per-dimension statistics the Discourse tab promises (constraint 2). Not a replacement; already present as a complement.

### 4.8 Already-bundled, zero-download persuasion lenses in CorpusMind

The app already ships three quantitative, citable lenses that cover persuasion-adjacent ground with **no downloads whatsoever**:

- **Cialdini's six influence principles** (v1.2.10): lexical cue sets, profile radar, co-occurrence table — the psychological-principles reading of persuasion.
- **Martin & White (2005) Appraisal**: engagement/attitude/graduation — the linguistic mechanisms of taking up evaluative stance.
- **Hyland (2005) metadiscourse** and **SFG modality/transitivity**: hedges, boosters, stance — the interactional texture of persuasion.

So the "persuasion discourse with quantitative analyses" need is *partially* served inside the app already; the PI lens is the only one providing a unified, theory-guided 15-dimension persuasion profile with per-dimension document scoring.

### 4.9 Comparison matrix

| Framework | Quant. per doc | Deterministic | Local/offline | Monologic | License OK | Redistributable data | Packaged/maintained | Citable |
|---|---|---|---|---|---|---|---|---|
| **persuasion-index 0.3.0 (current)** | ✔ (15 dims, 0–100) | ✔ | ✔ (bundled) | ✔ | ✔ Apache-2.0 | ✔ core; 4 optional files restricted | ✔ PyPI, pinned | ✔ EMNLP 2026 |
| IBM Debater arg-quality | ✔ | ✘ (API gone) | ✘ | ✔ | ✘ (never open) | ✘ | ✘ (sunset 2024) | ✔ |
| Persuasion-For-Good | ▷ (dialogue moves) | ✘ (neural) | ✘ (model download) | ✘ | ▷ research data | ✘ | ✘ research code | ✔ ACL 2019 |
| SemEval-2020/2021 techniques | ▷ (spans) | ✘ (neural) | ✘ (model download) | ▷ | ✘ research data | ✘ | ✘ research code | ✔ |
| LIWC-22 | ✔ | ✔ | ✔ | ✔ | ✘ commercial | ✘ | ✘ (product) | ✔ |
| Anthropic persuasion | ✘ (ratings corpus) | — | — | ✔ | ✘ CC-BY-NC-SA | ✘ | ✘ (dataset) | ✔ |
| LLM lens (existing AI layer) | ▷ | ✘ | ▷ (needs provider) | ✔ | ✔ | n/a | ✔ | ▷ |

---

## 5. Conclusion of the survey

No framework replaces `persuasion-index` on the constraint set. The closest quantitative persuasion framework (Debater's argument quality) is discontinued and was never open; the closest scholarly taxonomy (Persuasion-For-Good) is dialogic and neural; the technique-detection line targets propaganda/memes; LIWC is commercial. Meanwhile PI is the *only* framework in the survey that is simultaneously packaged, deterministic, bundled-offline, license-clean, peer-reviewed, and monologic-document-oriented. Replacing it would strictly worsen every constraint that motivated its adoption in v1.2.7.

---

## 6. Recommendations

- **R1 — Keep the framework (no code change).** `persuasion-index==0.3.0` stays as-is. Its pinning discipline (dimension comparisons are only valid under the same PI version + resource configuration) is already implemented and documented.
- **R2 — Make "optional" visually true (UI-only, small).** In `AnalysisView.tsx`'s `pi-health-card`: (a) title the card "Optional resource refinements" rather than a bare resource list; (b) lead with a one-line status — "The lens runs fully on bundled lexicons. The items below only refine specific sub-features and are never required." (the i18n keys `pi_health_missing_n` / `pi_health_policy` already carry this meaning — it needs prominence, not new translation surface); (c) collapse the per-resource "How to enable" download guides inside the existing `<details>` so the default render is a single quiet row. This directly addresses the misreading reported in this investigation, with two-figure UI churn and no engine change.
- **R3 — Surface PI's UKP-weighted research profile (zero downloads, additive).** The package exposes `get_report()`, a research profile weighted with the UKP argument-quality study weights; the engine currently consumes only `score()`/`score_batch()` dimension means. Exposing it as an additional export (a column set or a per-corpus JSON/PDF appendix) would enrich the lens without any resource files.
- **R4 — Optional neural lens, only behind the existing opt-in download pattern.** If a document-level persuasion-strategy classifier is ever wanted, adopt the app's established pattern (Arabic data pack / Ollama model downloads): explicit user-initiated download, visible size, offline afterwards, honest 503 when absent. Do not bundle torch, and do not make any Discourse lens depend on it.
- **R5 — Keep the source-install story one command.** `pip install -e .` already pulls PI; the spaCy model instruction should stay in the engine README (it is the same model the rest of the engine needs), and `scripts/install_pi_resources.py --all-open` remains the one-liner for the two openly licensed refinements.

---

## 7. Sources

- Gong, L., Wang, Z., Xu, Y., & Mendelsohn, J. (2026). *Persuasion Index: A Theory-Guided Framework for Persuasion Analysis.* EMNLP 2026. arXiv:2606.14580; package: pypi.org/project/persuasion-index (0.3.0, Apache-2.0); code: github.com/krystalgong/Persuasion_Index_Code.
- Zelch, I., Hagen, M., Stein, B., & Kiesel, J. (2025). *Reproducing the Argument Quality Prediction of Project Debater.* Proc. 12th Argument Mining Workshop (ACL), 181–188. Documents the 2024 sunset of the Debater Early Access Program (github.com/IBM/debater-eap-tutorial: "In 2024, the Debater Early Access Program was sunset … API access was discontinued").
- Wang, X., Shi, W., Kim, R., Oh, Y., Yang, S., Zhang, J., & Yu, Z. (2019). *Persuasion for Good.* ACL 2019 (arXiv:1906.06725; aclanthology.org/P19-1566); dataset: github.com/ohyj1002/persuasionforgood; HF models limited to niche fine-tunes (e.g. LACAI/roberta-large-PFG-donation-detection).
- Dimitrov, D., et al. (2021). *SemEval-2021 Task 6: Detection of Persuasion Techniques in Texts and Images.* (propaganda.math.unipd.it/semeval2021task6); Da San Martino, Y., et al. (2020). *SemEval-2020 Task 11.* Both research-licensed, transformer-based.
- Anthropic (2025). *Persuasion dataset*, huggingface.co/datasets/Anthropic/persuasion (CC-BY-NC-SA-4.0).
- Salvi, F., Ribeiro, M. H., Gallotti, R., & West, R. (2025). *On the conversational persuasiveness of GPT-4.* Nature Human Behaviour (background for the Anthropic dataset).
- CorpusMind internal: `docs/USER_GUIDE.md` §8 (lens descriptions, v1.2.9 resource guide), `CHANGELOG.md` v1.2.7–v1.2.9 (lens integration and hardening history), `engine/corpusmind-engine.spec` (bundling), `scripts/install_pi_resources.py` (resource acquisition).
