# pandoc

[![test](https://github.com/cobdfamily/pandoc/actions/workflows/test.yml/badge.svg)](https://github.com/cobdfamily/pandoc/actions/workflows/test.yml)

A simple pandoc-driven document conversion API.

This is a YAML-defined microservice — no Python source
in the repo, only tests. The HTTP surface lives in
[`config/tools.yaml`](config/tools.yaml) and is
consumed by the upstream `cobdfamily/url2code` engine,
which pandoc's image is built on top of.

## What it does

One route per supported target format under
`/v1/to/<slug>`, plus a discovery endpoint:

```
POST /v1/to/<slug>
   body:    multipart/form-data, field `document`
   form:    standalone (bool, default true)
            from       (text, optional override)
   returns: JSON with output_files.output_path.download_url
            -> GET that URL to retrieve the converted bytes

GET /v1/formats
   Return the curated catalog of supported writers.
   Use the `slug` field of any entry as the path
   suffix on /v1/to/<slug>.
```

Source format auto-detected from the upload's filename
extension. To override (e.g. upload as `.txt` but tell
pandoc it's actually markdown), pass `from` as a form
field.

## Supported target formats

The catalog lives in
[`config/formats.yaml`](config/formats.yaml) and is
served at `/v1/formats` (converted to JSON on the wire
by `bin/cat-yaml-as-json` from the url2code base).

30 writers, grouped by family:

- **Markdown / lightweight** (9): md, gfm, commonmark,
  rst, asciidoc, org, textile, mediawiki, dokuwiki
- **Document / e-book** (7): docx, odt, rtf, epub,
  epub2, fb2, pdf
- **Web** (2): html, html4
- **Print / typesetting** (4): latex, man, ms, texinfo
- **Structured / XML** (4): docbook, jats, opml, ipynb
- **Slides** (2): revealjs, beamer
- **Other** (2): plain, json (pandoc AST)

Adding a writer is a `formats.yaml` edit + a
`tools.yaml` edit (one new endpoint block, copying any
existing one). CI fails fast if the two drift.

### PDF

`/v1/to/pdf` renders via **weasyprint** (an HTML/CSS
engine bundled in the image) — *not* a TeX backend, so
there's no ~5 GB texlive layer. pandoc lays the document
out as HTML and weasyprint paints the PDF. Good for prose,
reports, and articles; if you need LaTeX-grade math /
typesetting, layer a downstream image with texlive and
point `--pdf-engine` at it, or use
`cobdfamily/outofoffice`'s LibreOffice path for
office-document fidelity.

## The standalone flag

`standalone` defaults to `true`: pandoc emits a
complete document (HTML with `<!DOCTYPE html>` /
`<html>` / `<body>`, LaTeX with `\documentclass`, etc.)
rather than a fragment. Pass `standalone=false` to get
just the body content -- useful when embedding the
output in a template.

## Citations (citeproc)

Attach a bibliography and pandoc resolves `[@key]` citations and
appends a reference list. Both inputs are **optional uploads** —
omit them and you get a plain conversion:

```sh
curl -fsS -X POST \
     -F document=@./paper.md \
     -F bibliography=@./refs.bib \
     http://localhost:8000/v1/to/html | jq
```

- **`bibliography`** (optional file) — any format pandoc reads
  (`.bib`, CSL `.json`, `.yaml`, ...). When present, the wrapper
  runs pandoc with `--citeproc --bibliography=<file>`.
- **`csl`** (optional file) — a Citation Style Language `.csl`
  controlling citation/reference formatting (`--csl=<file>`);
  pandoc's default style is used when omitted.

Available on every `/v1/to/<slug>` target (html, pdf, docx, ...).
Requires url2code ≥ 2.1.0 (optional uploads).

## Quick start

```sh
docker compose up -d

# Discover available formats.
curl -s http://localhost:8000/v1/formats \
  | jq '.parsed_output[].slug'

# Markdown -> HTML, standalone:
curl -fsS -X POST \
     -F document=@./README.md \
     http://localhost:8000/v1/to/html | jq

# Markdown -> docx (the most common ask):
curl -fsS -X POST \
     -F document=@./README.md \
     http://localhost:8000/v1/to/docx | jq

# Override autodetection (file is .txt but is actually
# markdown):
curl -fsS -X POST \
     -F document=@./notes.txt \
     -F from=markdown \
     http://localhost:8000/v1/to/html | jq

# Then GET the download_url from any of the above
# responses to retrieve the converted bytes.
```

## How conversion works

1. url2code receives the multipart upload, writes it
   to `/tmp/pandoc/uploads/<random>.<orig-ext>`. The
   extension is preserved so pandoc can auto-detect
   the source format.
2. url2code generates a randomized output path
   `/tmp/pandoc/outputs/<random>.<target-ext>`.
3. url2code renders any `from` / `standalone` form
   fields into pandoc args via the `flag` +
   `valuePrefix` mechanism.
4. url2code invokes
   `/app/bin/pandoc-convert <input> <output> <writer> [extra...]`.
5. The wrapper runs
   `pandoc -t <writer> -o <output> [extra] <input>`
   merging stderr to stdout for visibility.
6. url2code responds with JSON containing a
   `download_url` for the converted bytes.

## What it doesn't do

- **No auth.** Gate the service at your reverse proxy
  (Traefik / nginx) — see DEPLOYMENT.md.
- **No persistence.** Uploads and converted outputs
  live in `/tmp` and are wiped on container restart.
- **No cross-format batching.** One request, one
  conversion.

## Files

```
config/tools.yaml             # the entire HTTP surface
config/formats.yaml           # canonical writer catalog
bin/pandoc-convert            # shell wrapper around pandoc
Dockerfile                    # url2code base + pandoc
docker-compose.yaml           # local-dev / production-shape
tests/test_config.py          # YAML + catalog structural tests
tests/test_e2e.py             # docker-compose round-trip
.github/workflows/test.yml    # CI: yaml + e2e + nightly
.github/workflows/release.yml # CI: tag-driven multi-arch push
```
