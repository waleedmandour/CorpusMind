#!/usr/bin/env python3
"""r11: enrich reference-data/frameworks/*.yaml with research-grounded metadata.

Field report (r11): the 12 theoretical-framework YAMLs shipped with only
{name, full_name, version, framework_family, categories, guardrails} and the
/frameworks catalogue endpoint was never consumed by the UI, so the CDA
frameworks (Fairclough, van Dijk, Wodak) were effectively invisible in the
Discourse window. This script adds three additive, research-grounded fields
per framework - description, core_concepts, references - inserted right after
the framework_family line. Idempotent: files that already carry a description
are left untouched. Existing consumers keep working (all new keys optional).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "reference-data" / "frameworks"

# file stem -> (description, core_concepts, references)
ENRICHMENT: dict[str, tuple[str, list[str], list[str]]] = {
    "fairclough-cda": (
        "Fairclough's three-dimensional model treats every text as simultaneously (1) a "
        "text whose vocabulary, grammar and cohesion can be described; (2) an instance of "
        "discursive practice - produced, distributed and consumed in ways that must be "
        "interpreted; and (3) a piece of social practice whose ideological effects and "
        "power relations must be explained. Analysis moves from description to "
        "interpretation to explanation, asking how linguistic choices naturalize "
        "particular representations of the social world as common sense.",
        [
            "Three-dimensional model: description, interpretation, explanation",
            "Naturalization of ideological assumptions",
            "Hegemony and common sense",
            "Interdiscursivity and recontextualization",
            "Member resources (interpretative repertoires)",
        ],
        [
            "Fairclough, N. (1989). Language and Power. Longman.",
            "Fairclough, N. (1992). Discourse and Social Change. Polity Press.",
            "Fairclough, N. (1995). Critical Discourse Analysis: The Critical Study of Language. Longman.",
        ],
    ),
    "van-dijk-sca": (
        "van Dijk's socio-cognitive approach places cognition between discourse and "
        "society: ideologies are shared social representations, and concrete text or talk "
        "is produced and understood through mental models and context models. Because "
        "discourse structures can only be related to social structures through these "
        "mediated cognitions, analysis examines how discourse expresses and reproduces "
        "socially shared beliefs - classically through the ideological square of positive "
        "self-presentation and negative other-presentation.",
        [
            "Socio-cognitive mediation: discourse - cognition - society",
            "Mental models and context models",
            "Ideologies as shared social representations",
            "Ideological square: positive self / negative other presentation",
            "Micro-macro level bridging",
        ],
        [
            "van Dijk, T. A. (1998). Ideology: A Multidisciplinary Approach. Sage.",
            "van Dijk, T. A. (2001). Multidisciplinary CDA: A plea for diversity. In Wodak & Meyer (Eds.), Methods of Critical Discourse Analysis. Sage.",
            "van Dijk, T. A. (2008). Discourse and Context: A Sociocognitive Approach. Cambridge University Press.",
        ],
    ),
    "wodak-dha": (
        "The discourse-historical approach embeds a text in four levels of context: the "
        "text itself, intertextual and interdiscursive relations, the extralinguistic "
        "social and sociological variables, and the broader historical context. It "
        "operationalizes analysis through discourse strategies - referential/nomination, "
        "predication, argumentation (topoi), perspectivization, and "
        "intensification/mitigation - asking how social actors, objects and events are "
        "named, characterized and legitimized in their specific historical settings.",
        [
            "Four-level context: text, interdiscursive, social, historical",
            "Nomination / referential strategies",
            "Predication strategies",
            "Argumentation strategies and topoi",
            "Perspectivization, intensification and mitigation",
        ],
        [
            "Reisigl, M., & Wodak, R. (2001). Discourse and Discrimination: Rhetorics of Racism and Antisemitism. Routledge.",
            "Wodak, R., & Meyer, M. (Eds.) (2001/2009). Methods of Critical Discourse Analysis. Sage.",
            "Wodak, R. (2015). The Politics of Fear. Sage.",
        ],
    ),
    "machin-mayr-mcda": (
        "Machin and Mayr's multimodal introduction to CDA is a hands-on toolkit for "
        "tracing how discourse legitimates, naturalizes or recontextualizes social "
        "arrangements across language and image. It foregrounds the representation of "
        "social actors (van Leeuwen's socio-semantic network), abstraction and "
        "genericization, and the discursive construction of legitimacy - extending "
        "Fairclough-style critical questions to visual and multimodal material.",
        [
            "Representation of social actors (van Leeuwen)",
            "Recontextualization of social practice",
            "Legitimation and delegitimation strategies",
            "Discourses as unequal symbolic resources",
            "Multimodal critical analysis",
        ],
        [
            "Machin, D., & Mayr, A. (2012). How to Do Critical Discourse Analysis: A Multimodal Introduction. Sage.",
            "van Leeuwen, T. (2008). Discourse and Practice: New Tools for Critical Discourse Analysis. Oxford University Press.",
        ],
    ),
    "halliday-sfl": (
        "Systemic Functional Linguistics models language as a resource for making "
        "meaning, organized around three simultaneous metafunctions: ideational "
        "(representing experience), interpersonal (enacting relations and stances) and "
        "textual (organizing the message). Analysis works through system networks - "
        "transitivity, mood and modality, theme-rheme, cohesion - connecting each "
        "choice to its contextual function in register (field, tenor, mode).",
        [
            "Three metafunctions: ideational, interpersonal, textual",
            "System networks: choice as meaning",
            "Transitivity (process types) and modality",
            "Theme-rheme and information structure",
            "Register: field, tenor, mode",
        ],
        [
            "Halliday, M. A. K. (1985). An Introduction to Functional Grammar. Arnold.",
            "Halliday, M. A. K., & Matthiessen, C. M. I. M. (2014). Halliday's Introduction to Functional Grammar (4th ed.). Routledge.",
        ],
    ),
    "kress-van-leeuwen": (
        "Kress and van Leeuwen's grammar of visual design extends the SFL metafunctions "
        "to images: representational structures (narrative vs conceptual), interactive "
        "structures (contact, social distance, attitude, modality) and compositional "
        "structures (information value, salience, framing). The framework asks who or "
        "what is depicted, how the image engages the viewer, and how placement, size and "
        "framing organize meaning.",
        [
            "Representational: narrative and conceptual structures",
            "Interactive: contact, distance, attitude, modality",
            "Compositional: information value, salience, framing",
            "Metafunctions extended to the visual",
        ],
        [
            "Kress, G., & van Leeuwen, T. (1996/2006). Reading Images: The Grammar of Visual Design. Routledge.",
        ],
    ),
    "barthes-semiotics": (
        "Barthes's semiology analyses how signs carry second-order meanings: denotation "
        "(the literal sign) is overlaid by connotation and by myth - a second-order "
        "semiological system in which historical, contingent meanings present themselves "
        "as natural. Mythologies demonstrates the method on everyday cultural artefacts; "
        "Elements of Semiology systematizes signifier/signified, syntagm and system.",
        [
            "Signifier / signified / sign",
            "Denotation vs connotation",
            "Myth as second-order semiological system",
            "Naturalization of cultural meaning",
        ],
        [
            "Barthes, R. (1957/1972). Mythologies. Hill and Wang.",
            "Barthes, R. (1964/1967). Elements of Semiology. Jonathan Cape.",
        ],
    ),
    "peirce-semiotics": (
        "Peirce's triadic semiotics defines the sign through its relation to an object "
        "and an interpretant, with meaning produced in an unending process of "
        "interpretation (semiosis). His trichotomy of signs - icon (resemblance), index "
        "(causal or physical connection), symbol (convention) - offers a finer-grained "
        "typology than dyadic models and treats representation as inferential and "
        "fallibilist.",
        [
            "Triadic sign: representamen - object - interpretant",
            "Semiosis: unlimited interpretive process",
            "Icon, index, symbol",
            "Abduction and fallibilism",
        ],
        [
            "Peirce, C. S. (1931-1958). Collected Papers of Charles Sanders Peirce. Harvard University Press.",
            "Atkin, A. (2010). Peirce's Theory of Signs. Stanford Encyclopedia of Philosophy.",
        ],
    ),
    "lakoff-johnson-cmt": (
        "Conceptual Metaphor Theory holds that metaphor is systematic thought rather "
        "than ornament: mappings from concrete source domains structure abstract target "
        "domains (ARGUMENT IS WAR, TIME IS MONEY) and surface as conventional expressions "
        "in discourse. Analysis identifies source-target mappings, their entailments and "
        "what they hide - including orientational and ontological metaphors and metonymy.",
        [
            "Conceptual metaphor: source-to-target mapping",
            "Structural, orientational, ontological metaphors",
            "Systematic entailments; highlighting and hiding",
            "Metonymy as reference shift",
            "Embodiment as grounding",
        ],
        [
            "Lakoff, G., & Johnson, M. (1980). Metaphors We Live By. University of Chicago Press.",
            "Lakoff, G., & Johnson, M. (1999). Philosophy in the Flesh. Basic Books.",
            "Kovecses, Z. (2010). Metaphor: A Practical Introduction (2nd ed.). Oxford University Press.",
        ],
    ),
    "martin-white-appraisal": (
        "Appraisal Theory maps evaluative meaning in discourse across three regions: "
        "attitude (affect, judgment of character, appreciation of things), engagement "
        "(the heteroglossic backdrop - resources that contract or expand dialogistic "
        "space) and graduation (force and focus). Developed within SFL, it is the "
        "standard reference for analysing how texts negotiate evaluation and align "
        "readers around community-valued stances.",
        [
            "Attitude: affect, judgment, appreciation",
            "Engagement: monogloss vs heterogloss; contract vs expand",
            "Graduation: force and focus",
            "Reader alignment and community values",
        ],
        [
            "Martin, J. R., & White, P. R. R. (2005). The Language of Evaluation: Appraisal in English. Palgrave Macmillan.",
            "Martin, J. R., & Rose, D. (2007). Working with Discourse (2nd ed.). Continuum.",
        ],
    ),
    "aristotle-rhetoric": (
        "Aristotle's Rhetoric founds the systematic study of persuasion: speakers "
        "persuade through three pisteis - ethos (the character of the speaker), pathos "
        "(the emotions of the audience) and logos (the argument proper, especially the "
        "enthymeme). He distinguishes three genres (deliberative, forensic, epideictic) "
        "and ties effective argument to kairos, the opportune moment and situation.",
        [
            "Three pisteis: ethos, pathos, logos",
            "Enthymeme: the rhetorical syllogism",
            "Deliberative, forensic, epideictic genres",
            "Kairos: situational timing",
            "Topoi (common topics)",
        ],
        [
            "Aristotle (c. 350 BCE/2007). On Rhetoric: A Theory of Civic Discourse (Trans. G. A. Kennedy, 2nd ed.). Oxford University Press.",
        ],
    ),
    "toulmin-argumentation": (
        "Toulmin's model analyses practical argument as a pattern of interrelated moves: "
        "a claim supported by data (grounds), standing on a warrant, which can in turn be "
        "supported by backing; qualifiers express the strength of the claim and rebuttals "
        "the conditions under which it fails. The layout is the standard instrument for "
        "mapping how the arguments in a text are assembled - and where they are vulnerable.",
        [
            "Claim, data (grounds), warrant",
            "Backing, qualifier, rebuttal",
            "Argument layout as analytic map",
            "Field-dependence of warrants",
        ],
        [
            "Toulmin, S. E. (1958/2003). The Uses of Argument (Updated ed.). Cambridge University Press.",
            "Hitchcock, D., & Verheij, B. (Eds.) (2006). Arguing on the Toulmin Model. Springer.",
        ],
    ),
}


def yaml_block(description: str, concepts: list[str], references: list[str]) -> str:
    """Render the additive metadata as YAML, double-quoted where needed."""
    lines = [f'description: "{description}"', "core_concepts:"]
    lines += [f'  - "{c}"' for c in concepts]
    lines.append("references:")
    lines += [f'  - "{r}"' for r in references]
    return "\n".join(lines)


def main() -> None:
    changed: list[str] = []
    for stem, (desc, concepts, refs) in sorted(ENRICHMENT.items()):
        path = ROOT / f"{stem}.yaml"
        if not path.is_file():
            raise SystemExit(f"MISSING framework file: {path}")
        text = path.read_text(encoding="utf-8")
        # Top-level check only: category entries carry indented
        # `description:` keys, so a plain substring test would skip files.
        if re.search(r"^description:", text, re.M):
            print(f"SKIP (already enriched): {stem}")
            continue
        anchor = "framework_family:"
        idx = text.find(anchor)
        if idx == -1:
            raise SystemExit(f"NO framework_family anchor in {stem}")
        line_end = text.find("\n", idx)
        block = yaml_block(desc, concepts, refs)
        new_text = text[: line_end + 1] + block + "\n" + text[line_end + 1 :]
        path.write_text(new_text, encoding="utf-8")
        changed.append(stem)

    # Validate: parse all files and assert the three fields are present.
    import yaml  # noqa: PLC0415 — validation-only import

    for path in sorted(ROOT.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        stem = path.stem
        assert data.get("description", "").strip(), f"empty description: {stem}"
        assert data.get("core_concepts"), f"empty core_concepts: {stem}"
        assert data.get("references"), f"empty references: {stem}"
        print(f"OK {stem}: family={data.get('framework_family')!r} "
              f"concepts={len(data['core_concepts'])} refs={len(data['references'])}")
    print(f"\nEnriched {len(changed)} files: {', '.join(changed)}")


if __name__ == "__main__":
    main()
