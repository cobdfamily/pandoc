# Deployment

pandoc ships as a container image to the kibble
registry on every `git tag v*`. The image is built on
top of `cobdfamily/url2code:<tag>` and adds:

- `pandoc` (`apt-get`) — the conversion engine
- `config/tools.yaml` — the entire HTTP surface
- `config/formats.yaml` — curated writer catalog
- `bin/pandoc-convert` — shell wrapper bridging
  url2code's request shape and pandoc's CLI

No Python source is added; the runtime is url2code's
FastAPI engine, configured by the YAML.

Requires `cobdfamily/url2code:>=1.0.7` for the
`cat-yaml-as-json` helper used by the `/v1/formats`
endpoint.

## Pre-flight checklist

- [ ] Public hostname for pandoc
      (e.g. `pandoc.cobd.ca` or
      `pandoc.openapis.ca`) with an A record. The
      service speaks plain HTTP on `:8000` behind
      your reverse proxy / TLS terminator.
- [ ] Disk space on `/tmp` for uploads + converted
      outputs. Each request writes the input under
      `/tmp/pandoc/uploads` and the output under
      `/tmp/pandoc/outputs`. Both are wiped on
      container restart.

## Image distribution

`.github/workflows/release.yml` builds and pushes the
image on every `git tag v*`:

```sh
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

Within a couple of minutes:

- `kibble.apps.blindhub.ca/cobdfamily/pandoc:0.1.0`
- `kibble.apps.blindhub.ca/cobdfamily/pandoc:latest`

Multi-arch (amd64 + arm64), matching the fleet.

The image is small — pandoc is well under 200 MB on
top of the url2code base.

## No built-in auth

Every endpoint is unauthenticated by default. Gate the
service at your reverse proxy if you don't want it
open to the world. Sample nginx snippet:

```nginx
location / {
    if ($http_x_api_key != "$PANDOC_API_KEY") {
        return 401;
    }
    client_max_body_size 50m;
    proxy_pass http://127.0.0.1:8000;
    proxy_read_timeout 60s;
}
```

For the openapis.ca marketplace shape, see
`infra/docs/auth-strategy.md` in the workspace root.

## Run

```yaml
# /opt/pandoc/docker-compose.yaml
services:
  pandoc:
    image: kibble.apps.blindhub.ca/cobdfamily/pandoc:0.1.0
    container_name: pandoc
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
```

```sh
mkdir -p /opt/pandoc
cd /opt/pandoc
docker compose pull
docker compose up -d
docker compose logs -f pandoc
```

Behind your TLS reverse proxy, route
`https://pandoc.cobd.ca/*` to `127.0.0.1:8000`.

## Verify

```sh
# Liveness:
curl -fsS https://pandoc.cobd.ca/

# Generated OpenAPI docs at /docs and /redocs.

# List supported writers:
curl -fsS https://pandoc.cobd.ca/v1/formats \
  | jq '.parsed_output[].slug'

# Markdown -> HTML:
curl -fsS -X POST \
  -F document=@./README.md \
  https://pandoc.cobd.ca/v1/to/html | jq
```

## Routine operations

### Upgrading

```sh
git tag -a v0.1.1 -m "Release 0.1.1"
git push origin v0.1.1
# CI builds and pushes.

sed -i 's|pandoc:[^ ]*|pandoc:0.1.1|' docker-compose.yaml
docker compose pull
docker compose up -d --no-deps pandoc
```

### Adding a target format

Two-step edit:

1. **Add the entry to `config/formats.yaml`** with
   `{slug, ext, writer, name, family}`. The catalog is
   the canonical source of truth and is served at
   `/v1/formats`.

   ```yaml
   - slug: zimwiki
     ext: txt
     writer: zimwiki
     name: Zim wiki markup
     family: markdown
   ```

   `writer` must be a name pandoc actually supports —
   run `pandoc --list-output-formats` in the container
   to see what's available.

2. **Add the matching endpoint block to
   `config/tools.yaml`.** Copy any existing block of
   the same family, change the route to
   `/to/<slug>`, the `suffix` to `.<ext>`, and the
   third command arg to `<writer>`.

CI fails fast if (1) and (2) drift -- `test_config.py`
asserts every catalog `slug` has a matching
`/to/<slug>` endpoint with consistent suffix and
writer.

### Adding PDF support

Layer a downstream image. Two reasonable paths:

```Dockerfile
# Lightweight: weasyprint as the PDF engine.
FROM kibble.apps.blindhub.ca/cobdfamily/pandoc:0.1.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        weasyprint \
 && rm -rf /var/lib/apt/lists/*
USER url2code
```

```Dockerfile
# Heavy: full LaTeX backend.
FROM kibble.apps.blindhub.ca/cobdfamily/pandoc:0.1.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base texlive-fonts-recommended \
        texlive-latex-extra texlive-xetex \
 && rm -rf /var/lib/apt/lists/*
USER url2code
```

Then add a `to-pdf` endpoint to the downstream's
tools.yaml. The wrapper passes
`--pdf-engine=weasyprint` (or `--pdf-engine=xelatex`)
via the `extra_args` mechanism.

### Backups

There is **nothing** to back up. pandoc is stateless —
uploads and outputs live in `/tmp` and are wiped on
container restart.

The `formats.yaml` catalog *is* worth versioning
(it lives in this repo).
