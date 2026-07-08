from pathlib import Path

import pytest

from fnscraper import export, importer, pdf_fill
from fnscraper.apps import decode_fn_link, show_slug, slugify, _score_link
from fnscraper.scoring import score_event
from tests.test_scoring import make_event


def sample():
    return [
        score_event(make_event(url="https://festivalnet.com/1/C-O/Craft-Shows/x")),
        score_event(make_event(
            event_id="2", name="Pipe | Fest, with commas", state="PA",
            url="https://festivalnet.com/2/P-P/Food-Festivals/y",
            attendance=None,
        )),
    ]


# ---------------------------------------------------------------- importer
@pytest.mark.parametrize("fmt", ["csv", "xlsx", "md"])
def test_import_roundtrip(tmp_path, fmt):
    original = sample()
    export.export_all(original, tmp_path, "sel")
    loaded = importer.load_shows(tmp_path / f"sel.{fmt}")
    assert len(loaded) == 2
    by_id = {s.event.event_id: s for s in loaded}
    assert set(by_id) == {"1", "2"}
    a, b = by_id["1"], by_id["2"]
    assert a.event.url == "https://festivalnet.com/1/C-O/Craft-Shows/x"
    assert a.event.start_date == original[0].event.start_date
    assert a.event.attendance == 5000
    assert abs(a.breakdown.total_cost - original[0].breakdown.total_cost) < 0.01
    assert abs(a.breakdown.cost_per_jar - original[0].breakdown.cost_per_jar) < 0.01
    assert b.event.name == "Pipe | Fest, with commas"
    assert b.event.attendance is None
    assert b.breakdown.attendance_estimated is True


def test_import_rejects_foreign_files(tmp_path):
    f = tmp_path / "random.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        importer.load_shows(f)

    t = tmp_path / "nope.txt"
    t.write_text("x")
    with pytest.raises(ValueError):
        importer.load_shows(t)


# ---------------------------------------------------------------- pdf fill
def test_match_field_synonyms():
    assert pdf_fill.match_field("Business Name") == "business_name"
    assert pdf_fill.match_field("biz-Company_2") == "business_name"
    assert pdf_fill.match_field("Applicant Name") == "contact_name"
    assert pdf_fill.match_field("Name") == "contact_name"
    assert pdf_fill.match_field("E-Mail Address") == "email"
    assert pdf_fill.match_field("Description of Products") == "product_description"
    assert pdf_fill.match_field("Zip Code") == "zip"
    assert pdf_fill.match_field("qty_ordered") is None


def make_fillable_pdf(path, field_names):
    """Build a minimal AcroForm PDF with pypdf's object model."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, DictionaryObject, NameObject, RectangleObject,
        TextStringObject,
    )

    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    refs = ArrayObject()
    for i, name in enumerate(field_names):
        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): RectangleObject([80, 700 - 30 * i,
                                                  380, 720 - 30 * i]),
        })
        refs.append(w._add_object(widget))
    page[NameObject("/Annots")] = refs
    w._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): refs}
    )
    with open(path, "wb") as fh:
        w.write(fh)


def test_fill_pdf_with_real_acroform(tmp_path):
    src = tmp_path / "app.pdf"
    make_fillable_pdf(src, ["Business Name", "Email", "Widget Count"])

    profile = dict(pdf_fill.DEFAULT_PROFILE,
                   business_name="Jordo's Salsa", email="j@example.com")
    dst = tmp_path / "app__FILLED.pdf"
    filled, total = pdf_fill.fill_pdf(src, dst, profile)
    assert total == 3
    assert filled == 2                       # widget count has no synonym

    from pypdf import PdfReader
    fields = PdfReader(str(dst)).get_fields()
    assert fields["Business Name"].get("/V") == "Jordo's Salsa"
    assert fields["Email"].get("/V") == "j@example.com"


def test_fill_pdf_flat_returns_zero(tmp_path):
    from pypdf import PdfWriter
    src = tmp_path / "flat.pdf"
    w = PdfWriter()
    w.add_blank_page(612, 792)
    with src.open("wb") as fh:
        w.write(fh)
    assert pdf_fill.fill_pdf(src, tmp_path / "out.pdf", {}) == (0, 0)


def test_answer_sheet(tmp_path):
    p = pdf_fill.write_answer_sheet(tmp_path / "ANSWERS.md",
                                    {"business_name": "X"}, "Some Fest")
    text = p.read_text()
    assert "Some Fest" in text
    assert "**Business Name:** X" in text


# ---------------------------------------------------------------- apps utils
def test_decode_fn_link():
    assert decode_fn_link("/https-www-northcoastpromo-com") == \
        "https://www.northcoastpromo.com"
    assert decode_fn_link("/http-example-org") == "http://example.org"
    assert decode_fn_link("/craft-shows") is None


def test_slug_and_scoring_helpers():
    s = sample()[0]
    slug = show_slug(s)
    assert slug.startswith("2026-07-11_OH_")
    assert "/" not in slug and "|" not in slugify("a|b/c")
    assert _score_link("Vendor Application (PDF)", "https://x.com/app.pdf") >= 15
    assert _score_link("Our sponsors", "https://x.com/sponsors") < 0


def test_negative_keywords_block_permit_pdfs():
    from fnscraper.apps import DOWNLOAD_SCORE_THRESHOLD
    permit = _score_link("Block Party Permit Application",
                         "https://city.gov/PermitApplication.pdf")
    vendor = _score_link("Vendor Application 2026",
                         "https://fest.org/VendorApplication.pdf")
    assert permit < DOWNLOAD_SCORE_THRESHOLD
    assert vendor >= DOWNLOAD_SCORE_THRESHOLD


def test_name_tokens_and_relevance():
    from fnscraper.apps import _name_tokens, _relevance
    tokens = _name_tokens("Cleveland Irish Cultural Festival")
    assert tokens == {"cleveland", "irish", "cultural", "festival"}
    assert _relevance(tokens, "Cleveland Irish Cultural Festival — vendors") == 1.0
    assert _relevance(tokens, "City of Cleveland | permits") == 0.25
    assert _relevance(_name_tokens("Lancaster Festival"),
                      "Lancaster Archery Supply") == 0.5
