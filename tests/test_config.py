"""Static checks on config/tools.yaml + config/formats.yaml.

pandoc has no Python source of its own — the HTTP surface
is declared in config/tools.yaml and the writer catalog
lives in config/formats.yaml. These tests pin both shapes
so a careless edit can't ship a malformed config or a
catalog that drifts from the YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config" / "tools.yaml"
FORMATS_YAML = REPO_ROOT / "config" / "formats.yaml"


def _load_catalog():
    return yaml.safe_load(FORMATS_YAML.read_text())


# Slugs are derived from the catalog at import time so
# adding an entry to the catalog automatically propagates
# here. The /to/<slug> endpoints in tools.yaml are then
# verified against this list by tests below.
EXPECTED_SLUGS = [c["slug"] for c in _load_catalog()]
VALID_FAMILIES = {
    "markdown", "document", "web", "print",
    "structured", "slides", "other",
}


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(CONFIG.read_text())


@pytest.fixture(scope="module")
def endpoints(cfg):
    return cfg["endpoints"]


@pytest.fixture(scope="module")
def convert_endpoints(endpoints):
    """Just the conversion endpoints (/to/<slug>). Excludes
    /formats discovery (GET, no upload, runs cat-yaml-as-json
    instead of pandoc-convert)."""
    return [e for e in endpoints if e["name"] != "formats"]


@pytest.fixture(scope="module")
def catalog():
    return _load_catalog()


@pytest.fixture(scope="module")
def by_slug(catalog):
    return {entry["slug"]: entry for entry in catalog}


# ---------------------------------------------------------------------------
# top-level shape
# ---------------------------------------------------------------------------


def test_yaml_parses(cfg):
    assert isinstance(cfg, dict)
    assert "endpoints" in cfg
    assert isinstance(cfg["endpoints"], list)


def test_top_level_metadata(cfg):
    assert cfg["api"]["title"] == "pandoc"
    # API surface lives under /v1/. Liveness ``/`` and
    # FastAPI's ``/docs`` stay at the root.
    assert cfg["api"]["default_root"] == "/v1"
    assert cfg["logging"]["level"] in {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_no_endpoint_overrides_default_root(endpoints):
    """Fleet policy across every url2code consumer
    (needle, outofoffice, brl, pandoc, ...): one
    api.default_root for the entire surface, no
    per-endpoint ``root:`` escape hatch.

    url2code's EndpointConfig accepts a ``root:`` field
    that overrides the api.default_root for a single
    endpoint; nobody in the fleet uses that, and a
    future /v2 cutover wants to be a one-line edit in
    the api block rather than an audit of every
    endpoint."""
    for e in endpoints:
        assert "root" not in e, (
            f"{e['name']} sets a per-endpoint root override; "
            "the fleet rule is one default_root for the whole "
            "surface"
        )


def test_no_unexpected_endpoints(endpoints):
    """The surface is exactly: /formats + one /to/<slug> per
    catalog entry. Anything else fails here."""
    routes = {e["route"] for e in endpoints}
    expected = {f"/to/{slug}" for slug in EXPECTED_SLUGS}
    expected.add("/formats")
    extra = routes - expected
    missing = expected - routes
    assert not extra, f"unexpected routes: {sorted(extra)}"
    assert not missing, f"missing routes: {sorted(missing)}"


def test_endpoint_count_matches_catalog(convert_endpoints):
    """Number of /to/<slug> endpoints equals the number of
    catalog entries. Drift here means YAML or catalog needs
    updating."""
    assert len(convert_endpoints) == len(EXPECTED_SLUGS)


def test_routes_are_unique(endpoints):
    pairs = [(e.get("method", "GET"), e["route"]) for e in endpoints]
    assert len(pairs) == len(set(pairs)), f"duplicate routes: {pairs}"


def test_endpoint_names_are_unique(endpoints):
    names = [e["name"] for e in endpoints]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# command shape -- conversion endpoints all run pandoc-convert
# ---------------------------------------------------------------------------


def test_every_convert_endpoint_calls_pandoc_convert(convert_endpoints):
    """The wrapper at /app/bin/pandoc-convert is the only
    binary the conversion endpoints run. /formats uses
    cat-yaml-as-json (provided by url2code:>=1.0.7) and is
    excluded."""
    for e in convert_endpoints:
        assert e["command"]["executable"] == "/app/bin/pandoc-convert", \
            f"{e['name']} uses unexpected executable"


def test_every_convert_endpoint_passes_three_args(convert_endpoints):
    """The wrapper takes exactly three positional args:
    ``<input_path> <output_path> <writer>``. Anything beyond
    that is appended by url2code's flag rendering at request
    time."""
    for e in convert_endpoints:
        args = e["command"]["args"]
        assert len(args) == 3, \
            f"{e['name']} passes {len(args)} args, expected 3"
        assert args[0] == "{input_path}"
        assert args[1] == "{output_path}"


def test_writer_arg_matches_catalog(convert_endpoints, by_slug):
    """The third wrapper arg is the pandoc writer name. It
    must match the catalog's `writer` field for the matching
    slug -- otherwise /to/md might silently emit `gfm` (or
    vice versa)."""
    for e in convert_endpoints:
        slug = e["route"].rsplit("/", 1)[-1]
        expected_writer = by_slug[slug]["writer"]
        actual_writer = e["command"]["args"][2]
        assert actual_writer == expected_writer, \
            f"{e['name']}: writer arg {actual_writer!r} " \
            f"!= catalog {expected_writer!r}"


def test_every_convert_endpoint_has_a_timeout(convert_endpoints):
    """pandoc can hang on malformed input. A missing timeout
    means the request would block forever."""
    for e in convert_endpoints:
        timeout = e["command"].get("timeout_seconds")
        assert timeout is not None, f"{e['name']} missing timeout"
        assert timeout >= 30, \
            f"{e['name']} timeout {timeout}s too low"


# ---------------------------------------------------------------------------
# upload shape
# ---------------------------------------------------------------------------


def test_every_convert_endpoint_has_one_document_upload(convert_endpoints):
    """Clients shouldn't have to remember a different field
    name per endpoint. ``document`` is the convention."""
    for e in convert_endpoints:
        uploads = e.get("uploads") or []
        assert len(uploads) == 1, \
            f"{e['name']} has {len(uploads)} uploads, expected 1"
        upload = uploads[0]
        assert upload["field_name"] == "document"
        assert upload["placeholder"] == "input_path"


def test_input_placeholder_is_substituted(convert_endpoints):
    for e in convert_endpoints:
        assert "{input_path}" in e["command"]["args"], \
            f"{e['name']} missing {{input_path}} arg"


# ---------------------------------------------------------------------------
# output_files
# ---------------------------------------------------------------------------


def test_every_convert_endpoint_declares_one_output_file(convert_endpoints):
    """url2code generates a download URL only for declared
    output_files. /formats has none and is excluded."""
    for e in convert_endpoints:
        outputs = e.get("output_files") or []
        assert len(outputs) == 1
        out = outputs[0]
        assert out["placeholder"] == "output_path"
        assert out["filename_placeholder"] == "output_filename"


def test_output_suffix_matches_catalog(convert_endpoints, by_slug):
    """The output suffix becomes the file extension on the
    download URL. It must match the catalog's `ext` field
    (note: many slugs share an extension -- md/gfm/commonmark
    all -> .md; html/revealjs/html4 all -> .html)."""
    for e in convert_endpoints:
        slug = e["route"].rsplit("/", 1)[-1]
        expected_ext = by_slug[slug]["ext"]
        suffix = e["output_files"][0]["suffix"]
        assert suffix == f".{expected_ext}", \
            f"{e['name']}: suffix {suffix!r} != .{expected_ext}"


def test_output_placeholder_is_substituted(convert_endpoints):
    for e in convert_endpoints:
        assert "{output_path}" in e["command"]["args"], \
            f"{e['name']} missing {{output_path}} arg"


# ---------------------------------------------------------------------------
# request flags -- from + standalone
# ---------------------------------------------------------------------------


def test_every_convert_endpoint_exposes_from_and_standalone(convert_endpoints):
    """Both flags exposed on every conversion endpoint:
    `from` (text, optional, no default -- pandoc auto-detects
    from filename extension if omitted) and `standalone`
    (bool, default true -- most consumers want complete
    documents, not fragments)."""
    for e in convert_endpoints:
        flags = {f["name"]: f for f in e["request"]["flags"]}
        assert set(flags) == {"from", "standalone"}, \
            f"{e['name']} flags: {sorted(flags)} != {{from, standalone}}"
        assert flags["from"]["flag"] == "-f"
        assert flags["from"]["type"] == "text"
        assert flags["standalone"]["flag"] == "-s"
        assert flags["standalone"]["type"] == "bool"


def test_every_convert_endpoint_defaults_standalone_true(convert_endpoints):
    """Default-on standalone -- anyone wanting a fragment
    has to opt out by passing standalone=false."""
    for e in convert_endpoints:
        assert e.get("defaults", {}).get("standalone") == "true", \
            f"{e['name']} missing standalone default"


# ---------------------------------------------------------------------------
# output mode
# ---------------------------------------------------------------------------


def test_every_convert_endpoint_uses_text_output_mode(convert_endpoints):
    """The wrapper writes pandoc's stderr -> stdout via 2>&1
    on success or failure; there's no structured output to
    parse. The deliverable is the converted file (download_url),
    not the response body."""
    for e in convert_endpoints:
        assert e["output"]["mode"] == "text"


# ---------------------------------------------------------------------------
# formats.yaml -- the canonical catalog
# ---------------------------------------------------------------------------


def test_catalog_parses(catalog):
    """formats.yaml must be a list of {slug, ext, writer,
    name, family} objects."""
    assert isinstance(catalog, list)
    assert len(catalog) >= 1
    required = {"slug", "ext", "writer", "name", "family"}
    for entry in catalog:
        assert isinstance(entry, dict)
        assert required <= set(entry.keys()), \
            f"entry {entry!r} missing keys {required - set(entry.keys())}"


def test_catalog_slugs_are_unique(catalog):
    slugs = [e["slug"] for e in catalog]
    assert len(slugs) == len(set(slugs))


def test_catalog_slugs_are_url_safe(catalog):
    """Slugs become path components on /to/<slug>. Letters,
    digits, hyphens; not empty."""
    pattern = re.compile(r"^[a-z0-9][a-z0-9-]*$")
    for entry in catalog:
        assert pattern.match(entry["slug"]), \
            f"slug {entry['slug']!r} is not URL-safe"


def test_catalog_exts_are_filename_safe(catalog):
    """ext becomes the file extension on the download URL.
    Letters and digits only; not empty."""
    pattern = re.compile(r"^[a-z0-9]+$")
    for entry in catalog:
        # ext might be int (man "1") if YAML parses it as
        # such; treat as string.
        ext = str(entry["ext"])
        assert pattern.match(ext), \
            f"slug {entry['slug']!r}: ext {ext!r} not safe"


def test_catalog_family_is_known(catalog):
    """family drives doc grouping + per-family timeouts."""
    for entry in catalog:
        assert entry["family"] in VALID_FAMILIES, \
            f"slug {entry['slug']!r} has unknown family " \
            f"{entry['family']!r}"


def test_catalog_writers_look_like_pandoc_writers(catalog):
    """Loose sanity check on writer names. pandoc's writer
    names are lowercase, may contain underscores, sometimes
    digits (html4, html5, docbook5, epub2, epub3).
    Anything ALL-CAPS / kebab-case is almost certainly a
    typo."""
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    for entry in catalog:
        assert pattern.match(entry["writer"]), \
            f"slug {entry['slug']!r}: writer {entry['writer']!r} " \
            "doesn't look like a pandoc writer name"


# ---------------------------------------------------------------------------
# /formats -- discovery endpoint
# ---------------------------------------------------------------------------


def test_formats_endpoint_is_get(endpoints):
    """Discovery is parameter-less and read-only -- GET is
    the honest verb."""
    e = next(e for e in endpoints if e["name"] == "formats")
    assert e["method"] == "GET"


def test_formats_endpoint_returns_native_json(endpoints):
    e = next(e for e in endpoints if e["name"] == "formats")
    assert e["output"]["mode"] == "native_json"


def test_formats_endpoint_reads_catalog_file(endpoints):
    """The endpoint runs cat-yaml-as-json on the YAML
    catalog. cat-yaml-as-json ships in url2code:>=1.0.7."""
    e = next(e for e in endpoints if e["name"] == "formats")
    assert e["command"]["executable"] == "/app/bin/cat-yaml-as-json"
    assert e["command"]["args"] == ["/app/config/formats.yaml"]
