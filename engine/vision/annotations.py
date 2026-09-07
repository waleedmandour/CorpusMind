"""
Visual annotation framework — the five research-grounded dimensions that
give visual corpora the analytical apparatus corpus linguistics has for
text (v1.1.0 Lens round).

The five dimensions are the visual analogues of levels of linguistic
structure, each anchored in an established framework:

1. Visual Morphology (Cohn 2013, *The Visual Language of Comics*; cf.
   Engelhardt 2002) — the structural makeup of drawn or iconic signs,
   comparable to morphemes in spoken language.
2. Attentional Framing (Kress & van Leeuwen 2006, *Reading Images*;
   Bateman 2008, *Multimodal Film Analysis*; comics panel research) —
   layout, boundaries and panel structures that direct the viewer's
   focus, functioning like punctuation or syntactic chunking.
3. Filmic Shot Scale (Kress & van Leeuwen's social distance mapped onto
   the standard film taxonomy — Bordwell & Thompson 2013) — the relative
   distance/size of depicted participants, conveying interpersonal
   distance and modal prominence.
4. Path Structure and Transitions (McCloud 1993, *Understanding Comics*;
   Halliday & Hasan 1976 cohesive conjunction) — the sequential flow
   from one visual frame to the next, functioning like conjunctive or
   transitional markers in text.
5. Multimodal Integration (Barthes 1977 anchorage/relay; Royce 2007
   intersemiotic complementarity) — where text (captions, dialogue
   balloons) and images co-occur to construct meaning, semantic
   preference or framing.

Storage: annotations are attached per image inside ``Image.meta`` under
the ``annotations`` key (zero-migration JSON column, the same access
pattern the v1.0.9 OCR corpus tools use), alongside free multi-value
researcher tags under ``meta["tags"]``:

    meta = {
      "user": {...}, "exif": {...}, "xmp": {...},     # v1.0.9 fields
      "tags": ["press-photo", "election"],
      "annotations": {
        "visual_morphology": {"values": ["emblem"], "note": ""},
        "attentional_framing": {"values": ["panel", "given_new"], "note": ""},
        "shot_scale": {"values": ["medium_shot"], "note": ""},
        "path_transition": {"values": ["action_to_action"], "note": ""},
        "multimodal_integration": {"values": ["caption", "anchorage"], "note": ""},
      },
    }

The set-level reading order for sequence analyses (transition chains,
n-grams, dispersion) is ``created_at`` ASC — the same convention as the
OCR-corpus export. A ``path_transition`` value on frame *i* describes
the shift from frame *i* to frame *i + 1* (an edge annotation).
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Taxonomy schema
# --------------------------------------------------------------------------- #

SCHEMA: list[dict] = [
    {
        "id": "visual_morphology",
        "label_en": "Visual Morphology",
        "label_ar": "البنية الصرفية البصرية",
        "description_en": (
            "The structural makeup of drawn or iconic signs — the visual analogue "
            "of morphemes in spoken language (Cohn 2013; Engelhardt 2002). Tag the "
            "minimal graphic units and combinatorial structures the image is built from."
        ),
        "description_ar": (
            "البنية التركيبية للعلامات المرسومة أو الأيقونية — المقابل البصري "
            "للوحدات الصرفية في اللغة المنطوقة (كون 2013). وسِم الوحدات الرسومية "
            "الدنيا والبنى التركيبية التي تتألف منها الصورة."
        ),
        "framework": "Cohn 2013 (visual language theory)",
        "multi": True,
        "categories": [
            {"id": "graphic_stroke", "label_en": "Graphic stroke", "label_ar": "الضربة الرسومية",
             "description_en": "Line quality/weight as the minimal graphic unit."},
            {"id": "contour_shape", "label_en": "Contour shape", "label_ar": "الشكل المحيطي",
             "description_en": "A closed outline bounding a discrete form."},
            {"id": "closure", "label_en": "Closure", "label_ar": "الإغلاق الجشطالطي",
             "description_en": "Gestalt completion of a form across gaps."},
            {"id": "color_fill", "label_en": "Colour fill", "label_ar": "التعبئة اللونية",
             "description_en": "A flat chromatic region inside a contour."},
            {"id": "gradient_shading", "label_en": "Gradient shading", "label_ar": "التظليل التدرجي",
             "description_en": "Tonal transition modelling volume/depth."},
            {"id": "texture_pattern", "label_en": "Texture pattern", "label_ar": "النقش السطحي",
             "description_en": "A repeated surface micro-pattern."},
            {"id": "part_whole", "label_en": "Part-whole composition", "label_ar": "علاقة الجزء بالكل",
             "description_en": "Meronymic structure — components of a larger whole."},
            {"id": "repetition", "label_en": "Repetition", "label_ar": "التكرار",
             "description_en": "Iterated identical units (multiplicative structure)."},
            {"id": "symmetry", "label_en": "Symmetry", "label_ar": "التناظر",
             "description_en": "Mirrored structural organisation."},
            {"id": "radial_structure", "label_en": "Radial structure", "label_ar": "البنية الشعاعية",
             "description_en": "Organisation around a shared centre."},
            {"id": "emblem", "label_en": "Emblem", "label_ar": "الرمز الاصطلاحي",
             "description_en": "A conventionalised sign standing for a concept."},
            {"id": "logograph", "label_en": "Logograph", "label_ar": "الرسم المعجمي",
             "description_en": "A graphic token carrying lexical value (word-as-image)."},
        ],
    },
    {
        "id": "attentional_framing",
        "label_en": "Attentional Framing",
        "label_ar": "التأطير الانتباهي",
        "description_en": (
            "The layout, boundaries and panel structures that direct the viewer's "
            "focus — functioning like punctuation or syntactic chunking in text "
            "(Kress & van Leeuwen 2006; Bateman 2008)."
        ),
        "description_ar": (
            "التخطيط والحدود وبنى اللوحات التي توجّه انتباه المشاهد — بأدوار تشبه "
            "علامات الترقيم أو التقسيم التركيبي في النص (كرس وفان ليوين 2006؛ باتمان 2008)."
        ),
        "framework": "Kress & van Leeuwen 2006; Bateman 2008",
        "multi": True,
        "categories": [
            {"id": "panel", "label_en": "Panel", "label_ar": "اللوحة",
             "description_en": "A bounded framing unit."},
            {"id": "inset", "label_en": "Inset", "label_ar": "الإطار المداخل",
             "description_en": "A frame-within-frame (nested attention)."},
            {"id": "splash", "label_en": "Splash", "label_ar": "اللوحة الكاملة",
             "description_en": "A single full-page frame."},
            {"id": "full_bleed", "label_en": "Full bleed", "label_ar": "الامتداد الكامل",
             "description_en": "A frame extending beyond the trim margins."},
            {"id": "gutter", "label_en": "Gutter", "label_ar": "الهامش الفاصل",
             "description_en": "The separating space between frames."},
            {"id": "border_solid", "label_en": "Solid border", "label_ar": "حدود صلبة",
             "description_en": "A strong continuous boundary."},
            {"id": "border_soft", "label_en": "Soft border", "label_ar": "حدود ناعمة",
             "description_en": "A permeable/feathered boundary."},
            {"id": "border_absent", "label_en": "Absent border", "label_ar": "غياب الحدود",
             "description_en": "An unbounded composition."},
            {"id": "frame_break", "label_en": "Frame break", "label_ar": "كسر الإطار",
             "description_en": "Content crossing a frame boundary."},
            {"id": "grid_regular", "label_en": "Regular grid", "label_ar": "شبكة منتظمة",
             "description_en": "A modular layout grid of equal units."},
            {"id": "grid_irregular", "label_en": "Irregular grid", "label_ar": "شبكة غير منتظمة",
             "description_en": "Varied module sizes in the layout."},
            {"id": "given_new", "label_en": "Given–new", "label_ar": "معلوم–جديد",
             "description_en": "Left–right information value (given → new)."},
            {"id": "ideal_real", "label_en": "Ideal–real", "label_ar": "مثالي–واقعي",
             "description_en": "Top–bottom information value (ideal → real)."},
            {"id": "centre_margin", "label_en": "Centre–margin", "label_ar": "مركز–هامش",
             "description_en": "Centred emphasis vs peripheral framing."},
            {"id": "salience_contrast", "label_en": "Salience via contrast", "label_ar": "البروز عبر التباين",
             "description_en": "Attention capture through size/colour/contrast."},
        ],
    },
    {
        "id": "shot_scale",
        "label_en": "Filmic Shot Scale",
        "label_ar": "مقياس اللقطة",
        "description_en": (
            "The relative distance or size of visual objects and characters — the "
            " interpersonal-distance system of the image (Kress & van Leeuwen's "
            "social distance mapped to the standard film taxonomy; Bordwell & "
            "Thompson 2013). Conveys interpersonal distance and modal prominence."
        ),
        "description_ar": (
            "المسافة النسبية أو حجم الأشياء والشخصيات في الصورة — نظام المسافة "
            "التفاعلية للصورة (المسافة الاجتماعية عند كرس وفان ليوين مطابقةً "
            "لتصنيف اللقطات السينمائية). يعبّر عن المسافة الشخصية والبروز الأسلوبي."
        ),
        "framework": "Kress & van Leeuwen 2006; Bordwell & Thompson 2013",
        "multi": True,
        "categories": [
            {"id": "extreme_close_up", "label_en": "Extreme close-up", "label_ar": "لقطة قريبة جداً",
             "description_en": "Intimate distance — a detail fills the frame."},
            {"id": "close_up", "label_en": "Close-up", "label_ar": "لقطة قريبة",
             "description_en": "Close personal distance — head and shoulders."},
            {"id": "medium_close_up", "label_en": "Medium close-up", "label_ar": "لقطة متوسطة القرب",
             "description_en": "Personal distance — chest up."},
            {"id": "medium_shot", "label_en": "Medium shot", "label_ar": "لقطة متوسطة",
             "description_en": "Social distance — waist up."},
            {"id": "medium_long_shot", "label_en": "Medium long shot", "label_ar": "لقطة متوسطة بعيدة",
             "description_en": "Social-impersonal distance — knees up."},
            {"id": "full_shot", "label_en": "Full shot", "label_ar": "لقطة كاملة",
             "description_en": "Impersonal distance — the full figure."},
            {"id": "long_shot", "label_en": "Long shot", "label_ar": "لقطة بعيدة",
             "description_en": "Public distance — figure within its setting."},
            {"id": "extreme_long_shot", "label_en": "Extreme long shot", "label_ar": "لقطة بعيدة جداً",
             "description_en": "Distant public — the vista dominates the figure."},
        ],
    },
    {
        "id": "path_transition",
        "label_en": "Path Structure and Transitions",
        "label_ar": "البنية المسارية والانتقالات",
        "description_en": (
            "The sequential flow or narrative progression from one visual frame to "
            "the next — functioning like conjunctive or transitional markers in text "
            "(McCloud 1993; Halliday & Hasan 1976). Annotate the shift FROM this "
            "frame TO the following frame (the set's reading order is ingest order)."
        ),
        "description_ar": (
            "التدفق التتابعي أو التقدم السردي من لوحة بصرية إلى التالية — بأدوار "
            "تشبه أدوات الربط والانتقال في النص (ماكلاود 1993؛ هاليداي وحسن 1976). "
            "وسِم الانتقال من هذه اللوحة إلى اللوحة التالية وفق ترتيب الإدخال."
        ),
        "framework": "McCloud 1993; Halliday & Hasan 1976",
        "multi": True,
        "categories": [
            {"id": "moment_to_moment", "label_en": "Moment-to-moment", "label_ar": "لحظة إلى لحظة",
             "description_en": "Minimal temporal progression."},
            {"id": "action_to_action", "label_en": "Action-to-action", "label_ar": "فعل إلى فعل",
             "description_en": "A continuous action sequence."},
            {"id": "subject_to_subject", "label_en": "Subject-to-subject", "label_ar": "موضوع إلى موضوع",
             "description_en": "Same scene, new focal subject."},
            {"id": "scene_to_scene", "label_en": "Scene-to-scene", "label_ar": "مشهد إلى مشهد",
             "description_en": "A marked shift in time or place."},
            {"id": "aspect_to_aspect", "label_en": "Aspect-to-aspect", "label_ar": "جانب إلى جانب",
             "description_en": "Detached aspects of a place or idea."},
            {"id": "non_sequitur", "label_en": "Non-sequitur", "label_ar": "انقطاع منطقي",
             "description_en": "No logical relation between frames."},
            {"id": "match_cut", "label_en": "Match cut", "label_ar": "القطع المطابق",
             "description_en": "A graphic or content match across the cut."},
            {"id": "fade", "label_en": "Fade", "label_ar": "التلاشي",
             "description_en": "Gradual attenuation into or out of a frame."},
            {"id": "dissolve", "label_en": "Dissolve", "label_ar": "الذوبان",
             "description_en": "An overlap blend between frames."},
            {"id": "ellipsis_marker", "label_en": "Ellipsis marker", "label_ar": "علامة الحذف الزمني",
             "description_en": "An overt marker of elided time."},
        ],
    },
    {
        "id": "multimodal_integration",
        "label_en": "Multimodal Integration",
        "label_ar": "التكامل متعدد الأنماط",
        "description_en": (
            "The intersection where text (captions, dialogue balloons) and images "
            "co-occur to construct meaning, semantic preference or framing "
            "(Barthes 1977 anchorage/relay; Royce 2007 intersemiotic complementarity)."
        ),
        "description_ar": (
            "نقطة التقاء النص (التعليقات، بالونات الحوار) بالصورة في بناء المعنى "
            "أو التفضيل الدلالي أو التأطير (بارت 1977: التثبيت والتناوب؛ رويس 2007)."
        ),
        "framework": "Barthes 1977; Royce 2007",
        "multi": True,
        "categories": [
            {"id": "anchorage", "label_en": "Anchorage", "label_ar": "التثبيت",
             "description_en": "Text fixes or directs the image's meaning."},
            {"id": "relay", "label_en": "Relay", "label_ar": "التناوب",
             "description_en": "Text and image advance meaning together."},
            {"id": "caption", "label_en": "Caption", "label_ar": "التعليق النصي",
             "description_en": "Detached descriptive text."},
            {"id": "speech_balloon", "label_en": "Speech balloon", "label_ar": "بالون الكلام",
             "description_en": "Enclosed diegetic speech."},
            {"id": "thought_bubble", "label_en": "Thought bubble", "label_ar": "فقاعة الفكر",
             "description_en": "Represented interior thought."},
            {"id": "sound_effect", "label_en": "Sound effect", "label_ar": "المؤثر الصوتي المرئي",
             "description_en": "Onomatopoeic graphic text."},
            {"id": "label_title", "label_en": "Label / title", "label_ar": "العنوان/التسمية",
             "description_en": "Naming or heading text."},
            {"id": "emergent_text", "label_en": "Emergent text", "label_ar": "النص الناشئ",
             "description_en": "Text functioning as a graphic object."},
            {"id": "contradiction", "label_en": "Contradiction", "label_ar": "التقابل النصي-البصري",
             "description_en": "Text-image tension (irony)."},
        ],
    },
]

DIMENSION_IDS: tuple[str, ...] = tuple(d["id"] for d in SCHEMA)

_VALID_CATEGORY_IDS: dict[str, frozenset[str]] = {
    d["id"]: frozenset(c["id"] for c in d["categories"]) for d in SCHEMA
}

CATEGORY_LABELS: dict[str, dict[str, str]] = {
    d["id"]: {c["id"]: c["label_en"] for c in d["categories"]} for d in SCHEMA
}


def dimension(dim_id: str) -> dict | None:
    """Return the schema dict for one dimension id, or None."""
    return next((d for d in SCHEMA if d["id"] == dim_id), None)


def is_valid_dimension(dim_id: str) -> bool:
    return dim_id in _VALID_CATEGORY_IDS


def is_valid_category(dim_id: str, cat_id: str) -> bool:
    cats = _VALID_CATEGORY_IDS.get(dim_id)
    return cats is not None and cat_id in cats


def normalise_tags(tags: list) -> list[str]:
    """Normalise a researcher tag list: unique, stripped, lowercase-ish
    (preserving case is friendlier for names — keep as typed, dedupe
    case-insensitively), max 30 tags, each ≤ 64 chars."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags if isinstance(tags, list) else []:
        if not isinstance(t, str):
            continue
        s = t.strip()[:64]
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 30:
            break
    return out


def normalise_annotations(payload: dict) -> dict:
    """Validate + normalise a client annotation payload.

    Input shape: {dimension_id: {"values": [...], "note": "..."}, ...}
    plus optional "tags": [...]. Unknown dimensions are dropped (not an
    error — forward compatibility for older/newer clients); unknown
    category ids raise ``ValueError`` so typos never silently corrupt a
    corpus.

    Returns: {"tags": [...], "dimensions": {dim: {"values": [...],
    "note": str, "updated_at": iso}}}
    """
    from datetime import UTC, datetime

    dims_out: dict[str, dict] = {}
    payload_dims = payload.get("dimensions", payload)
    for dim_id in DIMENSION_IDS:
        block = payload_dims.get(dim_id)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise ValueError(f"Annotation block for '{dim_id}' must be an object")
        raw_values = block.get("values", [])
        if not isinstance(raw_values, list):
            raise ValueError(f"'{dim_id}.values' must be a list")
        values: list[str] = []
        for v in raw_values:
            if not isinstance(v, str):
                raise ValueError(f"'{dim_id}.values' entries must be strings")
            if not is_valid_category(dim_id, v):
                raise ValueError(
                    f"Unknown category '{v}' for dimension '{dim_id}' "
                    f"(valid: {sorted(_VALID_CATEGORY_IDS[dim_id])})"
                )
            if v not in values:
                values.append(v)
        note = block.get("note", "")
        if not isinstance(note, str):
            raise ValueError(f"'{dim_id}.note' must be a string")
        dims_out[dim_id] = {
            "values": values,
            "note": note[:2000],
            "updated_at": datetime.now(UTC).isoformat(),
        }
    return {
        "tags": normalise_tags(payload.get("tags", [])),
        "dimensions": dims_out,
    }


def read_annotations(meta: dict | None) -> dict:
    """Read the annotation payload out of an Image.meta JSON column."""
    if not isinstance(meta, dict):
        return {"tags": [], "dimensions": {}}
    return {
        "tags": list(meta.get("tags") or []),
        "dimensions": dict(meta.get("annotations") or {}),
    }
