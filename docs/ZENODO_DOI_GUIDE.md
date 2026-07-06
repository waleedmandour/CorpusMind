# Registering CorpusMind on Zenodo and Getting a DOI

> This guide walks you through archiving CorpusMind releases on Zenodo and
> minting a permanent, citable DOI for each version. No em dashes are used
> in this document.

---

## Table of Contents

1. [Why Zenodo](#1-why-zenodo)
2. [Prerequisites](#2-prerequisites)
3. [Link Your GitHub Repository to Zenodo](#3-link-your-github-repository-to-zenodo)
4. [Enable Auto-Archival on Release](#4-enable-auto-archival-on-release)
5. [Create Your First Release](#5-create-your-first-release)
6. [Edit the Zenodo Record Metadata](#6-edit-the-zenodo-record-metadata)
7. [Get the DOI](#7-get-the-doi)
8. [Citing the Software in a Paper](#8-citing-the-software-in-a-paper)
9. [Updating to a New Version](#9-updating-to-a-new-version)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Why Zenodo

Zenodo is a free, open-access repository operated by CERN and OpenAIRE. It
mints DataCite DOIs for any digital artifact: software, datasets, reports,
videos. For research software like CorpusMind, archiving on Zenodo gives you:

- A **permanent DOI** for each version, citable in papers and resolvable by
  publishers, journals, and the Software Heritage archive.
- **Long-term preservation** of the source tarball and binary installers,
  independent of GitHub.
- **Integration with GitHub releases** — every GitHub release is automatically
  archived to Zenodo, no manual upload needed.
- **Compliance with funder mandates** (Horizon Europe, NSF, etc.) that require
  research outputs to have a persistent identifier.
- **A Concept DOI** (one DOI for the whole project, always pointing to the
  latest version) plus a **Version DOI** for each individual release.

The Software Heritage archive automatically ingests Zenodo software records,
so archiving on Zenodo gives you a second redundant copy on top of GitHub.

---

## 2. Prerequisites

You need:

1. A **GitHub account** (you already have this — your repo is
   `github.com/waleedmandour/CorpusMind`).
2. An **ORCID iD** (free at orcid.org). Zenodo requires this for the
   "creators" field of the DOI metadata. Register at
   https://orcid.org/register if you do not have one.
3. The **GitHub release workflow must be producing release artifacts**. The
   `.github/workflows/release.yml` file added in this commit handles that:
   push a tag `v0.1.0` and the workflow builds `.dmg`, `.exe`, `.msi`,
   `.AppImage`, `.deb` and attaches them to the GitHub Release.
4. The repository must be **public** (it is). Zenodo can only archive public
   GitHub repositories automatically.

---

## 3. Link Your GitHub Repository to Zenodo

Zenodo talks to GitHub via OAuth. You authorize once, then select which
repositories to enable.

1. Go to **https://zenodo.org** and sign in with your ORCID.
   - If this is your first visit, Zenodo will ask you to confirm your email
     and accept the terms of use.
2. Click your username in the top-right corner, then **Settings**.
3. In the left sidebar, click **GitHub**.
4. Click **Connect GitHub**. You will be redirected to GitHub to authorize
   Zenodo. The permissions requested are:
   - Read access to your user profile
   - Read access to your email addresses
   - Webhook access to repositories you select
5. Click **Authorize zenodo**.
6. You will be returned to the Zenodo GitHub settings page, which now lists
   every public repository under your account.
7. Find **CorpusMind** in the list and flip the toggle switch next to it
   to **ON**.

When you flip the toggle, Zenodo creates a webhook on your GitHub repository.
From now on, every time you publish a GitHub Release, the webhook fires and
Zenodo automatically:
- Downloads the source tarball (`.tar.gz` and `.zip`)
- Downloads every binary asset attached to the release
- Creates a new Zenodo record
- Mints a new version DOI
- Updates the concept DOI to point to the latest version

---

## 4. Enable Auto-Archival on Release

The toggle in step 3.7 above is all you need. There are no further
configuration options on the Zenodo side. But there are two things worth
knowing:

**Draft vs. published records.** By default, Zenodo publishes the record
automatically when a GitHub release is published. If you want to review
the metadata before publishing, go to your Zenodo GitHub settings and change
the toggle from "Publish immediately" to "Create draft". You will then
receive an email each time a release is archived, with a link to the draft
record on Zenodo where you can edit and publish it manually.

**Rate limits.** Zenodo does not enforce a per-repository rate limit, but
GitHub limits webhook deliveries to 250 per hour per repository. For
normal release cadence (one release per week or less) this is never an
issue.

---

## 5. Create Your First Release

Now that Zenodo is linked, create your first release. The release workflow
will produce all the binaries, and Zenodo will archive them.

From your local clone:

```bash
# Make sure main is up to date and pushed
git checkout main
git pull origin main
git push origin main

# Tag the release. Use semantic versioning: vMAJOR.MINOR.PATCH
git tag -a v0.1.0 -m "CorpusMind v0.1.0 — initial public release"

# Push the tag. This triggers the release.yml workflow.
git push origin v0.1.0
```

What happens next, in order:

1. GitHub receives the tag push.
2. The `Release` workflow starts. Four parallel jobs run: macOS arm64,
   macOS Intel, Windows x64, Linux x64. Each takes 10-25 minutes.
3. Each job uploads its artifacts to a GitHub Release that the workflow
   creates automatically (via `softprops/action-gh-release@v2`).
4. When the release is published on GitHub, the Zenodo webhook fires.
5. Zenodo downloads the source tarball + all attached binaries and creates
   a new record.

You can watch the build live at:
`https://github.com/waleedmandour/CorpusMind/actions`

And the published release at:
`https://github.com/waleedmandour/CorpusMind/releases`

---

## 6. Edit the Zenodo Record Metadata

Zenodo pulls basic metadata from your GitHub repository, but you should
enrich it before citing the DOI in a paper. Within 24 hours of the release,
you will receive an email from Zenodo with a link to the new record.

1. Open the record URL from the email, or go to
   `https://zenodo.org` → click your username → **My Dashboard** →
   find the record under **Uploads**.
2. Click **Edit** (the pencil icon in the top-right).
3. Fill in the following fields:

   **Upload type**: Software
   
   **Resource type**: Software

   **DOI**: Leave blank. Zenodo assigns this when you click **Publish**.

   **Communities** (recommended): Add "Software Heritage" and any relevant
   research communities. For CorpusMind, consider:
   - Software Heritage
   - Linguistics
   - Digital Humanities
   - Computational Linguistics

   **Basic information**:
   - **Title**: CorpusMind
   - **Publication date**: (auto-filled from the release date)
   - **Version**: 0.1.0 (auto-filled from the GitHub tag, minus the leading "v")

   **Authors / Creators**: Add yourself (Dr. Waleed Mandour) and
   Prof. Wessam Ibrahim. For each:
   - Click **+ Add creator**
   - Type the name as it should appear in citations
   - Click the name to link it to their ORCID (this is important — it
     ensures citations are correctly attributed)
   - Add affiliations: "Sultan Qaboos University" for Dr. Mandour

   **Description**: A 2-3 paragraph abstract. Use the project's
   shortDescription from tauri.conf.json as a starting point:

   > CorpusMind is a local-first, AI-native research environment for corpus
   > linguistics and multimodal discourse analysis. It lets a linguist go
   > from raw texts and images to publication-ready quantitative and
   > qualitative analysis without writing code, without sending unpublished
   > data to a third-party server unless they explicitly choose to, and
   > without losing the methodological transparency that peer review demands.
   >
   > The desktop application bundles a FastAPI engine, a Tauri 2 shell, and
   > an installable PWA, supporting English and Arabic text analysis, vision
   > pipelines for multimodal discourse, and a pluggable AI assistant that
   > can connect to local (Ollama, LM Studio) or remote (OpenAI, Anthropic)
   > model providers.

   **Keywords**: Add at least 5. Suggested:
   - corpus linguistics
   - discourse analysis
   - multimodal analysis
   - Arabic NLP
   - visual grammar
   - critical discourse analysis
   - local-first software
   - research software

   **License**: GNU Affero General Public License v3.0 only (AGPL-3.0-only)
   Zenodo will auto-detect this from the LICENSE file, but verify.

   **Funding**: If CorpusMind was developed under a grant (e.g. Sultan
   Qaboos University internal grant, Horizon Europe, NSF), add the grant
   number. This is required by most funders for compliance.

   **Related identifiers**: Add:
   - Identifier: `https://github.com/waleedmandour/CorpusMind`
     Relation: isSupplementTo (or isSourceRepositoryFor)
   - Identifier: `https://doi.org/10.5281/zenodo.<your-concept-doi>`
     (after first publication, link to the Concept DOI as "isVersionOf")

4. Click **Save** at the bottom.

---

## 7. Get the DOI

There are actually two DOIs:

### 7.1 Concept DOI (one per project, never changes)

This represents the entire project, regardless of version. Always cite this
when you want to reference CorpusMind in general (not a specific version).
The Concept DOI automatically resolves to the latest published version.

Format: `10.5281/zenodo.XXXXXXX` (where XXXXXXX is a 7-digit number)

You can find it at the top of any version's record page on Zenodo, in the
"Cite as" box, OR by going to your Zenodo dashboard and looking at the
"Concept" entry for the CorpusMind upload.

### 7.2 Version DOI (one per release)

Each release gets its own Version DOI. Use this when you need to cite a
specific version of CorpusMind (e.g. "we used CorpusMind v0.1.0").

Format: `10.5281/zenodo.YYYYYYY` (different 7-digit number per version)

Find it on the record page for that specific version, in the "Cite as" box
or in the right sidebar under "DOI".

### 7.3 Resolving a DOI

To resolve any DOI, prepend `https://doi.org/`. For example:
`https://doi.org/10.5281/zenodo.YYYYYYY`

---

## 8. Citing the Software in a Paper

Once you have the DOI, you can cite CorpusMind in a manuscript. Use the
Version DOI for the version you actually used, and the Concept DOI for
general references.

### 8.1 APA Style

> Mandour, W., & Ibrahim, W. (2026). CorpusMind (Version 0.1.0)
> [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.YYYYYYY

### 8.2 Chicago Style

> Mandour, Waleed, and Wessam Ibrahim. 2026. "CorpusMind." Version 0.1.0.
> Zenodo. https://doi.org/10.5281/zenodo.YYYYYYY.

### 8.3 IEEE Style

> W. Mandour and W. Ibrahim, "CorpusMind, version 0.1.0," Jan. 2026.
> doi: 10.5281/zenodo.YYYYYYY.

### 8.4 BibTeX

```bibtex
@software{mandour_2026_corpusmind,
  author       = {Mandour, Waleed and Ibrahim, Wessam},
  title        = {{CorpusMind: Local-first, AI-native research environment
                   for corpus linguistics and multimodal discourse analysis}},
  month        = jan,
  year         = 2026,
  version      = {0.1.0},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.YYYYYYY},
  url          = {https://doi.org/10.5281/zenodo.YYYYYYY}
}
```

### 8.5 Add a CITATION.cff File

Zenodo can read a `CITATION.cff` file in your repository root and use it
to auto-generate the citation metadata. Create one:

```yaml
# CITATION.cff
cff-version: 1.2.0
message: "If you use CorpusMind in your research, please cite it as below."
title: "CorpusMind: Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis"
abstract: "CorpusMind lets a linguist go from raw texts and images to publication-ready quantitative and qualitative analysis without writing code, without sending unpublished data to a third-party server unless they explicitly choose to, and without losing the methodological transparency that peer review demands."
authors:
  - family-names: Mandour
    given-names: Waleed
    affiliation: "Sultan Qaboos University"
    orcid: "https://orcid.org/0000-0000-0000-0000"
  - family-names: Ibrahim
    given-names: Wessam
keywords:
  - corpus linguistics
  - discourse analysis
  - multimodal analysis
  - Arabic NLP
  - visual grammar
license: AGPL-3.0-only
repository-code: "https://github.com/waleedmandour/CorpusMind"
version: 0.1.0
date-released: 2026-01-07
preferred-citation:
  type: software
  authors:
    - family-names: Mandour
      given-names: Waleed
    - family-names: Ibrahim
      given-names: Wessam
  title: "CorpusMind"
  year: 2026
```

Replace the ORCID with your actual ORCID iD. When you create the next
GitHub release, Zenodo will read this file and pre-fill the metadata.

---

## 9. Updating to a New Version

When you release v0.2.0, v1.0.0, etc.:

1. Update the version in:
   - `desktop/src-tauri/tauri.conf.json` (the `"version"` field)
   - `engine/pyproject.toml` (`version = "..."`)
   - `web/package.json` (`"version"`)
   - `CITATION.cff` (`version` and `date-released`)

2. Commit and push to main:
   ```bash
   git add -A
   git commit -m "Release v0.2.0"
   git push origin main
   ```

3. Tag and push:
   ```bash
   git tag -a v0.2.0 -m "CorpusMind v0.2.0 — see CHANGELOG.md"
   git push origin v0.2.0
   ```

4. The release workflow builds new binaries and creates a new GitHub Release.

5. Zenodo's webhook fires. Because this is a new version of an existing
   repository, Zenodo creates a **new version of the existing record** (not
   a separate record). The Concept DOI stays the same; a new Version DOI
   is minted.

6. Edit the new version's metadata on Zenodo (the workflow does NOT copy
   metadata across versions — you need to re-enter or use the "Save as
   new version" feature on the previous record).

If you used a `CITATION.cff` file, Zenodo will import the updated metadata
automatically, so step 6 becomes a quick review rather than a full re-entry.

---

## 10. Troubleshooting

### The Zenodo webhook did not fire

Check the webhook delivery log on GitHub:
`https://github.com/waleedmandour/CorpusMind/settings/hooks`
You should see a "zenodo" webhook. Click it to see delivery history. If the
last delivery failed, click "Redeliver".

### The Zenodo record is missing binaries

Zenodo only archives assets that were attached to the GitHub Release at the
moment the webhook fired. If you added assets after the release was
published, Zenodo will not pick them up automatically. To fix:
1. Go to Zenodo → your record → Edit → Files
2. Click "Upload files" and add the missing binaries manually

### I made a mistake in the published record

Published Zenodo records can be edited at any time (the DOI does not
change). Click "Edit" on the record page, fix the metadata, and click
"Save". The DOI will continue to resolve to the corrected record.

If you need to retract the entire record, you can mark it as "Reserved"
(not findable in search) but you cannot delete it — Zenodo is a permanent
archive.

### I want to archive an older version that I never released

You cannot retroactively mint a Version DOI for a commit that was never
tagged. The correct approach is to:
1. Create a new GitHub Release with the old version number
2. Attach the source tarball (you can build one with `git archive`)
3. Let Zenodo archive it as usual

### The build workflow fails

Check the workflow run logs at:
`https://github.com/waleedmandour/CorpusMind/actions`
Common failures:
- Missing Apple signing secrets → the build still succeeds, the .dmg is
  just unsigned. Users get the "unidentified developer" warning.
- PyInstaller missing a hidden import → add it to `_hidden_imports` in
  `engine/corpusmind-engine.spec` and rebuild.
- Tauri sidecar not found → make sure the build script copied the binary
  to `desktop/src-tauri/binaries/corpusmind-engine-<triple>` before
  running `cargo tauri build`.

### I want a DOI before the first release (preprint)

You can create a manual Zenodo upload (not linked to GitHub) and mint a
DOI for a work-in-progress version. Go to `https://zenodo.org/deposit/new`,
upload your source as a .zip, fill in metadata, and click "Publish". This
gives you a DOI immediately. When you later create the GitHub-linked
release, you will have two separate DOIs — you can link them via
"Related identifiers" on each record (isVersionOf / isNewVersionOf).
