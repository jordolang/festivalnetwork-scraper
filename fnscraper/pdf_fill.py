"""Auto-fill fillable (AcroForm) PDF applications from a vendor profile.

Field matching is fuzzy: a PDF field named "Business Name", "Company",
"biz_name", etc. all map to the profile's ``business_name``.  Flat PDFs
(no form fields) can't be filled programmatically — callers get
``(0, 0)`` back and should fall back to an answer sheet.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

PROFILE_FILE = "vendor_profile.json"
PROFILE_EXAMPLE = "vendor_profile.example.json"

# Placeholders only.  This template is what gets written into a PDF when
# the owner has not run the setup wizard, and it ships in the public repo,
# so it must never carry one business's real contact details, tax ID, or
# insurance carrier — the next business to install would mail those out on
# its own applications.  `python -m fnscraper setup` writes the real
# values into the (gitignored) vendor_profile.json.
DEFAULT_PROFILE = {
    "business_name": "YOUR BUSINESS NAME",
    "contact_name": "YOUR NAME",
    "address": "YOUR STREET ADDRESS",
    "city": "YOUR CITY",
    "state": "OH",
    "zip": "00000",
    "phone": "(000) 000-0000",
    "email": "you@example.com",
    "website": "https://www.example.com",
    "product_description": "WHAT YOU SELL",
    "category": "YOUR VENDOR CATEGORY",
    "booth_size": "10x10",
    "electric_needed": "No",
    "years_in_business": "1",
    "tax_id": "YOUR TAX ID",
    "vendors_license": "None",
    "insurance_carrier": "YOUR INSURANCE CARRIER",
    "signature_date": "",
}

# profile key -> lowercase substrings that identify a matching PDF field
FIELD_SYNONYMS: dict[str, list[str]] = {
    "business_name": ["business name", "company", "business", "farm/company",
                      "organization", "booth name", "studio"],
    "contact_name": ["contact name", "your name", "applicant", "owner",
                     "first and last", "printed name", "full name", "name"],
    "address": ["street", "mailing address", "address"],
    "city": ["city", "town"],
    "state": ["state", "province"],
    "zip": ["zip", "postal"],
    "phone": ["phone", "cell", "telephone", "mobile"],
    "email": ["email", "e-mail"],
    "website": ["website", "web site", "url", "facebook", "social"],
    "product_description": ["description of product", "product description",
                            "items to be sold", "what will you sell",
                            "merchandise", "description", "products"],
    "category": ["category", "type of vendor", "vendor type", "medium"],
    "booth_size": ["booth size", "space size", "frontage"],
    "electric_needed": ["electric", "power", "amps"],
    "years_in_business": ["years in business", "years"],
    "tax_id": ["tax id", "ein", "vendor's license", "tax number"],
    "vendors_license": ["vendor license", "vendors license", "license number"],
    "insurance_carrier": ["insurance"],
    "signature_date": ["date"],
}

# Longest synonyms first so "business name" wins over "name".
_MATCH_ORDER = sorted(
    ((syn, key) for key, syns in FIELD_SYNONYMS.items() for syn in syns),
    key=lambda pair: -len(pair[0]),
)


def load_profile(repo_root: str | Path = ".") -> tuple[dict, bool]:
    """Return (profile, is_real).  Falls back to the example template."""
    root = Path(repo_root)
    real = root / PROFILE_FILE
    if real.exists():
        return {**DEFAULT_PROFILE, **json.loads(real.read_text())}, True
    example = root / PROFILE_EXAMPLE
    if example.exists():
        return {**DEFAULT_PROFILE, **json.loads(example.read_text())}, False
    return dict(DEFAULT_PROFILE), False


def write_example_profile(repo_root: str | Path = ".") -> Path:
    path = Path(repo_root) / PROFILE_EXAMPLE
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_PROFILE, indent=2) + "\n")
    return path


def match_field(field_name: str) -> str | None:
    """Map a PDF form-field name to a vendor-profile key, or None."""
    normalized = re.sub(r"[_\-\.]+", " ", field_name).strip().lower()
    if not normalized:
        return None
    # "E-Mail Address" must resolve to email, not address.
    if re.search(r"\be ?mail\b", normalized):
        return "email"
    for syn, key in _MATCH_ORDER:
        if syn in normalized:
            return key
    return None


def fill_pdf(src: Path, dst: Path, profile: dict) -> tuple[int, int]:
    """Fill text fields of ``src`` into ``dst``.

    Returns (fields_filled, fields_total).  (0, 0) means the PDF has no
    form fields at all (flat scan) — nothing was written.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    fields = reader.get_fields() or {}
    if not fields:
        return 0, 0

    values: dict[str, str] = {}
    for name, field in fields.items():
        if field.get("/FT") != "/Tx":        # text fields only; leave
            continue                          # checkboxes/choices alone
        key = match_field(name)
        if key and profile.get(key):
            values[name] = str(profile[key])

    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        try:
            writer.update_page_form_field_values(
                page, values, auto_regenerate=False
            )
        except Exception as exc:              # malformed page annotations
            log.debug("field update skipped on a page of %s: %s", src, exc)
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as fh:
        writer.write(fh)
    return len(values), len(fields)


def write_answer_sheet(dst: Path, profile: dict, context: str) -> Path:
    """Copy-paste sheet for flat PDFs and online forms."""
    lines = [
        f"# Application answers — {context}",
        "",
        "This application could not be auto-filled (scanned/flat PDF or an",
        "online form). Copy these values in:",
        "",
    ]
    for key, value in profile.items():
        label = key.replace("_", " ").title()
        lines.append(f"- **{label}:** {value}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + "\n")
    return dst
