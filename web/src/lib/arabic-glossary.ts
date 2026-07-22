/**
 * Academic Arabic terminology glossary for corpus linguistics — Issue 3.
 *
 * This module is the single source of truth for Arabic translations of
 * technical terms used in corpus linguistics, statistical NLP, and
 * multimodal discourse analysis. Every entry follows the conventions
 * used in:
 *
 *   - Arabic Linguistics Society style guide
 *   - King Abdulaziz City for Science and Technology (KACST) terminology
 *     database (Baheth)
 *   - "معجم علوم اللغة" (Mu'jam 'Ulum al-Lugha) by Abdel-Salam al-Masdi
 *   - Arabic translations of Sinclair (1991), McEnery & Hardie (2012),
 *     and Baker et al. (2008) where available
 *
 * Each entry includes:
 *   - en: the English term (canonical form, as used in the literature)
 *   - ar: the academic Arabic translation
 *   - alt: alternative Arabic translations (for context-dependent variants)
 *   - note: reviewer note explaining the choice, especially for terms
 *     where the literature disagrees
 *
 * Usage in components:
 *
 *   import { ACADEMIC_GLOSSARY, lookupTerm } from "@/lib/arabic-glossary";
 *   const arabicTerm = lookupTerm("concordance").ar; // "كشف السياق"
 *
 * The glossary is also exposed via the API so the engine's AI Assistant
 * can use the same terminology when generating Arabic responses.
 */

export interface GlossaryEntry {
  en: string;
  ar: string;
  alt?: string[];
  note?: string;
}

export const ACADEMIC_GLOSSARY: GlossaryEntry[] = [
  // -----------------------------------------------------------------
  // Corpus linguistics — core concepts
  // -----------------------------------------------------------------
  {
    en: "corpus",
    ar: "دخيرة لغوية",
    alt: ["مدونة لغوية", "مكنز لغوي"],
    note: "دخيرة لغوية is preferred per KACST; مدونة is also widely used in Arabic NLP literature but is ambiguous with 'blog'.",
  },
  {
    en: "corpus linguistics",
    ar: "لغويات الدخائر",
    alt: ["علم الدخائر اللغوية", "لغويات المدونة"],
  },
  {
    en: "reference corpus",
    ar: "الدخيرة المرجعية",
  },
  {
    en: "target corpus",
    ar: "الدخيرة الهدف",
  },
  {
    en: "concordance",
    ar: "كشف السياق",
    alt: ["كونكوردانس", "الفهرس السياقي"],
    note: "كشف السياق is the literal academic term; كونكوردانس is a transliteration common in software UIs.",
  },
  {
    en: "KWIC",
    ar: "الكلمة في سياقها",
    alt: ["الكلمة في وسط السياق"],
    note: "Abbreviation for 'KeyWord In Context'. Spelled out in Arabic because the acronym doesn't transfer.",
  },
  {
    en: "collocation",
    ar: "المتلازمات اللفظية",
    alt: ["التلازم اللفظي", "المصاحبة اللفظية"],
    note: "Use المتلازمات (plural) when referring to the phenomenon, المتلازم (singular) for one pair.",
  },
  {
    en: "collocate",
    ar: "المتلازم",
    alt: ["المصاحب"],
  },
  {
    en: "node word",
    ar: "الكلمة المحور",
    alt: ["الكلمة المركزية"],
  },
  {
    en: "keyness",
    ar: "الكلمة المفتاحية",
    alt: ["أهمية الكلمات", "الدلالة الإحصائية للكلمات"],
    note: "الكلمة المفتاحية is the term used in Arabic translations of Scott & Tribble (2006).",
  },
  {
    en: "keyword",
    ar: "الكلمة المفتاحية",
  },
  {
    en: "frequency",
    ar: "التكرار",
  },
  {
    en: "frequency list",
    ar: "قائمة التكرار",
    alt: ["قائمة التردد"],
  },
  {
    en: "raw frequency",
    ar: "التكرار الخام",
  },
  {
    en: "normalized frequency",
    ar: "التكرار المعياري",
    alt: ["التكرار النسبي"],
    note: "Usually per-million-words. المعياري is preferred over النسبي because the latter can imply proportion.",
  },
  {
    en: "per million words",
    ar: "لكل مليون كلمة",
  },
  {
    en: "dispersion",
    ar: "التشتت",
  },
  {
    en: "token",
    ar: "الرمز اللغوي",
    alt: ["المورف", "الوحدة المعجمية"],
    note: "رمز is preferred because it captures the surface-form notion; مورف is a morpheme-level term.",
  },
  {
    en: "type",
    ar: "النوع اللغوي",
    alt: ["النمط"],
    note: "Distinct from morphological type. Use النوع اللغوي to disambiguate.",
  },
  {
    en: "type-token ratio",
    ar: "نسبة تنوع الأنواع",
    alt: ["نسبة الأنواع إلى الرموز", "TTR"],
    note: "نسبة تنوع الأنواع is clearer than the literal الأنواع إلى الرموز because it captures the lexical-diversity semantics.",
  },
  {
    en: "TTR",
    ar: "نسبة تنوع الأنواع",
    alt: ["TTR"],
  },
  {
    en: "STTR",
    ar: "نسبة تنوع الأنواع المعيارية",
    alt: ["STTR"],
    note: "Standardized TTR computed over fixed-size chunks.",
  },
  {
    en: "lemma",
    ar: "الأساس الصرفي",
    alt: ["المدخل المعجمي", "الليمما"],
    note: "الأساس الصرفي is the academic term; المدخل المعجمي is used in dictionary contexts.",
  },
  {
    en: "lemmatization",
    ar: "استخراج الأساس الصرفي",
  },
  {
    en: "POS tag",
    ar: "الوسم الصرفي",
    alt: ["الوسم النحوي"],
  },
  {
    en: "POS tagging",
    ar: "الوسم الصرفي",
  },
  {
    en: "dependency parsing",
    ar: "الإعراب التبعي",
    alt: ["التحليل التبعي"],
    note: "الإعراب is the traditional Arabic grammatical term; التبعي specifies the dependency flavor.",
  },
  {
    en: "n-gram",
    ar: "متتالية أحادية",
    alt: ["N-gram", "السلاسل النحوية"],
    note: "Use the transliteration N-gram for n=2 (bigram), n=3 (trigram); متتالية for the general concept.",
  },
  {
    en: "bigram",
    ar: "ثنائية لفظية",
    alt: ["bigram"],
  },
  {
    en: "trigram",
    ar: "ثلاثية لفظية",
    alt: ["trigram"],
  },
  {
    en: "annotation",
    ar: "الوسم اللغوي",
    alt: ["التأطير اللغوي"],
  },
  {
    en: "annotation version",
    ar: "إصدار الوسم",
  },
  {
    en: "pipeline",
    ar: "خط المعالجة",
    alt: ["سلسلة المعالجة"],
  },
  {
    en: "register",
    ar: "السجل اللغوي",
  },
  {
    en: "genre",
    ar: "النوع الأدبي",
    alt: ["الجنس الأدبي"],
    note: "In corpus design, النوع is broader than الأدبي — use النوع الأدبي only for literary genres; otherwise just النوع.",
  },

  // -----------------------------------------------------------------
  // Statistical measures
  // -----------------------------------------------------------------
  {
    en: "log-likelihood",
    ar: "الاحتمالية اللوغاريتمية",
    alt: ["LL", "G²"],
  },
  {
    en: "chi-square",
    ar: "مربع كاي",
    alt: ["χ²", "اختبار كاي التربيعي"],
  },
  {
    en: "mutual information",
    ar: "المعلومات المتبادلة",
    alt: ["MI"],
  },
  {
    en: "T-score",
    ar: "درجة تي",
    alt: ["T-score"],
  },
  {
    en: "Dice coefficient",
    ar: "معامل دايس",
  },
  {
    en: "LogDice",
    ar: "دايس اللوغاريتمي",
    alt: ["LogDice"],
  },
  {
    en: "log ratio",
    ar: "النسبة اللوغاريتمية",
    alt: ["Log Ratio"],
  },
  {
    en: "odds ratio",
    ar: "نسبة الأرجحية",
  },
  {
    en: "%DIFF",
    ar: "نسبة الفرق المئوية",
    alt: ["%DIFF"],
  },
  {
    en: "simple maths",
    ar: "المعادلة البسيطة",
    alt: ["Simple Maths", "Kilgarriff's measure"],
    note: "Kilgarriff (2009) — keep the English name in parentheses for clarity.",
  },
  {
    en: "Delta P",
    ar: "دلتا بي",
    alt: ["ΔP"],
  },
  {
    en: "Juilland's D",
    ar: "معامل جويلاند دي",
    alt: ["Juilland's D"],
  },
  {
    en: "Gries' DP",
    ar: "معامل جريز دي بي",
    alt: ["Gries' DP", "DP"],
  },
  {
    en: "effect size",
    ar: "حجم الأثر",
  },
  {
    en: "statistical significance",
    ar: "الدلالة الإحصائية",
  },
  {
    en: "p-value",
    ar: "قيمة الاحتمالية",
    alt: ["p-value", "القيمة الاحتمالية"],
  },

  // -----------------------------------------------------------------
  // Discourse analysis
  // -----------------------------------------------------------------
  {
    en: "discourse analysis",
    ar: "تحليل الخطاب",
  },
  {
    en: "critical discourse analysis",
    ar: "التحليل النقدي للخطاب",
    alt: ["CDA"],
  },
  {
    en: "metadiscourse",
    ar: "ما وراء الخطاب",
    alt: ["المعجم الإشرافي"],
    note: "ما وراء الخطاب follows Hyland (2005); المعجم الإشرافي is a less common alternative.",
  },
  {
    en: "multimodal discourse analysis",
    ar: "تحليل الخطاب متعدد الوسائط",
    alt: ["MDA"],
  },
  {
    en: "visual grammar",
    ar: "القواعد البصرية",
    note: "Per Kress & van Leeuwen (2006).",
  },
  {
    en: "metafunction",
    ar: "الوظيفة المعنوية",
    alt: ["الوظيفة التلويّة"],
    note: "Halliday's three metafunctions: representational, interactive, compositional.",
  },
  {
    en: "representational metafunction",
    ar: "الوظيفة التمثيلية",
  },
  {
    en: "interactive metafunction",
    ar: "الوظيفة التفاعلية",
  },
  {
    en: "compositional metafunction",
    ar: "الوظيفة التركيبية",
  },
  {
    en: "appraisal theory",
    ar: "نظرية التقييم",
    note: "Martin & White (2005).",
  },
  {
    en: "semiotics",
    ar: "السيميائيات",
    alt: ["علاميات"],
  },
  {
    en: "ideology",
    ar: "الإيديولوجيا",
    alt: ["العقيدة"],
    note: "In CDA, الإيديولوجيا is preferred over العقيدة (which has religious connotations).",
  },
  {
    en: "power relation",
    ar: "علاقات القوة",
  },
  {
    en: "metaphor",
    ar: "الاستعارة",
  },
  {
    en: "conceptual metaphor theory",
    ar: "نظرية الاستعارة المفاهيمية",
    alt: ["CMT"],
    note: "Lakoff & Johnson (1980).",
  },
  {
    en: "argumentation",
    ar: "الجدل",
    alt: ["الحجاج", "التحليل الجدلي"],
    note: "Toulmin's model. الحجاج is preferred in Maghreb tradition; الجدل in Mashreq.",
  },

  // -----------------------------------------------------------------
  // Arabic-specific NLP
  // -----------------------------------------------------------------
  {
    en: "Arabic normalization",
    ar: "تطبيع النص العربي",
  },
  {
    en: "alef normalization",
    ar: "توحيد الألف",
    note: "Unifying أ إ آ → ا for matching purposes.",
  },
  {
    en: "teh marbuta",
    ar: "التاء المربوطة",
  },
  {
    en: "diacritics",
    ar: "التشكيل",
    alt: ["الحركات"],
  },
  {
    en: "diacritization",
    ar: "التشكيل التلقائي",
    alt: ["ضبط النص"],
  },
  {
    en: "root pattern",
    ar: "الجذر الصرفي",
    alt: ["الوزن الصرفي"],
    note: "In Arabic morphology, words derive from tri-consonantal roots via patterns (أوزان).",
  },
  {
    en: "dialect identification",
    ar: "تحديد اللهجة",
  },
  {
    en: "Modern Standard Arabic",
    ar: "العربية الفصحى الحديثة",
    alt: ["MSA", "الفصحى"],
  },
  {
    en: "Classical Arabic",
    ar: "العربية الكلاسيكية",
    alt: ["العربية الفصحى التراثية"],
  },
  {
    en: "Quranic Arabic",
    ar: "عربية القرآن الكريم",
  },

  // -----------------------------------------------------------------
  // AI / LLM terminology
  // -----------------------------------------------------------------
  {
    en: "grounded",
    ar: "مؤسَّس",
    alt: ["مستند إلى أدلة"],
    note: "In the CorpusMind-specific sense: backed by a tool-call citation.",
  },
  {
    en: "ungrounded",
    ar: "غير مؤسَّس",
    alt: ["غير مستند إلى أدلة"],
  },
  {
    en: "tool call",
    ar: "استدعاء الأداة",
  },
  {
    en: "evidence",
    ar: "الدليل",
    alt: ["الشاهد"],
  },
  {
    en: "citation",
    ar: "الإحالة",
    alt: ["الاستشهاد"],
  },
  {
    en: "language model",
    ar: "النموذج اللغوي",
  },
  {
    en: "large language model",
    ar: "النموذج اللغوي الكبير",
    alt: ["LLM"],
  },
  {
    en: "inference",
    ar: "الاستدلال",
  },
  {
    en: "local inference",
    ar: "الاستدلال المحلي",
    note: "Emphasizes that the model runs on the user's hardware, not in the cloud.",
  },
  {
    en: "prompt",
    ar: "المحفّز",
    alt: ["الموجّه", "prompt"],
    note: "المحفّز is preferred in academic Arabic AI literature; الموجّه is also common.",
  },
  {
    en: "temperature",
    ar: "حرارة النموذج",
    note: "LLM sampling temperature. Use حرارة النموذج to disambiguate from physical temperature.",
  },
  {
    en: "embedding",
    ar: "التضمين المتجهي",
    alt: ["embedding", "المتجه الدلالي"],
  },
  {
    en: "RAG",
    ar: "التوليد المعزز بالاسترجاع",
    alt: ["RAG"],
  },
];

/**
 * Look up the Arabic translation for an English term.
 *
 * Returns the first matching entry's `ar` field, or `null` if not found.
 * The lookup is case-insensitive on the English term.
 *
 * For UI usage, prefer the `t(lang, key)` function from `i18n.ts` —
 * this glossary is for content where the English term appears in
 * user-facing text (e.g., a stat header labeled "log-likelihood")
 * and needs to be swapped out for the Arabic equivalent.
 */
export function lookupTerm(en: string): GlossaryEntry | null {
  const lower = en.toLowerCase().trim();
  for (const entry of ACADEMIC_GLOSSARY) {
    if (entry.en.toLowerCase() === lower) return entry;
    if (entry.alt?.some(a => a.toLowerCase() === lower)) return entry;
  }
  return null;
}

/**
 * Translate a single English term to Arabic, with fallback to the
 * original English if no translation is available.
 */
export function translateTerm(en: string): string {
  const entry = lookupTerm(en);
  return entry?.ar ?? en;
}

/**
 * Translate all known terms in a string. Useful for column headers
 * like "Log-likelihood" or "Chi-Square" — each word/phrase is looked
 * up and replaced if a translation exists.
 */
export function translateTermsInText(text: string): string {
  let out = text;
  // Sort by length descending so multi-word phrases match before single words.
  const sorted = [...ACADEMIC_GLOSSARY].sort((a, b) => b.en.length - a.en.length);
  for (const entry of sorted) {
    // Word-boundary, case-insensitive match.
    const re = new RegExp(`\\b${escapeRegex(entry.en)}\\b`, "gi");
    out = out.replace(re, entry.ar);
  }
  return out;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
