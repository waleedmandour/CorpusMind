/**
 * KwicTable — the shared KWIC results table (v1.2.13-2).
 *
 * Extracted from ConcordancerView, which had TWO byte-identical copies
 * (one for Simple mode, one for CQL mode) that could silently drift.
 * Both modes now render this single component.
 */
import clsx from "clsx";

export interface KwicLine {
  line_id: string;
  document_filename: string;
  left: string;
  node: string;
  right: string;
  pos: string;
  lemma: string;
}

const POS_COLORS: Record<string, string> = {
  NOUN: "pos-noun", VERB: "pos-verb", ADJ: "pos-adj", ADV: "pos-adv",
  DET: "pos-det", ADP: "pos-adp", PRON: "pos-pron", AUX: "pos-aux",
  PUNCT: "pos-punct", CCONJ: "pos-cconj", SCONJ: "pos-sconj",
};

interface KwicTableProps {
  lines: KwicLine[];
  corpusLang: string;
  corpusScriptTag?: string;
}

export function KwicTable({ lines, corpusLang, corpusScriptTag }: KwicTableProps) {
  return (
    <table className="kwic-table" data-corpus-script={corpusScriptTag}>
      <thead>
        <tr>
          <th>Line ID</th>
          <th>Document</th>
          <th className="right-align">Left context</th>
          <th>Node</th>
          <th>Right context</th>
          <th>POS</th>
          <th>Lemma</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((l) => (
          <tr key={l.line_id}>
            <td className="line-id" title={l.line_id}>{l.line_id.slice(-12)}</td>
            <td className="doc" title={l.document_filename}>{l.document_filename}</td>
            <td className="left" dir="auto" lang={corpusLang}>{l.left}</td>
            <td className="node" dir="auto" lang={corpusLang}>{l.node}</td>
            <td className="right" dir="auto" lang={corpusLang}>{l.right}</td>
            <td><span className={clsx("pos-tag", POS_COLORS[l.pos] ?? "pos-other")}>{l.pos}</span></td>
            <td className="lemma" dir="auto" lang={corpusLang}>{l.lemma}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * KwicPagination — the shared Previous/Next pager (also duplicated before).
 */
interface KwicPaginationProps {
  total: number;
  offset: number;
  pageSize: number;
  hasPrev: boolean;
  hasNext: boolean;
  isFetching: boolean;
  onPrev: () => void;
  onNext: () => void;
}

export function KwicPagination({
  total, offset, pageSize, hasPrev, hasNext, isFetching, onPrev, onNext,
}: KwicPaginationProps) {
  if (total <= pageSize) return null;
  return (
    <div className="pagination-controls" style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginTop: "var(--space-3)", justifyContent: "center" }}>
      <button className="btn-small" onClick={onPrev} disabled={!hasPrev || isFetching}>
        {"\u25C0"} Previous {pageSize}
      </button>
      <span style={{ fontSize: "13px", color: "var(--text-subtle)" }}>
        Page {Math.floor(offset / pageSize) + 1} of {Math.ceil(total / pageSize)}
      </span>
      <button className="btn-small" onClick={onNext} disabled={!hasNext || isFetching}>
        Next {pageSize} {"\u25B6"}
      </button>
    </div>
  );
}
