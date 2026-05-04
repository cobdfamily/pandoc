# pandoc

[![test](https://github.com/cobdfamily/pandoc/actions/workflows/test.yml/badge.svg)](https://github.com/cobdfamily/pandoc/actions/workflows/test.yml)

Universal document conversion service. A document in,
the same document in a different format out — driven
by `pandoc`.

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

29 writers, grouped by family:

- **Markdown / lightweight** (9): md, gfm, commonmark,
  rst, asciidoc, org, textile, mediawiki, dokuwiki
- **Document / e-book** (6): docx, odt, rtf, epub,
  epub2, fb2
- **Web** (2): html, html4
- **Print / typesetting** (4): latex, man, ms, texinfo
- **Structured / XML** (4): docbook, jats, opml, ipynb
- **Slides** (2): revealjs, beamer
- **Other** (2): plain, json (pandoc AST)

Adding a writer is a `formats.yaml` edit + a
`tools.yaml` edit (one new endpoint block, copying any
existing one). CI fails fast if the two drift.

### What's not exposed

- **PDF.** pandoc's PDF path needs a TeX backend
  (texlive, ~5 GB) or weasyprint / wkhtmltopdf. None
  are bundled in v0.1.0 to keep the image small;
  operators who need PDF can layer a downstream image
  with their preferred backend. For office-format ->
  PDF, `cobdfamily/outofoffice`'s `/v1/to/pdf` covers
  the common cases via LibreOffice.

## The standalone flag

`standalone` defaults to `true`: pandoc emits a
complete document (HTML with `<!DOCTYPE html>` /
`<html>` / `<body>`, LaTeX with `\documentclass`, etc.)
rather than a fragment. Pass `standalone=false` to get
just the body content -- useful when embedding the
output in a template.

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
- **No PDF (in v0.1.0).** See above.
- **No bibliography / citation processing.** pandoc
  supports `--citeproc` / `--bibliography`; not
  exposed yet. Operators who need it can layer a
  downstream image.
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
