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
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

const TAGSET_LABELS: Record<string, string> = {
  upos: "UD UPOS (universal)",
  ptb: "Penn Treebank",
  claws7: "CLAWS-7 (BNC standard)",
  calima: "CAMeL / Calima (native)",
  usas: "USAS semantic (experimental)",
};

const GRAMMATICAL_EN = ["upos", "ptb", "claws7"];
const GRAMMATICAL_AR = ["upos", "calima"];
// v1.2.11: Urdu/Hindi/Farsi have no language-specific tagset in the engine;
// UPOS is the only valid choice (server validates - a PTB tagger does not
// exist for these languages).
const GRAMMATICAL_NEW_LANGS = ["upos"];
const SEMANTIC = ["usas"];

// v1.2.14-7 (r7): hints now resolve through i18n keys; the tagset names
// themselves are proper nouns and stay as-is in both languages.
const TAGSET_HINT_KEYS: Record<string, Parameters<typeof t>[1]> = {
  upos: "ts_hint_upos",
  ptb: "ts_hint_ptb",
  claws7: "ts_hint_claws7",
  calima: "ts_hint_calima",
  usas: "ts_hint_usas",
};

export function TagsetSelector({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const lang = useUI((s) => s.lang);
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

  const grammatical = language === "ar" ? GRAMMATICAL_AR : ["ur", "hi", "fa"].includes(language) ? GRAMMATICAL_NEW_LANGS : GRAMMATICAL_EN;
  const chosenHintKey = TAGSET_HINT_KEYS[current];

  return (
    <div className="corpus-card tagset-card">
      <h3>{t(lang, "ts_title")}</h3>
      <p className="settings-text-muted">
        {t(lang, "ts_intro")}
      </p>
      <select
        className="tagset-select"
        value={current}
        disabled={saveTagset.isPending}
        onChange={(e) => saveTagset.mutate(e.target.value)}
        aria-label={t(lang, "ts_aria")}
      >
        <optgroup label={t(lang, "ts_grammatical")}>
          {grammatical.map((t2) => (
            <option key={t2} value={t2}>{TAGSET_LABELS[t2] ?? t2}</option>
          ))}
        </optgroup>
        <optgroup label={t(lang, "ts_semantic")}>
          {SEMANTIC.map((t2) => (
            <option key={t2} value={t2}>{TAGSET_LABELS[t2] ?? t2}</option>
          ))}
        </optgroup>
      </select>
      {chosenHintKey && <p className="tagset-hint">{t(lang, chosenHintKey)}</p>}
      {saveTagset.isError && (
        <p className="settings-text-muted" role="alert">
          {t(lang, "ts_save_error")} {(saveTagset.error as Error)?.message}
        </p>
      )}
    </div>
  );
}
