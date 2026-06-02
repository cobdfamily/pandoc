"""End-to-end tests for pandoc.

Assumes the docker-compose stack at the repo root is up
and reachable at http://localhost:8000. The CI workflow
builds the image locally and brings the stack up before
invoking pytest; locally, ``docker compose up -d`` is
enough.

Coverage:

  /                        liveness (service field, version)
  GET /v1/formats          curated catalog of writers
  POST /v1/to/<slug>       round-trip md -> html, rst, docx
                           (sample subset; rest pinned
                           structurally by test_config.py)
  POST /v1/to/<slug> + from form field
                           override pandoc's auto-detection
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests

PANDOC_BASE_URL = os.environ.get("PANDOC_BASE_URL", "http://localhost:8000")

# A short markdown source. Includes a heading, paragraph,
# and a link -- so an html conversion produces visibly
# distinct bytes from the input, and a docx isn't trivially
# empty.
SAMPLE_MARKDOWN = """\
# Hello from pandoc

This is a deterministic source document used by the E2E
tests. It includes a [link](https://example.com) so the
output's structure is non-trivial.
"""


@pytest.fixture(scope="module")
def source_md(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("doc") / "source.md"
    path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# liveness
# ---------------------------------------------------------------------------


def test_liveness_returns_pandoc_service():
    """``/`` reports ``service: pandoc``. The api.title ->
    service field plumbing landed in url2code 1.0.6."""
    r = requests.get(PANDOC_BASE_URL + "/", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "pandoc"
    assert body["status"] == "ok"
    assert body["version"]


# ---------------------------------------------------------------------------
# /v1/formats -- discovery
# ---------------------------------------------------------------------------


def test_formats_returns_curated_catalog():
    """GET /v1/formats returns the catalog as parsed_output:
    a list of {slug, ext, writer, name, family} entries."""
    r = requests.get(PANDOC_BASE_URL + "/v1/formats", timeout=5)
    assert r.status_code == 200, r.text
    body = r.json()
    catalog = body.get("parsed_output")
    assert isinstance(catalog, list)
    assert len(catalog) >= 1
    for entry in catalog:
        assert {"slug", "ext", "writer", "name", "family"} <= set(entry.keys())
    # Slugs used by the conversion tests below must be in
    # the catalog or the endpoints wouldn't exist.
    slugs = [e["slug"] for e in catalog]
    for slug in ("md", "html", "rst", "docx"):
        assert slug in slugs, f"catalog missing {slug!r}"


# ---------------------------------------------------------------------------
# round-trip: upload -> convert -> fetch the converted bytes
# ---------------------------------------------------------------------------


def _convert(
    source: Path, target_slug: str, source_filename: str = "source.md",
    extra_data: dict | None = None,
) -> requests.Response:
    """POST the source to /v1/to/<slug> and return the raw
    response. Caller asserts on it."""
    with open(source, "rb") as f:
        return requests.post(
            f"{PANDOC_BASE_URL}/v1/to/{target_slug}",
            files={"document": (source_filename, f, "text/plain")},
            data=extra_data or {},
            timeout=60,
        )


def _download(response: requests.Response) -> bytes:
    body = response.json()
    output_files = body.get("output_files") or {}
    entry = output_files.get("output_path")
    assert entry, f"no output_path entry: {body}"
    download_url = entry.get("download_url")
    assert download_url, f"no download_url: {entry}"
    if download_url.startswith("/"):
        download_url = PANDOC_BASE_URL + download_url
    r = requests.get(download_url, timeout=30)
    assert r.status_code == 200, \
        f"download {download_url} failed: {r.status_code} {r.text[:200]}"
    return r.content


def test_convert_md_to_html(source_md):
    """``md -> html`` -- the canonical pandoc smoke test.
    Output must be HTML5-shaped and contain content from
    the source."""
    r = _convert(source_md, "html")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("exit_code") == 0, body

    converted = _download(r)
    text = converted.decode("utf-8", errors="replace").lower()
    # standalone=true (default) -> full document with
    # <!DOCTYPE html> / <html> / <body>.
    assert "<!doctype html" in text or "<html" in text, \
        f"not HTML (head: {text[:200]!r})"
    # The link from the source should round-trip.
    assert "example.com" in text


def test_convert_md_to_rst(source_md):
    """``md -> rst`` -- text-to-text, lets us inspect the
    converted bytes directly."""
    r = _convert(source_md, "rst")
    assert r.status_code == 200, r.text
    converted = _download(r)
    text = converted.decode("utf-8", errors="replace")
    # rst headings use underline syntax (=== / ---), not # .
    assert "Hello from pandoc" in text
    # Exact format may vary, but at least one rst-style
    # underline or reference link should be present.
    assert "===" in text or "---" in text or "`_" in text, \
        f"not rst-shaped (head: {text[:200]!r})"


def test_convert_md_to_docx(source_md):
    """``md -> docx`` -- OOXML is a ZIP archive. Magic check
    is the ZIP signature. Confirms pandoc + the docx writer
    work in the image."""
    r = _convert(source_md, "docx")
    assert r.status_code == 200, r.text
    converted = _download(r)
    assert converted.startswith(b"PK\x03\x04"), \
        f"not a ZIP/DOCX (first bytes: {converted[:4]!r})"


def test_convert_md_to_pdf(source_md):
    """``md -> pdf`` via the weasyprint engine (no LaTeX).
    Output must carry the ``%PDF`` magic. Confirms pandoc, the
    weasyprint pdf-engine, and its system deps all work in the
    image."""
    r = _convert(source_md, "pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("exit_code") == 0, body
    converted = _download(r)
    assert converted.startswith(b"%PDF"), \
        f"not a PDF (first bytes: {converted[:8]!r})"


def test_convert_with_citeproc_resolves_citations(tmp_path_factory):
    """Upload a doc with a `[@key]` citation + a .bib bibliography
    (the optional `bibliography` upload) -> pandoc runs --citeproc,
    so the raw `[@key]` is replaced by a formatted citation and a
    reference list naming the cited work appears."""
    doc = tmp_path_factory.mktemp("cite") / "doc.md"
    doc.write_text("See [@knuth1984] for details.\n", encoding="utf-8")
    bib = tmp_path_factory.mktemp("cite") / "refs.bib"
    bib.write_text(
        "@book{knuth1984,\n"
        "  author = {Knuth, Donald E.},\n"
        "  title = {The TeXbook},\n"
        "  year = {1984},\n"
        "  publisher = {Addison-Wesley}\n"
        "}\n",
        encoding="utf-8",
    )
    with open(doc, "rb") as f, open(bib, "rb") as b:
        r = requests.post(
            f"{PANDOC_BASE_URL}/v1/to/html",
            files={
                "document": ("doc.md", f, "text/plain"),
                "bibliography": ("refs.bib", b, "text/plain"),
            },
            timeout=60,
        )
    assert r.status_code == 200, r.text
    assert r.json().get("exit_code") == 0, r.json()
    html = _download(r).decode("utf-8", errors="replace").lower()
    # The raw citation token is gone (citeproc resolved it)...
    assert "[@knuth1984]" not in html
    # ...and the cited work shows up in the rendered references.
    assert "knuth" in html


def test_convert_without_bibliography_is_plain(source_md):
    """Omitting the optional `bibliography` upload -> a plain
    conversion (no --citeproc), proving the optional upload is
    genuinely optional. A `[@key]` stays literal."""
    cite_src = source_md  # reuse fixture path object's dir
    # Build a tiny doc with a citation and post WITHOUT a bib.
    text = "Ref [@nobody2099] stays raw.\n"
    r = requests.post(
        f"{PANDOC_BASE_URL}/v1/to/html",
        files={"document": ("d.md", text.encode("utf-8"), "text/plain")},
        data={"from": "markdown"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    html = _download(r).decode("utf-8", errors="replace")
    assert "nobody2099" in html  # unresolved -> token survives


def test_standalone_default_produces_full_document(source_md):
    """Default standalone=true wraps with <!DOCTYPE html>.
    Pinned because a regression in the bool-flag default
    handling would silently emit fragments."""
    r = _convert(source_md, "html")
    assert r.status_code == 200
    text = _download(r).decode("utf-8", errors="replace").lower()
    assert "<!doctype html" in text or "<html" in text


def test_standalone_false_produces_fragment(source_md):
    """Passing standalone=false omits the doctype + outer
    html wrapper -- pandoc emits just the body fragment."""
    r = _convert(source_md, "html", extra_data={"standalone": "false"})
    assert r.status_code == 200, r.text
    text = _download(r).decode("utf-8", errors="replace").lower()
    assert "<!doctype html" not in text
    assert "<html" not in text
    # The content is still there (link from the source).
    assert "example.com" in text


def test_from_form_field_overrides_autodetect(source_md):
    """Explicit `from` form field bypasses pandoc's
    extension-based auto-detection. Upload as .txt (which
    pandoc would treat as plain text), but tell pandoc the
    source is markdown."""
    r = _convert(
        source_md,
        "html",
        source_filename="source.txt",
        extra_data={"from": "markdown"},
    )
    assert r.status_code == 200, r.text
    text = _download(r).decode("utf-8", errors="replace").lower()
    # The `# Hello from pandoc` heading should be rendered
    # as <h1> (markdown-aware), not as a literal `# ...`
    # (plain-text reader).
    assert "<h1" in text, \
        f"`from=markdown` didn't override autodetect (head: {text[:200]!r})"
