# Framework prompt templates (§11.3)

Each file in this directory is one of the twelve supported theoretical lenses
for Suite B (§9.24). They are **versioned, editable YAML files** — not
hard-coded strings — so researchers can inspect and even propose edits to the
analytic lens being applied to their data.

## Schema

```yaml
name: str              # canonical short name
full_name: str         # full citation form (e.g. "Kress & van Leeuwen (2006)")
version: str           # semantic version of THIS template
framework_family:      # one of: visual_grammar | sfl | cda | mcda | semiotics | metaphor | appraisal | argumentation | rhetoric
categories:            # the framework's analytic categories — surfaced to the model as the structure to use
  - id: str
    label: str
    description: str
output_schema:         # the strict output schema the model must conform to
  claim: str
  evidence_ids: [str]
  confidence: float    # 0–1
  framework: str       # always the template's full_name
guardrails:            # explicit instructions, never to be removed
  - str
example_output:        # one worked example, for in-prompt demonstration
  ...
```

## Status (Phase 0)

Phase 0 ships one template — `kress-van-leeuwen.yaml` — to prove the format.
The remaining eleven land in Phase 4 (Suite B MVP), per the roadmap (§16).

| Template | Phase |
| --- | --- |
| `kress-van-leeuwen.yaml` | 0 (scaffold) |
| `halliday-sfl.yaml` | 4 |
| `fairclough-cda.yaml` | 4 |
| `van-dijk-sca.yaml` | 4 |
| `wodak-dha.yaml` | 4 |
| `machin-mayr-mcda.yaml` | 4 |
| `barthes-semiotics.yaml` | 4 |
| `peirce-semiotics.yaml` | 4 |
| `lakoff-johnson-cmt.yaml` | 4 |
| `martin-white-appraisal.yaml` | 4 |
| `toulmin-argumentation.yaml` | 4 |
| `aristotle-rhetoric.yaml` | 4 |
