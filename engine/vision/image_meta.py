"""Privacy-safe image metadata extraction (v1.0.9 Lens round).

Corpus-construction norms (and the IPTC Photo Metadata standard) expect an
image corpus to carry descriptive metadata: creator, date created, rights /
licence, headline, description, keywords. Most of that already travels inside
the image file itself as EXIF and XMP (IPTC Core/Extension are conventionally
serialized through XMP), so Lens extracts it at ingest and stores it in
``Image.meta`` alongside the researcher's own fields.

Design decisions
----------------
* **EXIF via Pillow only** — no new binary dependencies (the engine ships as
  a PyInstaller sidecar; every extra package costs build surface).
* **XMP via packet scan** — XMP lives in an ``<x:xmpmeta>`` packet that is
  plain XML embedded in the file. We lift a small, well-known field set with
  targeted regular expressions instead of pulling in a full RDF library.
* **GPS is deliberately NOT extracted.** Location coordinates are personal
  data under GDPR and almost never needed for discourse-analytic work, so the
  extractor skips every GPS tag/namespace on purpose and records why.
* **Never raises** — a malformed or missing metadata block must not fail an
  ingest; we return what we could read (possibly {}).
"""
from __future__ import annotations

import re

from app.logging import get_logger

log = get_logger(__name__)

# EXIF tags we surface (tag id -> canonical name). Deliberately excludes the
# GPS IFD (0x8825) and every 0x0001-0x001F GPS tag.
_EXIF_TAGS: dict[int, str] = {
    271: "make",
    272: "model",
    305: "software",
    306: "date_time",
    42016: "image_unique_id",  # rarely useful, but harmless & identifying-free
}
_EXIF_SUB_IFD_EXIF = 0x8769  # Exif IFD pointer
_EXIF_SUB_TAGS: dict[int, str] = {
    36867: "date_time_original",
    36868: "date_time_digitized",
    40964: "related_sound_file",  # kept out — actually drop below
}
# Keep only these from the Exif sub-IFD:
_EXIF_SUB_TAGS = {
    36867: "date_time_original",
    36868: "date_time_digitized",
}

_XMP_FIELD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("title", re.compile(rb"<dc:title[\s\S]{0,400}?<rdf:li[^>]*>([^<]{1,300})</rdf:li>", re.S)),
    ("creator", re.compile(rb"<dc:creator[\s\S]{0,400}?<rdf:li[^>]*>([^<]{1,300})</rdf:li>", re.S)),
    ("description", re.compile(rb"<dc:description[\s\S]{0,400}?<rdf:li[^>]*>([^<]{1,2000})</rdf:li>", re.S)),
    ("rights", re.compile(rb"<dc:rights[\s\S]{0,400}?<rdf:li[^>]*>([^<]{1,300})</rdf:li>", re.S)),
    ("headline", re.compile(rb"<photoshop:Headline>([^<]{1,300})</photoshop:Headline>", re.S)),
    ("credit", re.compile(rb"<photoshop:Credit>([^<]{1,300})</photoshop:Credit>", re.S)),
    ("usage_terms", re.compile(rb"<xmpRights:UsageTerms[\s\S]{0,400}?<rdf:li[^>]*>([^<]{1,300})</rdf:li>", re.S)),
    ("web_statement", re.compile(rb"<xmpRights:WebStatement>([^<]{1,300})</xmpRights:WebStatement>", re.S)),
]

_XMP_SUBJECT_PATTERN = re.compile(
    rb"<dc:subject[\s\S]{0,2000}?</dc:subject>", re.S)
_XMP_SUBJECT_LI = re.compile(rb"<rdf:li[^>]*>([^<]{1,120})</rdf:li>")

_XML_ENTITY = re.compile(rb"&#x([0-9a-fA-F]+);|&#(\d+);")
_XML_ESCAPES = {
    b"&lt;": b"<", b"&gt;": b">", b"&quot;": b'"', b"&apos;": b"'", b"&amp;": b"&",
}


def _clean_xml_text(raw: bytes) -> str:
    """Decode a small XML text node: entities → unicode, strip whitespace."""
    for esc, ch in _XML_ESCAPES.items():
        raw = raw.replace(esc, ch)

    def _hex_or_dec(m: re.Match[bytes]) -> bytes:
        if m.group(1):
            return bytes([int(m.group(1), 16)])
        return bytes([int(m.group(2))])

    raw = _XML_ENTITY.sub(_hex_or_dec, raw)
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _extract_exif(img) -> dict[str, str]:
    """Read the whitelisted EXIF tags. Never raises."""
    out: dict[str, str] = {}
    try:
        exif = img.getexif()
        if not exif:
            return out
        for tag_id, name in _EXIF_TAGS.items():
            val = exif.get(tag_id)
            if val not in (None, ""):
                out[name] = str(val).strip()[:200]
        try:
            sub = exif.get_ifd(_EXIF_SUB_IFD_EXIF) or {}
            for tag_id, name in _EXIF_SUB_TAGS.items():
                val = sub.get(tag_id)
                if val not in (None, ""):
                    out[name] = str(val).strip()[:200]
        except Exception:  # pragma: no cover — sub-IFD layout quirks
            pass
    except Exception as e:  # pragma: no cover — Pillow guard
        log.debug("exif_extract_failed", error=str(e))
    return out


def _extract_xmp(raw: bytes) -> dict:
    """Scan the embedded XMP packet for the IPTC-Core-aligned field set."""
    out: dict = {}
    try:
        start = raw.find(b"<x:xmpmeta")
        if start == -1:
            start = raw.find(b"<x:xapmeta")
        if start == -1:
            return out
        end = raw.find(b"</x:xmpmeta>", start)
        if end == -1:
            end = raw.find(b"</x:xapmeta>", start)
        if end == -1:
            return out
        packet = raw[start:end]
        for name, pat in _XMP_FIELD_PATTERNS:
            m = pat.search(packet)
            if m:
                text = _clean_xml_text(m.group(1))
                if text:
                    out[name] = text[:2000]
        subjects = _XMP_SUBJECT_PATTERN.search(packet)
        if subjects:
            keywords = [
                _clean_xml_text(li)
                for li in _XMP_SUBJECT_LI.findall(subjects.group(0))
            ]
            keywords = [k for k in keywords if k][:20]
            if keywords:
                out["keywords"] = keywords
    except Exception as e:  # pragma: no cover — guard against malformed packets
        log.debug("xmp_extract_failed", error=str(e))
    return out


def extract_image_metadata(raw: bytes) -> dict:
    """Extract privacy-safe descriptive metadata from raw image bytes.

    Returns ``{"exif": {...}, "xmp": {...}, "privacy": "gps_excluded"}`` —
    all sub-dicts possibly empty. Never raises.
    """
    result: dict = {"exif": {}, "xmp": {}, "privacy": "gps_excluded"}
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(raw)) as img:
            result["exif"] = _extract_exif(img)
    except Exception as e:  # pragma: no cover — not an image / Pillow guard
        log.debug("image_meta_open_failed", error=str(e))
    try:
        result["xmp"] = _extract_xmp(raw)
    except Exception:  # pragma: no cover
        pass
    # Drop the privacy marker when there is nothing at all — keeps empty
    # ingests clean.
    if not result["exif"] and not result["xmp"]:
        return {}
    return result
