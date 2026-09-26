"""UD v2 universal dependency relation inventory (v1.2.7, §2).

The 37 UD v2 universal relations, grouped by grammatical function for
corpus profiling, with plain-language descriptions for the UI.

Grouping follows the functional sections of the UD v2 documentation
(https://universaldependencies.org/u/dep/ — Nivre et al. 2016/2020), with
one pragmatic deviation noted below. Relation subtypes (e.g. ``nsubj:pass``,
``acl:relcl``) are collapsed onto their base relation by the profiler —
subtypes carry language-specific granularity the universal inventory
deliberately does not commit to.

Citation for results produced with this inventory:
    Nivre, J., de Marneffe, M.-C., Ginter, F., Hajič, J., Manning, C.D.,
    Pyysalo, S., Schuster, S., Tyers, F., & Zeman, D. (2020). Universal
    Dependencies v2: An evolving multilingual treebank collection.
    In Proceedings of LREC 2020. https://universaldependencies.org
"""

from __future__ import annotations

# Ordered functional groups — the UI renders them in this order.
UD_RELATION_GROUPS: dict[str, str] = {
    "core_arguments": "Core arguments",
    "noncore_arguments": "Non-core arguments",
    "nominal_dependents": "Nominal dependents",
    "clausal_dependents": "Clausal dependents",
    "modifiers": "Modifiers",
    "function_words": "Function words",
    "coordination": "Coordination",
    "mwe": "Fixed multiword expressions",
    "loose_joinings": "Loose joinings & other",
    "punctuation": "Punctuation",
    "clause_head": "Clause head (root)",
}

# relation -> (group key, short description). All 37 UD v2 relations are
# listed exactly once; a missing relation would be a coverage bug caught
# by test_v127_ud_sfg.py::test_ud_inventory_covers_37_relations.
UD_RELATION_INFO: dict[str, tuple[str, str]] = {
    # Core arguments
    "nsubj":  ("core_arguments", "nominal subject"),
    "obj":    ("core_arguments", "direct object"),
    "iobj":   ("core_arguments", "indirect object"),
    "csubj":  ("core_arguments", "clausal subject"),
    "ccomp":  ("core_arguments", "clausal complement"),
    "xcomp":  ("core_arguments", "open clausal complement"),
    # Non-core arguments
    "obl":        ("noncore_arguments", "oblique nominal"),
    "vocative":   ("noncore_arguments", "vocative"),
    "dislocated": ("noncore_arguments", "dislocated element"),
    # Nominal dependents
    "nmod":     ("nominal_dependents", "nominal modifier"),
    "appos":    ("nominal_dependents", "appositional modifier"),
    "nummod":   ("nominal_dependents", "numeric modifier"),
    "clf":      ("nominal_dependents", "classifier"),
    "acl":      ("nominal_dependents", "clausal modifier of a noun"),
    "compound": ("nominal_dependents", "compound"),
    # Clausal dependents
    "advcl":     ("clausal_dependents", "adverbial clause modifier"),
    "discourse": ("clausal_dependents", "discourse element"),
    "parataxis": ("clausal_dependents", "parataxis"),
    # Modifiers — advmod sits here (adj/verb modification) rather than
    # under clausal dependents; a functional, analysis-facing grouping.
    "amod":   ("modifiers", "adjectival modifier"),
    "advmod": ("modifiers", "adverbial modifier"),
    "det":    ("modifiers", "determiner"),
    # Function words
    "aux":  ("function_words", "auxiliary"),
    "cop":  ("function_words", "copula"),
    "case": ("function_words", "case marking"),
    "mark": ("function_words", "marker (subordination)"),
    "cc":   ("function_words", "coordinating conjunction"),
    # Coordination
    "conj": ("coordination", "conjunct"),
    # Fixed multiword expressions
    "fixed":    ("mwe", "fixed multiword expression"),
    "goeswith": ("mwe", "goes with (typos/splits)"),
    # Loose joinings & other
    "flat":       ("loose_joinings", "flat (names, dates, numbers)"),
    "list":       ("loose_joinings", "list"),
    "orphan":     ("loose_joinings", "orphan (ellipsis residue)"),
    "reparandum": ("loose_joinings", "reparandum (self-correction)"),
    "expl":       ("core_arguments", "expletive (placeholder subject/object)"),
    "dep":        ("loose_joinings", "unspecified dependency"),
    # Punctuation + root
    "punct": ("punctuation", "punctuation"),
    "root":  ("clause_head", "root of the clause"),
}

UD_RELATIONS: tuple[str, ...] = tuple(UD_RELATION_INFO)


# Non-UD labels → universal base relations. The bundled spaCy English
# models use the ClearNLP/OntoNotes scheme (ROOT, dobj, pobj, prep, attr,
# acomp, auxpass, nsubjpass, ...), while the CAMeL Arabic pipeline and
# future UD models emit proper UD labels. The profiler normalizes BOTH
# onto the universal inventory — a documented, label-level approximation
# (structural reanalysis like copular ROOT reassignment is out of scope).
_NON_UD_ALIASES: dict[str, str] = {
    # spaCy ClearNLP / OntoNotes basic English scheme
    "nsubjpass": "nsubj",
    "csubjpass": "csubj",
    "dobj": "obj",
    "dative": "iobj",
    "pobj": "obl",
    "oprd": "obl",
    "tmod": "obl",
    "npmod": "nmod",
    "prep": "case",
    "agent": "case",
    "possessive": "case",
    "auxpass": "aux",
    "acomp": "xcomp",
    "attr": "nmod",
    "poss": "nmod",
    "nn": "compound",
    "number": "nummod",
    "predet": "det",
    "preconj": "det",
    "quantmod": "advmod",
    "neg": "advmod",
    "relcl": "acl",
    "infmod": "acl",
    "partmod": "acl",
    "vmod": "acl",
    "rcmod": "acl",
    "intj": "discourse",
    "meta": "discourse",
    "prt": "compound",
    "mwe": "fixed",
    "hmod": "advmod",
    "eternal": "dep",  # legacy ClearNLP oddity
}


def base_relation(rel: str | None) -> str:
    """Normalize a dependency label onto its UD v2 universal base relation.

    Handles: UD subtypes (``nsubj:pass`` → ``nsubj``), case (``ROOT`` →
    ``root``), and the spaCy ClearNLP/OntoNotes labels the bundled English
    models emit (``dobj`` → ``obj``, ``pobj`` → ``obl``, ``ROOT`` → ``root``,
    ...). Unknown labels pass through unchanged so nothing is silently
    dropped from profiles.
    """
    if not rel:
        return ""
    base = rel.split(":", 1)[0].strip().lower()
    return _NON_UD_ALIASES.get(base, base)


def relation_group(rel: str | None) -> str:
    """Functional group of a relation's base form ('' when unknown)."""
    info = UD_RELATION_INFO.get(base_relation(rel))
    return info[0] if info else ""


def relation_description(rel: str | None) -> str:
    info = UD_RELATION_INFO.get(base_relation(rel))
    return info[1] if info else ""
