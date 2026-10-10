"""CQL-lite: a corpus-query-language front end for the concordance engine.

Phase 1 (no schema change). The grammar is CQP-flavoured so that queries
written for Sketch Engine / CWB transfer directly, restricted to what the
shipped v1.2.12 token schema can honour:

    query     := sequence [ "within" ("sentence" | "document") ]
    sequence  := element+
    element   := unit [quantifier] [flags]
    unit      := quoted | anytok | spec | group
    quoted    := '"' value '"'            word token (wildcards * ? allowed)
    anytok    := '[' ']'                  any single token
    spec      := '[' test (('&'|'|') test)* ']'
    test      := attr ('=' | '!=') value | attr '=' '/' regex '/'
    group     := '(' sequence ('|' sequence)* ')'
    quantifier:= '?' | '*' | '+' | '{' m [',' [n]] '}' | '{' ',' n '}'
    flags     := '%' ( 'c' | 'd' )        c = ignore case, d = fold diacritics

Attributes: word | lemma | pos (UPOS) | xpos (XPOS) | rel (UD dep_rel) |
morph (Feats substring) | root | pattern (Arabic morph layer components).
``&`` binds tighter than ``|`` inside a spec (disjunction of conjunctions).

Semantics (documented deviations from full CQP, all deliberate):
  * Matching is case-SENSITIVE by default (CQP convention); ``%c`` relaxes it.
    (The simple concordance box is case-insensitive by default — CQL is not.)
  * Sequences match over the document token stream and MAY cross sentence
    boundaries (CQP ``within text`` behaviour). ``within sentence`` restricts
    every match to a single sentence. Paragraph scope is NOT available: the
    ingestion pipeline flattens paragraph markup (documented limitation).
  * Punctuation tokens participate in matching as ordinary tokens (they can
    be matched explicitly, e.g. [word="."] or bridged with ``[]`` gaps).
  * Every distinct (start, end) match span is reported; ambiguous spans
    (e.g. ``"said" []* "news"``) produce one line per span.
  * A repetition unit always consumes at least one token, so ``("a"?)*``-style
    empty loops cannot occur; matches that would span zero tokens are dropped.
  * ``%d`` folds diacritics for exact/wildcard tests only; regex tests always
    run on raw text (mirroring the app's regex convention). ``normalize=True``
    applies the corpus language's normalizer to word/lemma exact/wildcard
    tests only.

Architecture (mirrors the v1.0.1 phrase-verification pattern in
stats.service.search_concordance): a SQL *prefilter* over the first element
generates candidate anchor tokens (conservative superset — when a test cannot
be expressed in SQL under the active flag combination it is dropped from the
prefilter, never approximated); a backtracking matcher then verifies the full
query over each candidate document's token stream. The candidate fetch is
bounded by the same _CONCORDANCE_FETCH_CAP as phrase queries; hitting it
marks ``total_capped`` in the query metadata (total is then a lower bound).
KWIC context, seeded sampling, AntConc-style sorting and pagination reuse the
concordance conventions so CQL results render identically in the client.
"""

from __future__ import annotations

import fnmatch
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import and_ as _and, func, or_ as _or, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from storage.models import Document, Token
from stats.service import (
    ConcordanceLine,
    ConcordanceResult,
    _CONCORDANCE_FETCH_CAP,
    _latest_version_id,
    _morph_component_cond,
    _norm_description,
    _Norm,
    _resolve_norm,
    _sort_token,
)


class CqlSyntaxError(ValueError):
    """A CQL-lite query could not be parsed or validated."""


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Flags:
    ignore_case: bool = False
    fold_diacritics: bool = False


@dataclass(frozen=True, slots=True)
class Test:
    """One attribute test. ``op`` is '=' or '!='; regex values carry /re/."""

    attr: str
    op: str
    value: str
    regex: bool = False


# Token units. Spec tests are stored as a DNF: disjunction of conjunctions.
@dataclass(frozen=True, slots=True)
class SpecUnit:
    dnf: tuple[tuple[Test, ...], ...]


@dataclass(frozen=True, slots=True)
class WordUnit:
    value: str


@dataclass(frozen=True, slots=True)
class AnyUnit:
    pass


@dataclass(frozen=True, slots=True)
class GroupUnit:
    alts: tuple[tuple["Element", ...], ...]


@dataclass(frozen=True, slots=True)
class Element:
    unit: SpecUnit | WordUnit | AnyUnit | GroupUnit
    qmin: int = 1
    qmax: int | None = 1  # None = unbounded
    flags: Flags = field(default_factory=Flags)


@dataclass(frozen=True, slots=True)
class CqlQuery:
    sequence: tuple[Element, ...]
    within: str = "document"  # "document" | "sentence"


ATTRS = ("word", "lemma", "pos", "xpos", "rel", "morph", "root", "pattern")

_ATTR_COLUMNS = {
    "word": Token.text,
    "lemma": Token.lemma,
    "pos": Token.pos,
    "xpos": Token.pos_fine,
    "rel": Token.dep_rel,
    "morph": Token.morph,
}


# --------------------------------------------------------------------------- #
# Lexer
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Tok:
    kind: str  # LB RB LP RP PIPE AMP EQ NEQ QUANT STR RE FLAGS WORD WITHIN EOF
    value: object = ""
    pos: int = 0


def _lex(src: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "[":
            toks.append(_Tok("LB", ch, i))
            i += 1
        elif ch == "]":
            toks.append(_Tok("RB", ch, i))
            i += 1
        elif ch == "(":
            toks.append(_Tok("LP", ch, i))
            i += 1
        elif ch == ")":
            toks.append(_Tok("RP", ch, i))
            i += 1
        elif ch == "|":
            toks.append(_Tok("PIPE", ch, i))
            i += 1
        elif ch == "&":
            toks.append(_Tok("AMP", ch, i))
            i += 1
        elif ch == "=":
            toks.append(_Tok("EQ", ch, i))
            i += 1
        elif ch == "!":
            if i + 1 < n and src[i + 1] == "=":
                toks.append(_Tok("NEQ", "!=", i))
                i += 2
            else:
                raise CqlSyntaxError(f"position {i}: lone '!' — did you mean '!='?")
        elif ch == "?":
            toks.append(_Tok("QUANT", (0, 1), i))
            i += 1
        elif ch == "*":
            toks.append(_Tok("QUANT", (0, None), i))
            i += 1
        elif ch == "+":
            toks.append(_Tok("QUANT", (1, None), i))
            i += 1
        elif ch == "{":
            m = re.match(r"\{\s*(\d+)?\s*(?:,\s*(\d*)\s*)?\}", src[i:])
            if not m:
                raise CqlSyntaxError(f"position {i}: malformed quantifier (use {{m,n}}, {{m,}}, {{,n}}, {{m}})")
            lo, hi = m.group(1), m.group(2)
            if lo is None and hi is None:
                raise CqlSyntaxError(f"position {i}: empty quantifier '{{}}' — '{{}}' is not a quantifier")
            qmin = int(lo) if lo else 0
            qmax: int | None
            if hi is None:
                qmax = qmin if lo is not None else None  # {m} vs unreachable
                if lo is None:  # pragma: no cover - regex above forbids
                    raise CqlSyntaxError(f"position {i}: malformed quantifier")
            else:
                qmax = int(hi) if hi != "" else None  # {m,} / {,n} / {m,n}
            toks.append(_Tok("QUANT", (qmin, qmax), i))
            i += m.end()
        elif ch == '"':
            j, buf = i + 1, []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n and src[j + 1] in ('"', "\\"):
                    buf.append(src[j + 1])
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise CqlSyntaxError(f"position {i}: unterminated string literal")
            toks.append(_Tok("STR", "".join(buf), i))
            i = j + 1
        elif ch == "/":
            j, buf = i + 1, []
            while j < n and src[j] != "/":
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j])
                    buf.append(src[j + 1])
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            if j >= n:
                raise CqlSyntaxError(f"position {i}: unterminated regex literal")
            toks.append(_Tok("RE", "".join(buf), i))
            i = j + 1
        elif ch == "%":
            m = re.match(r"%([A-Za-z]*)", src[i:])
            flags = m.group(1)
            unknown = set(flags) - {"c", "d"}
            if unknown:
                raise CqlSyntaxError(
                    f"position {i}: unknown flag(s) {''.join(sorted(unknown))} — supported: %c (ignore case), %d (fold diacritics)"
                )
            toks.append(_Tok("FLAGS", flags, i))
            i += m.end()
        else:
            m = re.match(r"[A-Za-z_][A-Za-z_]*", src[i:])
            if not m:
                raise CqlSyntaxError(f"position {i}: unexpected character {ch!r}")
            word = m.group(0)
            if word.lower() == "within":
                toks.append(_Tok("WITHIN", word, i))
            else:
                toks.append(_Tok("WORD", word, i))
            i += m.end()
    toks.append(_Tok("EOF", "", n))
    return toks


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def _parse_quant(t: _Tok) -> tuple[int, int | None]:
    qmin, qmax = t.value
    if qmax is not None and qmax < qmin:
        raise CqlSyntaxError(f"position {t.pos}: quantifier upper bound below lower bound")
    if qmax == 0:
        raise CqlSyntaxError(f"position {t.pos}: quantifier permits zero occurrences only — query matches nothing")
    return qmin, qmax


class _Parser:
    def __init__(self, toks: list[_Tok]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def take(self) -> _Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, kind: str, what: str) -> _Tok:
        t = self.peek()
        if t.kind != kind:
            raise CqlSyntaxError(f"position {t.pos}: expected {what}")
        return self.take()

    def parse(self) -> CqlQuery:
        seq = self.parse_sequence(stop=("WITHIN", "EOF"))
        within = "document"
        if self.peek().kind == "WITHIN":
            self.take()
            t = self.expect("WORD", "'sentence' or 'document' after 'within'")
            scope = str(t.value).lower()
            if scope not in ("sentence", "document"):
                raise CqlSyntaxError(
                    f"position {t.pos}: 'within' supports 'sentence' or 'document' (got {t.value!r}); "
                    "paragraph markup is flattened at ingestion and cannot be queried"
                )
            within = scope
        t = self.peek()
        if t.kind != "EOF":
            raise CqlSyntaxError(f"position {t.pos}: unexpected {t.value!r} after end of query")
        return CqlQuery(sequence=seq, within=within)

    def parse_sequence(self, stop: tuple[str, ...]) -> tuple[Element, ...]:
        elems: list[Element] = []
        while self.peek().kind not in stop:
            elems.append(self.parse_element())
        if not elems:
            t = self.peek()
            raise CqlSyntaxError(f"position {t.pos}: empty sequence — a query needs at least one token element")
        return tuple(elems)

    def parse_element(self) -> Element:
        unit, flaggable, inner_flags = self.parse_unit()
        qmin, qmax = 1, 1
        if self.peek().kind == "QUANT":
            qmin, qmax = _parse_quant(self.take())
        flags = Flags()
        if self.peek().kind == "FLAGS":
            ftok = self.take()
            flags = Flags(ignore_case="c" in str(ftok.value), fold_diacritics="d" in str(ftok.value))
            if not flaggable:
                raise CqlSyntaxError(
                    f"position {ftok.pos}: %flags are allowed on word tokens and [...] specifications only"
                )
            if inner_flags is not None:
                raise CqlSyntaxError(
                    f"position {ftok.pos}: flags given both inside and outside the specification — use one position"
                )
        elif inner_flags is not None:
            flags = inner_flags
        return Element(unit=unit, qmin=qmin, qmax=qmax, flags=flags)

    def parse_unit(self) -> tuple[SpecUnit | WordUnit | AnyUnit | GroupUnit, bool, Flags | None]:
        t = self.peek()
        if t.kind == "STR":
            self.take()
            if not str(t.value):
                raise CqlSyntaxError(f"position {t.pos}: empty word token \"\"")
            return WordUnit(str(t.value)), True, None
        if t.kind == "LB":
            self.take()
            if self.peek().kind == "RB":
                self.take()
                return AnyUnit(), False, None
            spec = self.parse_spec_dnf()
            inner_flags: Flags | None = None
            if self.peek().kind == "FLAGS":  # CQP-style: [ ... %c]
                ftok = self.take()
                inner_flags = Flags(
                    ignore_case="c" in str(ftok.value), fold_diacritics="d" in str(ftok.value)
                )
            self.expect("RB", "']' to close the token specification")
            return spec, True, inner_flags
        if t.kind == "LP":
            self.take()
            alts = [self.parse_sequence(stop=("PIPE", "RP"))]
            while self.peek().kind == "PIPE":
                self.take()
                alts.append(self.parse_sequence(stop=("PIPE", "RP")))
            self.expect("RP", "')' to close the group")
            return GroupUnit(tuple(alts)), False, None
        raise CqlSyntaxError(
            f"position {t.pos}: expected a token — use \"word\", [attr=\"value\"], [] for any token, "
            "or ( … ) for grouping"
        )

    def parse_spec_dnf(self) -> SpecUnit:
        conj = self.parse_conj()
        alts = [conj]
        while self.peek().kind == "PIPE":
            self.take()
            alts.append(self.parse_conj())
        return SpecUnit(tuple(alts))

    def parse_conj(self) -> tuple[Test, ...]:
        tests = [self.parse_test()]
        while self.peek().kind == "AMP":
            self.take()
            tests.append(self.parse_test())
        return tuple(tests)

    def parse_test(self) -> Test:
        t = self.expect("WORD", "an attribute name (word, lemma, pos, xpos, rel, morph, root, pattern)")
        attr = str(t.value).lower()
        if attr not in ATTRS:
            raise CqlSyntaxError(
                f"position {t.pos}: unknown attribute {t.value!r} — supported: {', '.join(ATTRS)}"
            )
        op = self.take()
        if op.kind not in ("EQ", "NEQ"):
            raise CqlSyntaxError(f"position {op.pos}: expected '=' or '!=' after {attr!r}")
        v = self.peek()
        if v.kind == "RE":
            self.take()
            pattern = str(v.value)
            try:
                re.compile(pattern)
            except re.error as exc:
                raise CqlSyntaxError(f"position {v.pos}: invalid regex /{pattern}/ ({exc})") from exc
            return Test(attr=attr, op=str(op.value), value=pattern, regex=True)
        if v.kind == "STR":
            self.take()
            if not str(v.value):
                raise CqlSyntaxError(f"position {v.pos}: empty value in {attr} test")
            return Test(attr=attr, op=str(op.value), value=str(v.value))
        raise CqlSyntaxError(
            f"position {v.pos}: expected \"value\" or /regex/ after {attr} {op.value}"
        )


def parse_cql(query: str) -> CqlQuery:
    """Parse and validate a CQL-lite query string."""
    if not query or not query.strip():
        raise CqlSyntaxError("empty query")
    return _Parser(_lex(query)).parse()


def ast_to_str(q: CqlQuery) -> str:
    """Canonical round-trippable rendering (returned in query metadata)."""
    body = " ".join(_render_element(el) for el in q.sequence)
    return body + (f" within {q.within}" if q.within != "document" else "")


def _render_element(el: Element) -> str:
    def q() -> str:
        if el.qmin == 1 and el.qmax == 1:
            return ""
        if el.qmin == 0 and el.qmax is None:
            return "*"
        if el.qmin == 1 and el.qmax is None:
            return "+"
        if el.qmin == 0 and el.qmax == 1:
            return "?"
        if el.qmax is None:
            return f"{{{el.qmin},}}"
        return f"{{{el.qmin},{el.qmax}}}"

    def fl() -> str:
        f = ("c" if el.flags.ignore_case else "") + ("d" if el.flags.fold_diacritics else "")
        return f"%{f}" if f else ""

    u = el.unit
    if isinstance(u, WordUnit):
        core = f"\"{u.value}\""
    elif isinstance(u, AnyUnit):
        core = "[]"
    elif isinstance(u, SpecUnit):
        conjuncts = []
        for conj in u.dnf:
            conjuncts.append(
                " & ".join(
                    f"{t.attr}{t.op}/{t.value}/" if t.regex else f'{t.attr}{t.op}"{t.value}"'
                    for t in conj
                )
            )
        core = "[" + " | ".join(conjuncts) + "]"
    else:
        alts = [" ".join(_render_element(e) for e in alt) for alt in u.alts]
        core = "(" + " | ".join(alts) + ")"
    return core + q() + fl()


# --------------------------------------------------------------------------- #
# Matching over document token streams
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _TokenView:
    text: str
    lemma: str
    pos: str
    pos_fine: str
    dep_rel: str
    morph: str
    morph_parts: dict[str, str]
    sentence_idx: int
    token_idx: int


def _parse_morph(morph: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for comp in morph.split("|"):
        if not comp:
            continue
        k, sep, v = comp.partition("=")
        if sep:
            parts[k.strip()] = v.strip()
    return parts


def _attr_value(view: _TokenView, attr: str) -> str:
    if attr == "word":
        return view.text
    if attr == "lemma":
        return view.lemma
    if attr == "pos":
        return view.pos
    if attr == "xpos":
        return view.pos_fine
    if attr == "rel":
        return view.dep_rel
    if attr == "morph":
        return view.morph
    return view.morph_parts.get(attr, "")  # root | pattern


def _apply_flags(value: str, flags: Flags) -> str:
    v = value.lower() if flags.ignore_case else value
    if flags.fold_diacritics:
        v = "".join(c for c in unicodedata.normalize("NFD", v) if not unicodedata.combining(c))
    return v


def _wildcard_regex(value: str) -> str:
    out: list[str] = []
    for ch in value:
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _test_matches(t: Test, view: _TokenView, flags: Flags, norm: _Norm | None) -> bool:
    """Authoritative Python-side evaluation of one attribute test.

    Regex runs on raw text (app convention — normalization is skipped for
    regex, mirrored from search_concordance); %c maps to re.IGNORECASE.
    Normalization applies to word/lemma exact and wildcard tests only.
    """
    raw = _attr_value(view, t.attr)
    if t.regex:
        hit = re.search(t.value, raw, re.IGNORECASE if flags.ignore_case else 0) is not None
        return hit if t.op == "=" else not hit
    if norm is not None and t.attr in ("word", "lemma"):
        actual = norm.norm_py(raw)
        pattern = norm.norm_py(t.value)
    else:
        actual, pattern = raw, t.value
    actual = _apply_flags(actual, flags)
    pattern = _apply_flags(pattern, flags)
    if "*" in pattern or "?" in pattern:
        hit = fnmatch.fnmatchcase(actual, pattern)
    else:
        hit = actual == pattern
    return hit if t.op == "=" else not hit


def _spec_matches(unit: SpecUnit, view: _TokenView, flags: Flags, norm: _Norm | None) -> bool:
    return any(all(_test_matches(t, view, flags, norm) for t in conj) for conj in unit.dnf)


def _element_once(
    el: Element,
    stream: list[_TokenView],
    pos: int,
    norm: _Norm | None,
    memo: dict[tuple[str, int, int], set[int]],
) -> set[int]:
    """End positions after matching ``el.unit`` exactly once at ``pos``."""
    key = ("once", id(el), pos)
    hit = memo.get(key)
    if hit is not None:
        return hit
    ends: set[int] = set()
    unit = el.unit
    if isinstance(unit, WordUnit):
        if _test_matches(Test("word", "=", unit.value), stream[pos], el.flags, norm):
            ends = {pos + 1}
    elif isinstance(unit, AnyUnit):
        ends = {pos + 1}
    elif isinstance(unit, SpecUnit):
        if _spec_matches(unit, stream[pos], el.flags, norm):
            ends = {pos + 1}
    else:  # GroupUnit
        for alt in unit.alts:
            ends |= _sequence_ends(alt, stream, pos, norm, memo)
        ends = {e for e in ends if e > pos}  # a repetition unit consumes >= 1 token
    memo[key] = ends
    return ends


def _element_ends(
    el: Element,
    stream: list[_TokenView],
    pos: int,
    norm: _Norm | None,
    memo: dict[tuple[str, int, int], set[int]],
) -> set[int]:
    """All end positions for ``el`` (honouring its quantifier) starting at ``pos``."""
    key = ("rep", id(el), pos)
    hit = memo.get(key)
    if hit is not None:
        return hit
    acc: set[int] = set()
    frontier: set[int] = {pos}
    count = 0
    while True:
        if count >= el.qmin:
            acc |= frontier
        if el.qmax is not None and count >= el.qmax:
            break
        if count >= len(stream) - pos:  # hard termination bound (half-open ends)
            break
        nxt: set[int] = set()
        for p in frontier:
            nxt |= _element_once(el, stream, p, norm, memo)
        if not nxt:
            break
        frontier = nxt
        count += 1
    memo[key] = acc
    return acc


def _sequence_ends(
    seq: tuple[Element, ...],
    stream: list[_TokenView],
    pos: int,
    norm: _Norm | None,
    memo: dict[tuple[str, int, int], set[int]],
) -> set[int]:
    """All end positions reachable from ``pos``; may include ``pos`` itself."""
    frontier: set[int] = {pos}
    for el in seq:
        nxt: set[int] = set()
        for p in frontier:
            nxt |= _element_ends(el, stream, p, norm, memo)
        frontier = nxt
        if not frontier:
            return frontier
    return frontier


def _iter_elements(seq: tuple[Element, ...]):
    for el in seq:
        yield el
        if isinstance(el.unit, GroupUnit):
            for alt in el.unit.alts:
                yield from _iter_elements(alt)


# --------------------------------------------------------------------------- #
# SQL anchor prefilter (conservative superset; Python matcher is authoritative)
# --------------------------------------------------------------------------- #


def _test_sql(t: Test, flags: Flags, norm: _Norm | None) -> ColumnElement[bool] | None:
    """SQL translation of one test for the ANCHOR PREFILTER.

    Returns None when SQL cannot express the test without risking an
    under-match (e.g. %d diacritic folding, which has no SQL counterpart).
    The prefilter must only ever be a superset of the Python match set.
    """
    if t.attr in ("root", "pattern"):
        if t.op != "=" or t.regex:
            return None
        # Superset LIKE (component may sit anywhere in the morph string — the
        # shared _morph_component_cond only matches head components exactly).
        # The Python matcher is authoritative and re-verifies exactly.
        q_like = t.value.replace("*", "%").replace("?", "_")
        return Token.morph.like(f"%{t.attr}={q_like}%")
    col = _ATTR_COLUMNS.get(t.attr)
    if col is None:
        return None
    if t.regex:
        pat = ("(?i)" + t.value) if flags.ignore_case else t.value
        cond = col.op("REGEXP")(pat)
        return cond if t.op == "=" else ~cond
    if flags.fold_diacritics:
        return None
    wildcard = "*" in t.value or "?" in t.value
    use_norm = norm is not None and t.attr in ("word", "lemma")
    colx = norm.sql_expr(col) if use_norm else col
    val = norm.norm_py(t.value) if use_norm else t.value
    if t.op == "=":
        if wildcard:
            if flags.ignore_case:
                return func.lower(colx).like(val.replace("*", "%").replace("?", "_").lower())
            return colx.op("REGEXP")("^" + _wildcard_regex(val) + "$")
        if flags.ignore_case:
            return func.lower(colx) == func.lower(val)
        return colx == val
    # '!=' — negated forms
    if wildcard:
        like = val.replace("*", "%").replace("?", "_")
        if flags.ignore_case:
            return func.lower(colx).notlike(like.lower())
        return ~colx.op("REGEXP")("^" + _wildcard_regex(val) + "$")
    if flags.ignore_case:
        return func.lower(colx) != func.lower(val)
    return colx != val


def _anchor_condition(el: Element, norm: _Norm | None) -> ColumnElement[bool] | None:
    """SQL condition on the first sequence element, or None (scan all tokens)."""
    if el.qmin == 0:
        return None
    unit = el.unit
    if isinstance(unit, WordUnit):
        dnf: tuple[tuple[Test, ...], ...] = ((Test("word", "=", unit.value),),)
    elif isinstance(unit, SpecUnit):
        dnf = unit.dnf
    else:
        return None
    conj_conds: list[ColumnElement[bool]] = []
    for conj in dnf:
        conds: list[ColumnElement[bool]] = []
        for t in conj:
            cond = _test_sql(t, el.flags, norm)
            if cond is None:
                conds = []
                break
            conds.append(cond)
        if conds:
            conj_conds.append(conds[0] if len(conds) == 1 else _and(*conds))
    if not conj_conds:
        return None
    return conj_conds[0] if len(conj_conds) == 1 else _or(*conj_conds)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


async def search_concordance_cql(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    window: int = 5,
    limit: int = 100,
    offset: int = 0,
    document_ids: list[str] | None = None,
    random_sample: int | None = None,
    sample_seed: int | None = None,
    sort: list[dict] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
) -> ConcordanceResult:
    """CQL-lite KWIC search. Raises CqlSyntaxError on invalid queries."""
    parsed = parse_cql(query)

    version_id = await _latest_version_id(session, corpus_id)
    norm = await _resolve_norm(session, corpus_id, normalize=normalize,
                               normalize_arabic=normalize_arabic, zwnj=zwnj)
    # A DISABLED _Norm object must not normalize: matching and the prefilter
    # see None unless the user asked for normalization (legacy flag or v1.2.11).
    match_norm: _Norm | None = norm if norm.enabled else None

    def meta(total_unknown: bool, lines_n: int) -> dict:
        m: dict = {
            "q": query,
            "mode": "cql",
            "window": window,
            "within": parsed.within,
            "parsed": ast_to_str(parsed),
        }
        if norm.enabled:
            if norm.legacy:
                m["normalize_arabic"] = True
            else:
                m["normalize"] = True
                m["normalization"] = _norm_description(norm)
                if norm.lang in ("ur", "fa"):
                    m["zwnj"] = norm.zwnj
            has_regex = any(
                t.regex for el in _iter_elements(parsed.sequence)
                if isinstance(el.unit, SpecUnit)
                for conj in el.unit.dnf for t in conj
            )
            if has_regex:
                m["normalization_scope"] = (
                    "Normalization applies to word/lemma exact and wildcard tests; "
                    "regex tests match raw text."
                )
        if sort:
            m["sort"] = sort
        if random_sample:
            m["random_sample"] = random_sample
            m["sample_seed"] = sample_seed
        if total_unknown:
            m["total_capped"] = True
            m["total_lower_bound"] = lines_n
        return m

    if not version_id:
        return ConcordanceResult(lines=[], total=0, query=meta(False, 0))

    # ---- candidate anchors (first element), or every stream position ----- #
    anchor_cond = _anchor_condition(parsed.sequence[0], match_norm)
    capped = False
    if anchor_cond is not None:
        stmt = (
            select(Token)
            .where(Token.version_id == version_id, anchor_cond)
            .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
        )
        if document_ids is not None:
            stmt = stmt.where(Token.document_id.in_(document_ids))
        stmt = stmt.limit(_CONCORDANCE_FETCH_CAP)
        anchor_rows = (await session.execute(stmt)).scalars().all()
        capped = len(anchor_rows) >= _CONCORDANCE_FETCH_CAP
    else:
        anchor_rows = None

    if anchor_rows is not None and not anchor_rows:
        return ConcordanceResult(lines=[], total=0, query=meta(False, 0))

    # ---- per-document token streams (all tokens, punctuation included) --- #
    if anchor_rows is not None:
        doc_ids = sorted({t.document_id for t in anchor_rows})
    else:
        dstmt = select(Document.id).where(Document.corpus_id == corpus_id)
        if document_ids is not None:
            dstmt = dstmt.where(Document.id.in_(document_ids))
        doc_ids = sorted((await session.scalars(dstmt)).all())

    streams: dict[str, list[_TokenView]] = {}
    index_of: dict[int, int] = {}  # token.id -> stream position within its document
    filename_of: dict[str, str] = {}
    for doc_id in doc_ids:
        rows = (
            await session.execute(
                select(Token, Document.filename)
                .join(Document, Token.document_id == Document.id)
                .where(Token.version_id == version_id, Token.document_id == doc_id)
                .order_by(Token.sentence_idx, Token.token_idx)
            )
        ).all()
        views: list[_TokenView] = []
        for tok, fname in rows:
            index_of[tok.id] = len(views)
            views.append(
                _TokenView(
                    text=tok.text or "",
                    lemma=tok.lemma or "",
                    pos=tok.pos or "",
                    pos_fine=tok.pos_fine or "",
                    dep_rel=tok.dep_rel or "",
                    morph=tok.morph or "",
                    morph_parts=_parse_morph(tok.morph or ""),
                    sentence_idx=tok.sentence_idx,
                    token_idx=tok.token_idx,
                )
            )
        streams[doc_id] = views
        if rows:
            filename_of[doc_id] = fname

    anchors: list[tuple[str, int]] = (
        [(t.document_id, index_of[t.id]) for t in anchor_rows]
        if anchor_rows is not None
        else [(d, i) for d in doc_ids for i in range(len(streams[d]))]
    )

    # ---- match (memo is per document: positions are stream-local) -------- #
    verified: list[tuple[str, int, int]] = []
    current_doc: str | None = None
    memo: dict[tuple[str, int, int], set[int]] = {}
    for doc_id, pos in anchors:
        if doc_id != current_doc:
            current_doc = doc_id
            memo = {}
        for e in _sequence_ends(parsed.sequence, streams[doc_id], pos, match_norm, memo):
            if e > pos:
                verified.append((doc_id, pos, e - 1))

    if parsed.within == "sentence":
        verified = [
            (d, s, e)
            for (d, s, e) in verified
            if streams[d][s].sentence_idx == streams[d][e].sentence_idx
        ]

    # One KWIC line per match start: keep the shortest span when several
    # spans share a start (CQP-like one-match-per-start behaviour).
    best: dict[tuple[str, int], int] = {}
    for d, s, e in verified:
        key = (d, s)
        if key not in best or e < best[key]:
            best[key] = e
    verified = [(d, s, e) for (d, s), e in sorted(best.items())]

    total: int | None = len(verified)
    if capped and anchor_rows is not None:
        total = None

    if random_sample and total:
        import random as _random

        rng = _random.Random(sample_seed)
        k = min(random_sample, len(verified))
        verified = sorted(rng.sample(verified, k))

    # ---- batched sentence-context fetch (KWIC left/right + sort keys) ---- #
    needed_sentences: set[tuple[str, int]] = {
        (d, streams[d][s].sentence_idx) for d, s, _ in verified
    } | {(d, streams[d][e].sentence_idx) for d, _, e in verified}
    sentence_cache: dict[tuple[str, int], list[tuple[str, str, str]]] = {}
    if needed_sentences:
        keys = sorted(needed_sentences)
        CHUNK = 400
        for i in range(0, len(keys), CHUNK):
            chunk = keys[i : i + CHUNK]
            batch_stmt = (
                select(
                    Token.document_id,
                    Token.sentence_idx,
                    Token.token_idx,
                    Token.text,
                    Token.lemma,
                    Token.pos,
                )
                .where(Token.version_id == version_id)
                .where(
                    _or(*[
                        (Token.document_id == d) & (Token.sentence_idx == s)
                        for d, s in chunk
                    ])
                )
                .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
            )
            for doc_id, sent_idx, _tok_idx, text, lemma, pos in (
                await session.execute(batch_stmt)
            ).all():
                sentence_cache.setdefault((doc_id, sent_idx), []).append(
                    (text or "", lemma or "", pos or "")
                )

    lines: list[ConcordanceLine] = []
    for d, s_pos, e_pos in verified:
        stream = streams[d]
        start_view = stream[s_pos]
        end_view = stream[e_pos]
        start_sent = sentence_cache.get((d, start_view.sentence_idx), [])
        end_sent = sentence_cache.get((d, end_view.sentence_idx), [])
        left_texts = [t[0] for t in start_sent]
        right_texts = [t[0] for t in end_sent]
        lines.append(
            ConcordanceLine(
                line_id=f"{d}:{start_view.sentence_idx}:{start_view.token_idx}",
                document_id=d,
                document_filename=filename_of.get(d, ""),
                sentence_idx=start_view.sentence_idx,
                token_idx=start_view.token_idx,
                left=" ".join(left_texts[max(0, start_view.token_idx - window) : start_view.token_idx]),
                node=" ".join(v.text for v in stream[s_pos : e_pos + 1]),
                right=" ".join(right_texts[end_view.token_idx + 1 : end_view.token_idx + 1 + window]),
                pos=start_view.pos,
                lemma=start_view.lemma,
            )
        )

    # ---- KWIC sort (AntConc-style L1/R1/L2/R2, up to 3 levels) ----------- #
    if sort:

        def sort_key(line: ConcordanceLine) -> list[str]:
            sent_tokens = sentence_cache.get((line.document_id, line.sentence_idx), [])
            keys: list[str] = []
            for spec in sort[:3]:
                side = spec.get("side", "right")
                off = max(1, min(3, int(spec.get("offset", 1))))
                if side == "left":
                    keys.append(_sort_token(sent_tokens, line.token_idx - off).lower())
                else:
                    keys.append(_sort_token(sent_tokens, line.token_idx + off).lower())
            return keys

        lines.sort(key=sort_key)

    total_final = total if total is not None else len(verified)
    lines = lines[offset : offset + limit]
    return ConcordanceResult(lines=lines, total=total_final, query=meta(total is None, len(verified)))
