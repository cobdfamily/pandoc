# Changelog

All notable changes to pandoc. Format roughly follows
[Keep a Changelog](https://keepachangelog.com); dates
are ISO 8601 in UTC.

Pre-existing release tags (if any) are still visible
via `git log --tags --oneline`; this file starts
empty and is filled forward from this point.

## [Unreleased]

## [1.2.0] - 2026-06-01

### Added
- **Citations (citeproc).** Every `/v1/to/<slug>` endpoint now
  accepts two optional uploads: `bibliography` (any format pandoc
  reads) and `csl` (a Citation Style Language file). When a
  bibliography is supplied, `bin/pandoc-convert` runs pandoc with
  `--citeproc --bibliography=<file>` (+ `--csl=<file>` when given),
  resolving `[@key]` citations and emitting a reference list. Omit
  them and the conversion is unchanged. Built on url2code 2.1.0's
  optional uploads (`required: false`).

### Changed
- Base image `1.0.8 -> 2.1.0` (needs the optional-uploads feature;
  also brings the async executor + streamed upload I/O from 2.x).
- `api.version` `1.1.1 -> 1.2.0`.

## [1.1.1] - 2026-06-01

### Fixed
- PDF conversion (`/v1/to/pdf`) failed at runtime under the
  hardened read-only-root container:
  `pandoc: .: openTempFile: permission denied (Read-only file
  system)`. pandoc writes its PDF intermediate into the working
  directory (`/app`, read-only). `bin/pandoc-convert` now `cd`s
  into a tmpfs scratch dir for the PDF path before invoking
  pandoc, and compose sets `HOME=/tmp` so weasyprint's fontconfig
  cache lands on the writable tmpfs. Surfaced by the e2e suite
  running against the hardened compose; 1.1.0's PDF path was
  broken at runtime.

### Changed
- `api.version` `1.1.0 -> 1.1.1`.

## [1.1.0] - 2026-06-01

### Added
- **PDF output at `POST /v1/to/pdf`** — rendered via
  `pandoc --pdf-engine=weasyprint` (an HTML/CSS engine), so no
  TeX/texlive backend is bundled (avoids a ~5 GB layer). New
  `pdf` catalog entry (document family); the `pandoc-convert`
  wrapper special-cases the `pdf` writer to drop `-t` (pandoc
  infers PDF from the `.pdf` output extension) and pass
  `--pdf-engine=weasyprint`. The Dockerfile installs weasyprint
  + its runtime libs (`libpango-1.0-0`, `libpangoft2-1.0-0`,
  `fonts-dejavu-core`). New e2e test asserts the `%PDF` magic.

### Changed
- `api.version` `1.0.0 -> 1.1.0`.

### Deferred
- **citeproc / bibliography** (the other half of roadmap Sprint
  12) is not in this release. Wiring a bibliography file needs
  an *optional* multipart upload, but url2code uploads are
  mandatory — so citeproc needs either a dedicated endpoint or a
  new engine "optional uploads" feature first. Tracked as a
  follow-up.

## [1.0.0] - 2026-06-01

First tagged release of pandoc. Captures the existing surface
plus this sprint's standardization work.

### Added
- Document conversion over HTTP via the `pandoc` CLI: one
  `POST /v1/to/<slug>` route per supported target writer (29
  writers) plus `/v1/formats` discovery. Source format
  auto-detected from the upload extension; the `from` form
  field overrides. `standalone` defaults to true. Full surface
  in README.md.
- `api.version "1.0.0"` on `GET /` liveness (Sprint 1).
- Daily Grype CVE scan (`.github/workflows/cve-scan.yml`) over
  the image's oras-attached CycloneDX SBOM (Sprint 4).

### Changed
- Pinned the url2code base image to `1.0.8` (was `latest`) for
  reproducible builds (Sprint 1).
- Hardened `docker-compose.yaml`: read-only root, tmpfs `/tmp`,
  `cap_drop: ALL`, `no-new-privileges` (Sprint 4).

### Known limitations
- No PDF output yet (needs a TeX or weasyprint/wkhtmltopdf
  backend; roadmap Sprint 12).
- No bibliography / citeproc yet (roadmap Sprint 12). One
  conversion per request.

[1.2.0]: https://github.com/cobdfamily/pandoc/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/cobdfamily/pandoc/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/cobdfamily/pandoc/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/cobdfamily/pandoc/commits/v1.0.0
