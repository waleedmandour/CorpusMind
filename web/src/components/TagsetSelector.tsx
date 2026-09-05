/**
 * TagsetSelector (v1.2.0, Issue 4) — per-corpus tagset choice.
 *
 * Shown in the "Your Corpus" window: the user picks the tagset used for
 * POS-style analysis — grammatical (UD UPOS, Penn Treebank, CLAWS-7 for
 * English; UD UPOS or the native CAMeL/Calima tags for Arabic) or semantic
 * (USAS top-level, experimental). The choice is persisted per corpus
 * (PATCH /corpora/{cid}/tagset → pipeline_recipe) and becomes the default
 * tagset in the analysis panels.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const TAGSET_LABELS: Record<string, string> = {
  upos: "UD UPOS (universal)",
  ptb: "Penn Treebank",
  claws7: "CLAWS-7 (BNC standard)",
  calima: "CAMeL / Calima (native)",
  usas: "USAS semantic (experimental)",
};

const GRAMMATICAL_EN = ["upos", "ptb", "claws7"];
const GRAMMATICAL_AR = ["upos", "calima"];
const SEMANTIC = ["usas"];

const TAGSET_HINTS: Record<string, string> = {
  upos: "The 17-tag universal inventory — language-independent default.",
  ptb: "The classic Penn Treebank tags (NN, VBD, IN, ...) — English treebank standard.",
  claws7: "The ~150-tag BNC/Sketch Engine tagset, mapped from Penn Treebank (approximation).",
  calima: "Native CAMeL Tools morphological tags (noun, verb, adj, prep, ...).",
  usas: "UCREL Semantic Analysis System top-level categories (A=abstract ... Z=grammatical words). Lexicon-based, experimental — cite the USAS taxonomy.",
};

export function TagsetSelector({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const corpusQ = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
  });

  const language = corpusQ.data?.language || "en";
  const current =
    (corpusQ.data as unknown as { pipeline_recipe?: { tagset?: string } } | undefined)
      ?.pipeline_recipe?.tagset ?? "upos";

  const saveTagset = useMutation({
    mutationFn: (tagset: string) => api.setCorpusTagset(cid, tagset),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpus", cid] }),
  });

  const grammatical = language === "ar" ? GRAMMATICAL_AR : GRAMMATICAL_EN;
  const chosenHint = TAGSET_HINTS[current];

  return (
    <div className="corpus-card tagset-card">
      <h3>Tagset</h3>
      <p className="settings-text-muted">
        Choose the grammatical or semantic tagset used for POS-style analysis of
        this corpus. The choice is saved with the corpus.
      </p>
      <select
        className="tagset-select"
        value={current}
        disabled={saveTagset.isPending}
        onChange={(e) => saveTagset.mutate(e.target.value)}
        aria-label="Corpus tagset"
      >
        <optgroup label="Grammatical">
          {grammatical.map((t) => (
            <option key={t} value={t}>{TAGSET_LABELS[t] ?? t}</option>
          ))}
        </optgroup>
        <optgroup label="Semantic">
          {SEMANTIC.map((t) => (
            <option key={t} value={t}>{TAGSET_LABELS[t] ?? t}</option>
          ))}
        </optgroup>
      </select>
      {chosenHint && <p className="tagset-hint">{chosenHint}</p>}
      {saveTagset.isError && (
        <p className="settings-text-muted" role="alert">
          Could not save the tagset: {(saveTagset.error as Error)?.message}
        </p>
      )}
    </div>
  );
}
