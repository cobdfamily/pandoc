# Changelog

All notable changes to pandoc. Format roughly follows
[Keep a Changelog](https://keepachangelog.com); dates
are ISO 8601 in UTC.

Pre-existing release tags (if any) are still visible
via `git log --tags --oneline`; this file starts
empty and is filled forward from this point.

## [Unreleased]

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

[1.0.0]: https://github.com/cobdfamily/pandoc/commits/v1.0.0
