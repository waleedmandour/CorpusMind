/**
 * discourse-frameworks-catalogue.test.tsx — v1.2.14-11 (r11) field report.
 *
 * Field report: "I cannot see the 3 CDA frameworks in the UI!" — the 12 YAML
 * lens templates (incl. Fairclough CDA, van Dijk SCA, Wodak DHA) shipped with
 * every install and GET /api/v1/frameworks served them, but NO web component
 * ever called the endpoint. The Discourse window only rendered cue-taxonomy
 * category analysis.
 *
 * Fix pinned here: the Discourse panel now renders the theoretical-frameworks
 * catalogue (engine YAMLs = single source of truth), CDA family first, each
 * lens with its research-grounded definition (description, core concepts,
 * canonical references). Engine-side parity is covered by
 * engine/tests/test_r11_frameworks_catalogue.py.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalysisView, orderFrameworksCatalogue, FrameworksCatalogue } from "@/views/AnalysisView";
import { queryClientDefaults } from "@/lib/queryClient";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";

// sigma (the graph library behind CollocationNetwork) touches
// WebGL2RenderingContext at module load — jsdom has none, and this test
// exercises the Discourse panel's catalogue, not the network chart.
vi.mock("@/components/CollocationNetwork", () => ({ CollocationNetwork: () => null }));

const makeClient = () => new QueryClient({ defaultOptions: queryClientDefaults });

const okJson = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });

// The catalogue payload mirrors the enriched engine YAMLs (r11): every lens
// carries description / core_concepts / references; the trio + MCDA are CDA.
const FRAMEWORKS = [
  {
    key: "fairclough-cda", name: "fairclough-cda",
    full_name: "Fairclough (1995) Three-Dimensional CDA", version: "0.1.0", family: "cda",
    description: "Fairclough's three-dimensional model treats every text as (1) a text, (2) discursive practice, (3) social practice.",
    core_concepts: ["Three-dimensional model", "Naturalization"],
    references: ["Fairclough, N. (1989). Language and Power. Longman.", "Fairclough, N. (1995). Critical Discourse Analysis. Longman."],
    categories: [{ id: "textual_analysis", label: "Text analysis", description: "Vocabulary, grammar, cohesion." }],
  },
  {
    key: "van-dijk-sca", name: "van-dijk-sca",
    full_name: "van Dijk (2008) Socio-Cognitive Approach", version: "0.1.0", family: "cda",
    description: "Cognition mediates between discourse and society; ideologies are shared social representations.",
    core_concepts: ["Mental models", "Ideological square"],
    references: ["van Dijk, T. A. (1998). Ideology: A Multidisciplinary Approach. Sage."],
    categories: [{ id: "actors", label: "Social actors", description: "" }],
  },
  {
    key: "wodak-dha", name: "wodak-dha",
    full_name: "Wodak (2001) Discourse-Historical Approach", version: "0.1.0", family: "cda",
    description: "Four levels of context; discourse strategies (nomination, predication, argumentation topoi).",
    core_concepts: ["Topoi", "Nomination strategies"],
    references: ["Reisigl, M., & Wodak, R. (2001). Discourse and Discrimination. Routledge."],
    categories: [{ id: "content", label: "Content", description: "" }],
  },
  {
    key: "machin-mayr-mcda", name: "machin-mayr-mcda",
    full_name: "Machin & Mayr (2012) Multimodal CDA", version: "0.1.0", family: "mcda",
    description: "Multimodal toolkit for tracing legitimation and social-actor representation.",
    core_concepts: ["Social actors", "Legitimation"],
    references: ["Machin, D., & Mayr, A. (2012). How to Do Critical Discourse Analysis. Sage."],
    categories: [{ id: "actors", label: "Social actors", description: "" }],
  },
  {
    key: "halliday-sfl", name: "halliday-sfl",
    full_name: "Halliday (1985) Systemic Functional Linguistics", version: "0.1.0", family: "sfl",
    description: "Three metafunctions; system networks; register.",
    core_concepts: ["Metafunctions"], references: ["Halliday, M. A. K. (1985). An Introduction to Functional Grammar. Arnold."],
    categories: [],
  },
  {
    key: "toulmin-argumentation", name: "toulmin-argumentation",
    full_name: "Toulmin (1958) Argumentation Model", version: "0.1.0", family: "argumentation",
    description: "Claim, data, warrant, backing, qualifier, rebuttal.",
    core_concepts: ["Claim-warrant"], references: ["Toulmin, S. E. (1958/2003). The Uses of Argument. Cambridge University Press."],
    categories: [],
  },
  {
    key: "aristotle-rhetoric", name: "aristotle-rhetoric",
    full_name: "Aristotle (c. 350 BCE) Rhetoric", version: "0.1.0", family: "rhetoric",
    description: "Ethos, pathos, logos; enthymeme; kairos.",
    core_concepts: ["Three pisteis"], references: ["Aristotle (c. 350 BCE/2007). On Rhetoric. Oxford University Press."],
    categories: [],
  },
];

const DISCOURSE_RESULT = {
  corpus_id: "c1", taxonomy: "Hyland 2005", taxonomy_key: "hyland2005",
  total_tokens: 10000,
  citation: "Hyland (2005) Metadiscourse",
  categories: {
    hedges: { freq: 10, per_million: 1000.0, dp: 0.5, log_likelihood: 3.2, log_ratio: 1.1, pct_diff: 25.0, simple_maths: 0.4, examples: ["perhaps", "may"] },
  },
};

let fetchCalls: string[] = [];

beforeEach(() => {
  cleanup();
  fetchCalls = [];
  useApp.setState({ activeCorpusId: "c1" });
  useUI.setState({ lang: "en", studentClient: false, activeNav: "discourse" });
  (globalThis as any).fetch = vi.fn((url: string) => {
    const u = String(url);
    fetchCalls.push(u);
    if (u.includes("/frameworks")) return Promise.resolve(okJson({ frameworks: FRAMEWORKS }));
    if (u.includes("/discourse/taxonomies")) {
      return Promise.resolve(okJson({
        taxonomies: [
          { key: "hyland2005", name: "Hyland 2005", languages: ["en"] },
          { key: "martinwhite2005", name: "Martin & White 2005", languages: ["en"] },
        ],
      }));
    }
    if (u.includes("/discourse")) return Promise.resolve(okJson(DISCOURSE_RESULT));
    if (u.includes("/corpora/c1")) return Promise.resolve(okJson({ id: "c1", name: "Corpus One", project_id: "p1" }));
    if (u.includes("/corpora")) return Promise.resolve(okJson([{ id: "c1", name: "Corpus One", project_id: "p1" }]));
    if (u.includes("/projects/p1/corpora")) return Promise.resolve(okJson([{ id: "c1", name: "Corpus One", project_id: "p1" }]));
    return Promise.resolve(okJson({}));
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const sleep = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

describe("r11 Discourse window: theoretical-frameworks catalogue (field report: 3 CDA frameworks invisible)", () => {
  it("the Discourse panel renders the catalogue with the CDA trio visible", async () => {
    render(<QueryClientProvider client={makeClient()}><AnalysisView /></QueryClientProvider>);
    await sleep(300);
    const catalogue = document.querySelector(".fw-catalogue");
    expect(catalogue).not.toBeNull();
    const cards = Array.from(document.querySelectorAll(".fw-card"));
    expect(cards.length).toBe(FRAMEWORKS.length);
    const names = cards.map((c) => c.querySelector("strong")?.textContent ?? "");
    // CDA family first, in the classic order, then Machin & Mayr (mcda).
    expect(names[0]).toContain("Fairclough");
    expect(names[1]).toContain("van Dijk");
    expect(names[2]).toContain("Wodak");
    expect(names[3]).toContain("Machin & Mayr");
    // Research grounding is on screen, not just in the payload.
    const fairclough = cards[0];
    expect(fairclough.textContent).toContain("three-dimensional model");
    expect(fairclough.textContent).toContain("Language and Power");
    expect(fairclough.textContent).toContain("Core concepts");
    // The framework data came from the engine catalogue endpoint.
    expect(fetchCalls.some((u) => u.includes("/frameworks"))).toBe(true);
  });

  it("FrameworksCatalogue (standalone) keeps the CDA-first order via orderFrameworksCatalogue", () => {
    const ordered = orderFrameworksCatalogue(FRAMEWORKS as any);
    expect(ordered.slice(0, 4).map((f) => f.key)).toEqual(
      ["fairclough-cda", "van-dijk-sca", "wodak-dha", "machin-mayr-mcda"],
    );
  });

  it("renders nothing (no empty box) before the catalogue loads", () => {
    (globalThis as any).fetch = vi.fn(() => new Promise<Response>(() => {})); // hang
    render(<QueryClientProvider client={makeClient()}><FrameworksCatalogue /></QueryClientProvider>);
    expect(document.querySelector(".fw-catalogue")).toBeNull();
  });
});
