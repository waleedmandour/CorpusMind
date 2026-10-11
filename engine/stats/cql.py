"""CQL-lite: a corpus-query-language front end for the concordance engine.

Phase 1 (no schema change). The grammar is CQP-flavoured, restricted to what
the shipped token schema can honour — it is NOT CQP, and queries do not
"transfer directly" from Sketch Engine / CWB; see the differences table below.

    query     := sequence [ "within" ("sentence" | "s" | "document" | "doc") ]
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
morph (Feats) | root | pattern (Arabic morph layer). ``&`` binds tighter than
``|`` inside a spec (disjunction of conjunctions).

Matching strategy (DECIDED, v1.2.13-2)
--------------------------------------
ONE match per start position: the *earliest-ending* match. Elements are
expanded left-to-right, each trying its candidate end positions in increasing
order (bounded by the quantifier); the first complete accept wins and no
other span from that start is reported. For the canonical literal + gap
patterns (``"the" []* "of"``, ``[lemma="take"] []{0,3} "risk"``) this is
exactly the shortest span per start — CQP's one-match-per-start behaviour —
and gap expansion is linear in the distance to the first accept. Queries
whose nesting makes "earliest in application order" differ from the absolute
shortest span (contrived alternations under quantifiers) report the
leftmost-earliest span; this is documented, deliberate, and pinned by tests.

Span semantics: one KWIC line per match START, carrying the earliest-ending
span. Ambiguous starts do NOT produce one line per span. (v1.2.13-1's
docstring claimed "every distinct span is reported" while the executor kept
the shortest — that contradiction is fixed here; the behaviour was always
one-line-per-start.)

Work budget and deadline (v1.2.13-2)
------------------------------------
Matching runs off the event loop (``asyncio.to_thread``) under an explicit
budget: a step counter (attribute tests + frontier expansions), a max span
length, and a wall-clock deadline. Exceeding the step budget or span bound
raises ``CqlTooExpensive`` (HTTP 422 with an actionable message); exceeding
the deadline raises ``CqlDeadlineExceeded`` (HTTP 504). Regex tests are
screened at parse time for catastrophic nested-quantifier patterns, and the
budget/deadline backstop covers the rest. Students get a stricter budget
(see api/analysis.py).

``within sentence`` bounds the scan: the matcher restricts the stream to the
anchor's sentence and never scans beyond it (cross-sentence spans are
impossible by construction, not filtered after the fact). Default scope is
the document: sequences MAY cross sentence boundaries. Paragraph scope is
NOT available: the ingestion pipeline flattens paragraph markup (documented
limitation).

Differences from CQP (all deliberate — do not assume Sketch Engine/CWB
compatibility):
  * Quoted values are WILDCARD patterns (* = any run, ? = one char), not
    regexes. Regex only via /re/, and unanchored (Python ``re.search``) —
    CQP anchors regexes to the whole token string.
  * Flag placement: %c/%d are accepted both inside the brackets
    (``[word="x" %c]``) and after them (``"x" %c``); CQP only allows some
    positions.
  * Scope: ``within sentence`` / ``within document`` only (``s``/``doc``
    accepted as aliases). CQP's ``within <struct>`` over arbitrary
    structural tags is not supported (no structural annotation stored).
  *morph is a WHOLE-STRING match against the stored Feats string, not a
    substring test — write ``morph="*Animacy=Anim*"`` (wildcards) for a
    substring-style search.
  * Arabic root/pattern match the REAL stored format: dotted roots and
    diacritised patterns as produced by the CAMeL backend, e.g.
    ``[root="ك.ت.ب"]`` (morph strings look like ``root=ك.ت.ب|stem=…|pattern=…``).
  * %c is Unicode-aware case-folding (NFC + ``str.casefold``) on both the
    SQL prefilter and the Python matcher, so école/École, STRASSE/straße,
    οδος/Οδός (final sigma), Москва/МОСКВА all match. Turkish İ/ı are NOT
    fold-equivalent to i/i under Unicode case folding — behaviour is
    consistent between the prefilter and the matcher (both find or both
    don't), but locale-specific folding (Turkish İ↔i) is out of scope.
  * Opt-in CQP-compat mode (``cqp_compat=True`` / request field): quoted
    values become ANCHORED REGEXES (real CQP semantics) instead of
    wildcards; %d still does not apply to regex tests.
  * A repetition unit always consumes at least one token, so ``("a"?)*``-style
    empty loops cannot occur; matches spanning zero tokens are dropped.
  * Punctuation tokens participate in matching as ordinary tokens.
  * ``%d`` folds diacritics for exact/wildcard tests only; regex tests always
    run on raw text (mirroring the app's regex convention). ``normalize=True``
    applies the corpus language's normalizer to word/lemma exact/wildcard
    tests only.

Architecture (mirrors the v1.0.1 phrase-verification pattern in
stats.service.search_concordance): a SQL *prefilter* over the first element
generates candidate anchor tokens (conservative superset — when a test cannot
be expressed in SQL under the active flag combination it is dropped from the
prefilter, never approximated); the matcher then verifies the full query over
each candidate document's token stream. The candidate fetch is bounded by the
same _CONCORDANCE_FETCH_CAP as phrase queries; hitting it marks
``total_capped`` in the query metadata (total is then a lower bound).
Match spans are cached per (corpus, query, version, filters) so pagination
does not re-run the matcher, and each page fetches KWIC context for its own
spans only. KWIC context, seeded sampling, AntConc-style sorting and
pagination reuse the concordance conventions so CQL results render
identically in the client.
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from collections import OrderedDict
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
    check_regex_safe,
)


class CqlSyntaxError(ValueError):
    """A CQL-lite query could not be parsed or validated."""


class CqlTooExpensive(ValueError):
    """The query exceeded the matcher work budget or span bound.

    Surfaced as HTTP 422 with an actionable message (bound the gaps,
    add a literal anchor, scope with ``within sentence``).
    """


class CqlDeadlineExceeded(TimeoutError):
    """The query exceeded the matcher wall-clock deadline. HTTP 504."""


# --------------------------------------------------------------------------- #
# Work budget / deadline (v1.2.13-2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MatchLimits:
    """Matcher resource limits. Students get a stricter set (see below)."""

    max_steps: int = 1_500_000   # attribute tests + frontier expansions
    max_span: int = 5_000        # longest span a single match may cover (tokens)
    deadline_s: float = 20.0     # wall-clock budget for the whole match phase


#: Classroom role limits — deliberately stricter than the teacher's defaults
#: so a classroom of concurrent students cannot saturate the CPU.
STUDENT_MATCH_LIMITS = MatchLimits(max_steps=300_000, max_span=1_000, deadline_s=10.0)


class _Budget:
    """Mutable step counter + deadline for one match phase."""

    __slots__ = ("max_steps", "max_span", "deadline", "steps")

    def __init__(self, limits: MatchLimits) -> None:
        self.max_steps = limits.max_steps
        self.max_span = limits.max_span
        self.deadline = time.monotonic() + limits.deadline_s
        self.steps = 0

    def spend(self, n: int = 1) -> None:
        self.steps += n
        if self.steps > self.max_steps:
            raise CqlTooExpensive(
                f"query exceeded the matcher work budget ({self.max_steps:,} steps). "
                "Narrow it: add a literal anchor (a quoted word), bound unbounded "
                "gaps ([]* → []{0,50}), or scope with 'within sentence'."
            )
        # Deadline checked every ~1k steps; a single step is O(token length),
        # so between checks we never accumulate more than microseconds of
        # non-regex work. Catastrophic regexes are rejected at parse time.
        if (self.steps & 0x3FF) == 0 and time.monotonic() > self.deadline:
            raise CqlDeadlineExceeded(
                "query exceeded the matcher wall-clock deadline — narrow the "
                "pattern (bound gaps, add a literal anchor, 'within sentence')"
            )

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline:
            raise CqlDeadlineExceeded(
                "query exceeded the matcher wall-clock deadline — narrow the "
                "pattern (bound gaps, add a literal anchor, 'within sentence')"
            )


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
        self.compat = False

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
            t = self.expect("WORD", "'sentence' (or 's') or 'document' (or 'doc') after 'within'")
            scope = str(t.value).lower()
            # v1.2.13-2: CQP-style aliases — 'within s' == 'within sentence',
            # 'within doc' == 'within document'. Paragraph scope does not
            # exist (markup flattened at ingestion).
            if scope in ("sentence", "s"):
                within = "sentence"
            elif scope in ("document", "doc"):
                within = "document"
            else:
                raise CqlSyntaxError(
                    f"position {t.pos}: 'within' supports 'sentence' (or 's') or "
                    f"'document' (or 'doc') (got {t.value!r}); "
                    "paragraph markup is flattened at ingestion and cannot be queried"
                )
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
            # v1.2.13-2: consecutive flag tokens merge ("%c%d" lexes as two
            # tokens; "%cd" as one) — both spellings are accepted.
            seen_c, seen_d = str(ftok.value).count("c"), str(ftok.value).count("d")
            while self.peek().kind == "FLAGS":
                ftok2 = self.take()
                seen_c += str(ftok2.value).count("c")
                seen_d += str(ftok2.value).count("d")
            flags = Flags(ignore_case=seen_c > 0, fold_diacritics=seen_d > 0)
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
            if self.compat:
                # v1.2.13-2 CQP-compat: a quoted token is an ANCHORED REGEX on
                # word (real CQP semantics). Wrapped so both the Python
                # matcher (re.search) and the SQL REGEXP prefilter anchor
                # identically; rendered canonically as [word=/^(?:…)$/].
                _check_regex_safe(str(t.value), t.pos)
                test = Test("word", "=", f"^(?:{t.value})$", regex=True)
                return SpecUnit(((test,),)), True, None
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
            _check_regex_safe(pattern, v.pos)
            return Test(attr=attr, op=str(op.value), value=pattern, regex=True)
        if v.kind == "STR":
            self.take()
            if not str(v.value):
                raise CqlSyntaxError(f"position {v.pos}: empty value in {attr} test")
            # v1.2.13-2 opt-in CQP-compat: quoted values are ANCHORED REGEXES
            # (real CQP semantics) instead of wildcard patterns.
            if self.compat:
                _check_regex_safe(str(v.value), v.pos)
                return Test(attr=attr, op=str(op.value), value=f"^(?:{v.value})$", regex=True)
            return Test(attr=attr, op=str(op.value), value=str(v.value))
        raise CqlSyntaxError(
            f"position {v.pos}: expected \"value\" or /regex/ after {attr} {op.value}"
        )


def parse_cql(query: str, *, cqp_compat: bool = False) -> CqlQuery:
    """Parse and validate a CQL-lite query string.

    With ``cqp_compat=True`` quoted values are treated as anchored regexes
    (real CQP semantics) instead of wildcard patterns — see the module
    docstring's differences table.
    """
    if not query or not query.strip():
        raise CqlSyntaxError("empty query")
    parser = _Parser(_lex(query))
    parser.compat = cqp_compat
    return parser.parse()


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


def _casefold_u(value: str) -> str:
    """Unicode-aware case-insensitive key: NFC(str.casefold(x)).

    Must stay EXACTLY in sync with the SQL ``unicase()`` function registered
    in storage/session.py — the prefilter/matcher superset property depends
    on both layers folding identically (French é/É, German ß/SS, Greek
    ς/σ/Σ, Cyrillic а/А all fold; Turkish İ/ı deliberately do not fold to
    i — locale-specific case folding is out of scope, documented).
    """
    return unicodedata.normalize("NFC", value.casefold())


def _apply_flags(value: str, flags: Flags) -> str:
    # %c is Unicode case FOLDING (not ASCII lower()): this is what makes the
    # SQL prefilter (unicase()) and the Python matcher agree on non-ASCII.
    v = _casefold_u(value) if flags.ignore_case else value
    if flags.fold_diacritics:
        v = "".join(c for c in unicodedata.normalize("NFD", v) if not unicodedata.combining(c))
    return v


def _wildcard_regex(value: str) -> str:
    """THE wildcard→regex translation (v1.2.13-2: single source of truth).

    Used by BOTH the Python matcher and the SQL REGEXP prefilter so the two
    layers can never drift (fnmatch was removed: it treats ``[...]`` as a
    character class, so "a[bc]*" matched 'abd' in Python while the SQL
    prefilter treated the brackets literally).
    """
    out: list[str] = []
    for ch in value:
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


# Catastrophic-backtracking screen (heuristic): a quantifier applied to a
# group that itself ends in a quantifier — the classic (a+)+ / (a|a)* bomb
# family. The screen lives in stats/service.check_regex_safe (shared with
# the simple concordance's regex level); the step budget and deadline below
# remain the backstop for anything the screen misses. A single re.search
# call is atomic (documented residual risk, bounded by token length for
# non-pathological patterns).


def _check_regex_safe(pattern: str, pos: int = 0) -> None:
    """Reject catastrophic regexes at parse time (CqlSyntaxError with position)."""
    try:
        check_regex_safe(pattern)
    except ValueError as exc:
        raise CqlSyntaxError(f"position {pos}: {exc}") from exc


def _test_matches(t: Test, view: _TokenView, flags: Flags, norm: _Norm | None) -> bool:
    """Authoritative Python-side evaluation of one attribute test.

    Regex runs on raw text (app convention — normalization is skipped for
    regex, mirrored from search_concordance); %c maps to re.IGNORECASE.
    Normalization applies to word/lemma exact and wildcard tests only.
    Wildcards go through _wildcard_regex + fullmatch (single helper shared
    with the SQL prefilter — never fnmatch, whose [..] classes diverge).
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
        hit = re.fullmatch(_wildcard_regex(pattern), actual) is not None
    else:
        hit = actual == pattern
    return hit if t.op == "=" else not hit


def _spec_matches(unit: SpecUnit, view: _TokenView, flags: Flags, norm: _Norm | None) -> bool:
    return any(all(_test_matches(t, view, flags, norm) for t in conj) for conj in unit.dnf)


# --------------------------------------------------------------------------- #
# The matcher: earliest-end match per start, under an explicit work budget.
#
# Strategy (documented in the module docstring): elements are expanded
# left-to-right; each element yields candidate end positions lazily, in
# application-count (BFS) order with each level sorted — for single-token
# units (word/spec/any, the overwhelmingly common case) that is exactly
# increasing position order. The DFS stops at the FIRST complete accept, so
# an unbounded gap ("the" []* "of") costs only up to the first accept
# ("linear for gaps") instead of enumerating every span (the v1.2.13-1
# O(n^2) time / O(n^2) memory behaviour — 20K tokens: 23 s / 1.4 GB, 50K
# OOM — is fixed by construction).
#
# `within sentence` bounds every scan to the anchor's sentence: the stream
# is cut at the sentence end and the matcher cannot scan beyond it.
# --------------------------------------------------------------------------- #


def _sentence_bounds(stream: list[_TokenView]) -> dict[int, int]:
    """sentence_idx -> exclusive end position of that sentence in the stream.

    The stream is ordered by (sentence_idx, token_idx), so the last write
    per sentence_idx is the position after its final token.
    """
    bounds: dict[int, int] = {}
    for i, v in enumerate(stream):
        bounds[v.sentence_idx] = i + 1
    return bounds


def _element_once(
    el: Element,
    stream: list[_TokenView],
    pos: int,
    hi: int,
    norm: _Norm | None,
    memo: dict[tuple[int, int], set[int]] | None,
    budget: _Budget,
) -> set[int]:
    """End positions after matching ``el.unit`` exactly once at ``pos``."""
    budget.spend()  # every attribute test is a budgeted work unit
    unit = el.unit
    if isinstance(unit, WordUnit):
        return {pos + 1} if _test_matches(Test("word", "=", unit.value), stream[pos], el.flags, norm) else set()
    if isinstance(unit, AnyUnit):
        return {pos + 1}
    if isinstance(unit, SpecUnit):
        return {pos + 1} if _spec_matches(unit, stream[pos], el.flags, norm) else set()

    # GroupUnit — union over alternatives. Alternatives are sequences, so
    # resolve them with the bounded reachable-set walk. Group results are the
    # only memoized once-results (word/spec/any are a single cheap attribute
    # test — memoizing them per position is what blew up memory in 1.2.13-1),
    # and only while small, so a pathological group cannot balloon the cache.
    key = (id(el.unit), pos)
    if memo is not None:
        hit = memo.get(key)
        if hit is not None:
            return hit
    ends: set[int] = set()
    for alt in unit.alts:
        ends |= _sequence_reachable(alt, stream, pos, hi, norm, memo, budget, hi)
    ends = {e for e in ends if e > pos}  # a repetition unit consumes >= 1 token
    if memo is not None and len(ends) <= 32:
        memo[key] = ends
    return ends


def _sequence_reachable(
    seq: tuple[Element, ...],
    stream: list[_TokenView],
    pos: int,
    hi: int,
    norm: _Norm | None,
    memo: dict[int, set[int]] | None,
    budget: _Budget,
    cap: int,
) -> set[int]:
    """All end positions of ``seq`` reachable from ``pos`` (bounded by cap/budget).

    Used for group alternatives. Zero-width ends (``pos`` itself) may be
    included when every element has a qmin of 0.
    """
    frontier: set[int] = {pos}
    budget.spend()
    for el in seq:
        nxt: set[int] = set()
        for q in frontier:
            # Per-position element ends via the bounded level walk.
            for e in _element_ends_level(el, stream, q, min(hi, cap), norm, memo, budget, want_all=True):
                nxt.add(e)
        frontier = nxt
        if not frontier:
            return frontier
    return frontier


def _element_ends_level(
    el: Element,
    stream: list[_TokenView],
    pos: int,
    max_reach: int,
    norm: _Norm | None,
    memo: dict[int, set[int]] | None,
    budget: _Budget,
    want_all: bool,
):
    """Yield ends of ``el`` at ``pos`` in application-count (BFS) order.

    Each application consumes at least one token, so levels ascend; within a
    level, ends are yielded sorted. When ``want_all`` is set the generator is
    fully consumed by the caller (group-alternative resolution); the main DFS
    consumes it lazily and stops at the first accept.
    """
    budget.spend()
    if el.qmin == 0:
        yield pos
    frontier: set[int] = {pos}
    seen: set[int] = set()
    count = 0
    while True:
        if el.qmax is not None and count >= el.qmax:
            return
        if count >= max_reach - pos:  # every further application overshoots
            return
        budget.spend()
        nxt: set[int] = set()
        for q in frontier:
            for e in _element_once(el, stream, q, max_reach, norm, memo, budget):
                if pos < e <= max_reach:
                    nxt.add(e)
        if not nxt:
            return
        count += 1
        frontier = nxt
        if count >= el.qmin:
            for e in sorted(nxt):
                if e not in seen:
                    seen.add(e)
                    yield e


def _match_earliest(
    seq: tuple[Element, ...],
    stream: list[_TokenView],
    start: int,
    hi: int,
    norm: _Norm | None,
    memo: dict[int, set[int]] | None,
    budget: _Budget,
) -> int | None:
    """Earliest-ending match of ``seq`` at ``start`` (exclusive end), or None.

    DFS over elements, each consuming its candidate ends in increasing
    (application-count) order; the first complete accept wins — one match
    per start, exactly as documented.
    """
    n = len(seq)

    def go(i: int, pos: int) -> int | None:
        if i == n:
            return pos
        for e in _element_ends_level(seq[i], stream, pos, hi, norm, memo, budget, want_all=False):
            r = go(i + 1, e)
            if r is not None:
                return r
        return None

    return go(0, start)


def _match_all(
    parsed: CqlQuery,
    streams: dict[str, list[_TokenView]],
    anchors: list[tuple[str, int]],
    norm: _Norm | None,
    limits: MatchLimits,
) -> list[tuple[str, int, int]]:
    """Match every anchor start; returns (doc, start, end_inclusive) spans.

    Pure CPU — runs inside asyncio.to_thread. Raises CqlTooExpensive /
    CqlDeadlineExceeded when the budget or deadline is hit.
    """
    budget = _Budget(limits)
    per_sentence = parsed.within == "sentence"
    out: list[tuple[str, int, int]] = []
    bounds_cache: dict[str, dict[int, int]] = {}
    memo: dict[tuple[int, int], set[int]] = {}  # small GroupUnit once-results, per document
    current_doc: str | None = None
    for doc_id, pos in anchors:
        if doc_id != current_doc:
            current_doc = doc_id
            memo = {}
        stream = streams[doc_id]
        hi = len(stream)
        if per_sentence:
            b = bounds_cache.get(doc_id)
            if b is None:
                b = _sentence_bounds(stream)
                bounds_cache[doc_id] = b
            # never scan beyond the anchor's sentence
            hi = b.get(stream[pos].sentence_idx, len(stream))
        end = _match_earliest(parsed.sequence, stream, pos, hi, norm, memo, budget)
        if end is not None and end - pos <= limits.max_span:
            out.append((doc_id, pos, end - 1))
        # Per-anchor deadline check: guards low-step/high-time patterns too.
        budget.check_deadline()
    return out


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

    v1.2.13-2: %c comparisons go through the Unicode-aware ``unicase()``
    SQL function (NFC + casefold, registered in storage/session.py and kept
    exactly in sync with the Python ``_casefold_u``) — SQLite's built-in
    ``lower()``/``LIKE`` are ASCII-only, which silently dropped non-ASCII
    candidates ('"école" %c' found 1 of 3, '"москва" %c' 1 of 2).
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
        # REGEXP is the registered Python-re function (Unicode-aware); with
        # (?i) it folds exactly like the Python matcher's re.IGNORECASE.
        pat = ("(?i)" + t.value) if flags.ignore_case else t.value
        cond = col.op("REGEXP")(pat)
        return cond if t.op == "=" else ~cond
    if flags.fold_diacritics:
        return None
    wildcard = "*" in t.value or "?" in t.value
    use_norm = norm is not None and t.attr in ("word", "lemma")
    colx = norm.sql_expr(col) if use_norm else col
    val = norm.norm_py(t.value) if use_norm else t.value
    if flags.ignore_case:
        # Unicode-aware superset: identical folding on both layers.
        if wildcard:
            if t.op == "=":
                # LIKE over casefolded keys: '_'/'%' over-match where SQLite
                # LIKE differs from a strict wildcard regex — safe for '='
                # (superset), and the Python matcher re-verifies exactly.
                like = _casefold_u(val).replace("*", "%").replace("?", "_")
                return func.unicase(colx).like(like)
            # '!=' must never UNDER-match, and NOT-LIKE would (LIKE '_' is
            # wider than a literal '_'): fall back to a full scan instead.
            return None
        if t.op == "=":
            return func.unicase(colx) == func.unicase(val)
        return func.unicase(colx) != func.unicase(val)
    if t.op == "=":
        if wildcard:
            return colx.op("REGEXP")("^" + _wildcard_regex(val) + "$")
        return colx == val
    # '!=' — negated forms. REGEXP is the exact Python-semantics negation
    # (NOT-LIKE would under-match: LIKE '_' is wider than a literal '_').
    if wildcard:
        return ~colx.op("REGEXP")("^" + _wildcard_regex(val) + "$")
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
# Match-span service (P2 refactor): one reusable entry point for every
# consumer — concordance, export, AI tools, frequency/collocation/dispersion
# over a CQL node, subcorpus-by-CQL.
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CqlMatchSet:
    """Result of ``find_cql_spans``: spans + the streams needed to use them.

    ``spans`` holds (document_id, start_pos, end_pos) INCLUSIVE stream
    positions (one earliest-ending match per start, in ascending order).
    """

    spans: list[tuple[str, int, int]]
    streams: dict[str, list[_TokenView]]
    filenames: dict[str, str]
    version_id: str
    parsed: CqlQuery
    capped: bool  # anchor fetch hit _CONCORDANCE_FETCH_CAP (total is a lower bound)

    def node_views(self):
        """Yield the token views covered by each match span (the KWIC node)."""
        for d, s, e in self.spans:
            yield self.streams[d][s : e + 1]

    def start_views(self):
        """Yield the first token view of each match (one per span)."""
        for d, s, _ in self.spans:
            yield self.streams[d][s]

    def per_document(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d, _s, _e in self.spans:
            counts[d] = counts.get(d, 0) + 1
        return counts


# Span cache: pagination must not re-run the matcher for every page. Keyed by
# everything that changes the span set; capped LRU with a TTL and a global
# span ceiling so memory stays bounded.
_SPAN_CACHE: "OrderedDict[tuple, tuple[float, list[tuple[str, int, int]], bool]]" = OrderedDict()
_SPAN_CACHE_MAX_ENTRIES = 24
_SPAN_CACHE_TTL_S = 600.0
_SPAN_CACHE_MAX_SPANS = 2_000_000


def _span_cache_key(
    corpus_id: str,
    version_id: str,
    parsed: CqlQuery,
    document_ids: list[str] | None,
    norm: _Norm | None,
    cqp_compat: bool,
) -> tuple:
    return (
        corpus_id,
        version_id,
        ast_to_str(parsed),
        parsed.within,
        tuple(sorted(document_ids)) if document_ids is not None else None,
        (norm.enabled, norm.lang, norm.legacy, norm.zwnj) if norm is not None else None,
        cqp_compat,
    )


def _span_cache_get(key: tuple) -> tuple[list[tuple[str, int, int]], bool] | None:
    hit = _SPAN_CACHE.get(key)
    if hit is None:
        return None
    ts, spans, capped = hit
    if time.monotonic() - ts > _SPAN_CACHE_TTL_S:
        _SPAN_CACHE.pop(key, None)
        return None
    _SPAN_CACHE.move_to_end(key)
    return spans, capped


def _span_cache_put(key: tuple, spans: list[tuple[str, int, int]], capped: bool) -> None:
    total = sum(len(v[1]) for v in _SPAN_CACHE.values())
    while _SPAN_CACHE and (
        len(_SPAN_CACHE) >= _SPAN_CACHE_MAX_ENTRIES or total + len(spans) > _SPAN_CACHE_MAX_SPANS
    ):
        _, (_ts, old, _c) = _SPAN_CACHE.popitem(last=False)
        total -= len(old)
    _SPAN_CACHE[key] = (time.monotonic(), spans, capped)


def _span_cache_clear() -> None:
    """Test/admin hook: drop the span cache."""
    _SPAN_CACHE.clear()


async def _load_streams(
    session: AsyncSession,
    version_id: str,
    doc_ids: list[str],
) -> tuple[dict[str, list[_TokenView]], dict[str, str], dict[int, int]]:
    """Load per-document token streams (ordered views) for the given docs."""
    streams: dict[str, list[_TokenView]] = {}
    filename_of: dict[str, str] = {}
    index_of: dict[int, int] = {}
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
    return streams, filename_of, index_of


async def find_cql_spans(
    session: AsyncSession,
    corpus_id: str,
    query: str,
    *,
    document_ids: list[str] | None = None,
    normalize: bool | None = None,
    normalize_arabic: bool = False,
    zwnj: str = "keep",
    limits: MatchLimits | None = None,
    cqp_compat: bool = False,
    use_cache: bool = True,
) -> CqlMatchSet:
    """Reusable CQL match service: parse → prefilter → match → spans.

    Returns the earliest-ending span per start (ascending) plus the token
    streams, so consumers (concordance, export, AI tools, statistics over a
    CQL node, subcorpus-by-CQL) share one implementation with the same
    budget/deadline guards. Raises CqlSyntaxError / CqlTooExpensive /
    CqlDeadlineExceeded.
    """
    parsed = parse_cql(query, cqp_compat=cqp_compat)
    if limits is None:
        limits = MatchLimits()
    version_id = await _latest_version_id(session, corpus_id)
    norm = await _resolve_norm(session, corpus_id, normalize=normalize,
                               normalize_arabic=normalize_arabic, zwnj=zwnj)
    match_norm: _Norm | None = norm if norm.enabled else None
    if not version_id:
        return CqlMatchSet(spans=[], streams={}, filenames={}, version_id="",
                           parsed=parsed, capped=False)

    key = _span_cache_key(corpus_id, version_id, parsed, document_ids, match_norm, cqp_compat)
    cached = _span_cache_get(key) if use_cache else None
    if cached is not None:
        spans, capped = cached
        # Streams are reloaded on demand for the docs the consumer needs.
        doc_ids = sorted({d for d, _s, _e in spans})
        streams, filename_of, _ = await _load_streams(session, version_id, doc_ids)
        return CqlMatchSet(spans=spans, streams=streams, filenames=filename_of,
                           version_id=version_id, parsed=parsed, capped=capped)

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
        spans: list[tuple[str, int, int]] = []
        _span_cache_put(key, spans, capped)
        return CqlMatchSet(spans=[], streams={}, filenames={}, version_id=version_id,
                           parsed=parsed, capped=capped)

    if anchor_rows is not None:
        doc_ids = sorted({t.document_id for t in anchor_rows})
    else:
        dstmt = select(Document.id).where(Document.corpus_id == corpus_id)
        if document_ids is not None:
            dstmt = dstmt.where(Document.id.in_(document_ids))
        doc_ids = sorted((await session.scalars(dstmt)).all())

    streams, filename_of, index_of = await _load_streams(session, version_id, doc_ids)
    anchors: list[tuple[str, int]] = (
        [(t.document_id, index_of[t.id]) for t in anchor_rows]
        if anchor_rows is not None
        else [(d, i) for d in doc_ids for i in range(len(streams[d]))]
    )

    # ---- match: pure CPU, OFF the event loop, under an explicit budget ---- #
    spans = await asyncio.to_thread(_match_all, parsed, streams, anchors, match_norm, limits)
    _span_cache_put(key, spans, capped)
    return CqlMatchSet(spans=spans, streams=streams, filenames=filename_of,
                       version_id=version_id, parsed=parsed, capped=capped)


async def _fetch_sentences(
    session: AsyncSession,
    version_id: str,
    needed: set[tuple[str, int]],
) -> dict[tuple[str, int], list[tuple[str, str, str]]]:
    """Batched sentence fetch for KWIC context and sort keys."""
    sentence_cache: dict[tuple[str, int], list[tuple[str, str, str]]] = {}
    if not needed:
        return sentence_cache
    keys = sorted(needed)
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
    return sentence_cache


def _build_lines(
    spans: list[tuple[str, int, int]],
    streams: dict[str, list[_TokenView]],
    filename_of: dict[str, str],
    sentence_cache: dict[tuple[str, int], list[tuple[str, str, str]]],
    window: int,
) -> list[ConcordanceLine]:
    lines: list[ConcordanceLine] = []
    for d, s_pos, e_pos in spans:
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
    return lines


def _kwic_sort(
    lines: list[ConcordanceLine],
    sort: list[dict],
    sentence_cache: dict[tuple[str, int], list[tuple[str, str, str]]],
) -> None:
    """AntConc-style L1/R1/L2/R2 sort, up to 3 levels (in place)."""

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
    limits: MatchLimits | None = None,
    cqp_compat: bool = False,
) -> ConcordanceResult:
    """CQL-lite KWIC search.

    Raises CqlSyntaxError on invalid queries, CqlTooExpensive when the work
    budget / span bound is hit (HTTP 422), CqlDeadlineExceeded on the
    wall-clock deadline (HTTP 504). Matching runs in a worker thread.

    Paging (v1.2.13-2): match spans are computed once (and cached per
    corpus+query+version), the page is SLICED FIRST, and sentence context is
    fetched only for that page's spans — never for the whole match set. KWIC
    sort still needs every line's context (AntConc-style L1/R1 keys), so
    sorted requests keep the full-context build.
    """
    match_set = await find_cql_spans(
        session, corpus_id, query,
        document_ids=document_ids, normalize=normalize,
        normalize_arabic=normalize_arabic, zwnj=zwnj,
        limits=limits, cqp_compat=cqp_compat,
    )
    parsed = match_set.parsed
    version_id = match_set.version_id
    norm = await _resolve_norm(session, corpus_id, normalize=normalize,
                               normalize_arabic=normalize_arabic, zwnj=zwnj)

    def meta(total_unknown: bool, lines_n: int) -> dict:
        m: dict = {
            "q": query,
            "mode": "cql",
            "window": window,
            "within": parsed.within,
            "parsed": ast_to_str(parsed),
            "strategy": "earliest-end per start",
        }
        if cqp_compat:
            m["cqp_compat"] = True
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
        if not sort:
            m["page"] = {"offset": offset, "limit": limit, "context_for_page_only": True}
        if total_unknown:
            m["total_capped"] = True
            m["total_lower_bound"] = lines_n
        return m

    spans = match_set.spans
    total: int | None = len(spans)
    if match_set.capped:
        total = None

    if random_sample and total:
        import random as _random

        rng = _random.Random(sample_seed)
        k = min(random_sample, len(spans))
        spans = sorted(rng.sample(spans, k))

    if not spans:
        return ConcordanceResult(lines=[], total=total if total is not None else 0,
                                 query=meta(total is None, 0))

    if sort:
        # Sorting needs every line's context (L1/R1 keys) — full build.
        streams = match_set.streams
        needed: set[tuple[str, int]] = set()
        for d, s, e in spans:
            needed.add((d, streams[d][s].sentence_idx))
            needed.add((d, streams[d][e].sentence_idx))
        sentence_cache = await _fetch_sentences(session, version_id, needed)
        lines = _build_lines(spans, streams, match_set.filenames, sentence_cache, window)
        _kwic_sort(lines, sort, sentence_cache)
        total_final = total if total is not None else len(spans)
        return ConcordanceResult(lines=lines[offset : offset + limit],
                                 total=total_final, query=meta(total is None, len(spans)))

    # ---- paged path: slice FIRST, fetch context for the page only -------- #
    page_spans = spans[offset : offset + limit]
    page_docs = sorted({d for d, _s, _e in page_spans})
    lines: list[ConcordanceLine] = []
    if page_spans:
        streams = match_set.streams
        # On a span-cache hit find_cql_spans only loaded the docs that had
        # spans overall; make sure every PAGE doc's stream is present.
        missing = [d for d in page_docs if d not in streams]
        if missing:
            extra_streams, extra_filenames, _ = await _load_streams(session, version_id, missing)
            streams.update(extra_streams)
            match_set.filenames.update(extra_filenames)
        needed = set()
        for d, s, e in page_spans:
            needed.add((d, streams[d][s].sentence_idx))
            needed.add((d, streams[d][e].sentence_idx))
        sentence_cache = await _fetch_sentences(session, version_id, needed)
        lines = _build_lines(page_spans, streams, match_set.filenames, sentence_cache, window)
    total_final = total if total is not None else len(spans)
    return ConcordanceResult(lines=lines, total=total_final, query=meta(total is None, len(spans)))
