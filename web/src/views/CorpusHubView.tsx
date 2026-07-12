/**
 * CorpusHubView — search and download open-access corpora.
 *
 * Three hubs are supported (all proxied through the engine so the user's
 * IP stays out of upstream logs and CORS isn't an issue):
 *   - HuggingFace datasets-server (Wikipedia ar/en, OSCAR, CC-100, ...)
 *   - Wikipedia live (fresh article fetch for ar + en)
 *   - OPUS (parallel corpora, ar <-> en translation pairs)
 *
 * The user can search by keyword + language, see license metadata for
 * each result, and download with one click. Downloaded files land in the
 * browser's default download location; from there the user uploads them
 * into a corpus via the Projects view.
 *
 * Privacy: searches and downloads go through the engine, which calls the
 * upstream APIs. The user's corpus data never leaves their machine —
 * only search queries and the selected corpus IDs are sent to the hubs.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type HubSearchResult } from "@/lib/api";

export function CorpusHubView() {
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState<"ar" | "en" | "ar-en">("en");
  const [hub, setHub] = useState<"all" | "huggingface" | "wikipedia" | "opus">("all");
  const [searchParams, setSearchParams] = useState<{ q: string; lang: string; hub: string } | null>(null);
  const [downloading, setDownloading] = useState<Set<string>>(new Set());

  const catalogue = useQuery({ queryKey: ["hub-catalogue"], queryFn: api.hubCatalogue });
  const search = useQuery({
    queryKey: ["hub-search", searchParams],
    queryFn: () => {
      if (!searchParams) return null;
      return api.hubSearch(searchParams.q, searchParams.lang, searchParams.hub, 30);
    },
    enabled: !!searchParams,
  });

  const doSearch = () => {
    if (!query.trim()) return;
    setSearchParams({ q: query.trim(), lang: language, hub });
  };

  const handleDownload = async (result: HubSearchResult) => {
    setDownloading((prev) => new Set(prev).add(result.id));
    try {
      const url = api.hubDownloadUrl(result.hub, result.id, result.title, result.extra);
      // Trigger browser download
      const a = document.createElement("a");
      a.href = url;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      // Allow re-download after 3 seconds
      setTimeout(() => {
        setDownloading((prev) => {
          const next = new Set(prev);
          next.delete(result.id);
          return next;
        });
      }, 3000);
    }
  };

  return (
    <div className="hub-view">
      <div className="hub-header">
        <h1>Corpus Hub</h1>
        <p className="hub-subtitle">
          Search and download open-access corpora in Arabic and English.
          License metadata is shown for every result — always check before
          redistributing.
        </p>
      </div>

      {/* Search bar */}
      <div className="hub-search-bar">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
          placeholder="Search for a topic, corpus name, or keyword..."
          className="hub-search-input"
        />
        <select value={language} onChange={(e) => setLanguage(e.target.value as "ar" | "en" | "ar-en")}>
          <option value="en">English</option>
          <option value="ar">Arabic</option>
          <option value="ar-en">Arabic-English (parallel)</option>
        </select>
        <select value={hub} onChange={(e) => setHub(e.target.value as "all" | "huggingface" | "wikipedia" | "opus")}>
          <option value="all">All hubs</option>
          <option value="huggingface">HuggingFace</option>
          <option value="wikipedia">Wikipedia (live)</option>
          <option value="opus">OPUS (parallel)</option>
        </select>
        <button className="btn-primary" onClick={doSearch} disabled={!query.trim()}>
          Search
        </button>
      </div>

      {/* Hub catalogue (shown when no search has been run yet) */}
      {!searchParams && (
        <div className="hub-catalogue">
          <h2 className="hub-section-title">Available Hubs</h2>
          <div className="hub-cards">
            {catalogue.data?.hubs.map((h) => (
              <div key={h.id} className="hub-card">
                <h3>{h.name}</h3>
                <p>{h.description}</p>
                <div className="hub-card-meta">
                  <span className="hub-tag">Languages: {h.languages.join(", ")}</span>
                  <span className="hub-tag">{h.requires_key ? "API key required" : "No key needed"}</span>
                </div>
              </div>
            ))}
          </div>

          <h2 className="hub-section-title">Featured Corpora</h2>
          <div className="hub-cards">
            {catalogue.data?.featured.map((f) => (
              <div key={f.id} className="hub-card featured">
                <h3>{f.title}</h3>
                <div className="hub-card-meta">
                  <span className="hub-tag">Hub: {f.hub}</span>
                  <span className="hub-tag">Language: {f.language}</span>
                  <span className="hub-tag">Size: {f.size}</span>
                  <span className="hub-tag">License: {f.license}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search results */}
      {searchParams && (
        <div className="hub-results">
          <div className="hub-results-header">
            <h2 className="hub-section-title">
              {search.isFetching
                ? "Searching..."
                : `${search.data?.total ?? 0} result${(search.data?.total ?? 0) === 1 ? "" : "s"} for "${searchParams.q}"`}
            </h2>
            <button className="btn-small" onClick={() => setSearchParams(null)}>New search</button>
          </div>

          {search.isError && (
            <div className="error">
              Search failed: {String(search.error)}
            </div>
          )}

          {search.data?.results.length === 0 && !search.isFetching && (
            <div className="hub-empty">
              No results found. Try a different keyword or switch languages.
            </div>
          )}

          {search.data?.results.map((result) => (
            <div key={result.id} className={clsx("hub-result-card", `hub-${result.hub}`)}>
              <div className="hub-result-header">
                <span className="hub-result-hub-badge">{result.hub}</span>
                <h3 className="hub-result-title">{result.title}</h3>
              </div>
              <p className="hub-result-desc">{result.description}</p>
              <div className="hub-result-meta">
                <span className="hub-tag">Language: {result.language}</span>
                <span className="hub-tag">Size: {result.size}</span>
                <span className="hub-tag">License: {result.license}</span>
                <span className="hub-tag">Format: {result.download_format}</span>
              </div>
              <div className="hub-result-actions">
                <button
                  className="btn-primary hub-download-btn"
                  disabled={downloading.has(result.id)}
                  onClick={() => handleDownload(result)}
                >
                  {downloading.has(result.id) ? "Downloading..." : "Download"}
                </button>
                <span className="hub-download-hint">
                  After download, go to Projects to upload the file into a corpus.
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Privacy note */}
      <div className="hub-privacy-note">
        <strong>Privacy:</strong> Searches and downloads are proxied through the
        CorpusMind engine on your machine. Your existing corpus data is never sent
        to any hub — only search queries and the IDs of corpora you choose to download.
      </div>
    </div>
  );
}
