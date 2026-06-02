# pandoc image: cobdfamily/url2code base + pandoc.
#
# No Python source in this repo (tests aside). The HTTP
# surface is entirely defined in config/tools.yaml --
# url2code reads it on startup and registers the FastAPI
# routes from it.
#
# One route per supported target format under /v1/to/<slug>,
# plus /v1/formats discovery. Source format auto-detected
# from the upload's filename extension; override with the
# `from` form field. Each route returns JSON with a
# download_url for the converted output (url2code's built-in
# output_files mechanism).
#
# PDF output is intentionally NOT exposed in v0.1.0 -- pandoc
# needs a TeX backend (texlive, ~5 GB) or weasyprint /
# wkhtmltopdf for PDF, and bundling either materially bloats
# the image. Operators who need PDF can layer a downstream
# image with their preferred backend.

ARG URL2CODE_TAG=1.0.8
FROM kibble.apps.blindhub.ca/cobdfamily/url2code:${URL2CODE_TAG}

USER root

# pandoc is the converter; the apt package is self-contained
# (no LaTeX deps). pandoc-data is pulled in transitively for
# the readers/writers' shared resources.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        pandoc \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# PDF output without a TeX backend: pandoc's
# --pdf-engine=weasyprint renders HTML/CSS to PDF. weasyprint
# is a Python package; install it into the base image's venv so
# its `weasyprint` console script lands on PATH for pandoc to
# invoke. The libpango* libs + a base font above are weasyprint's
# runtime system dependencies.
RUN uv pip install --no-cache --python /app/.venv/bin/python weasyprint

# Pre-create temp tree as root + chown to runtime user so
# upload writes and converted-output writes both succeed
# without further chowns at request time.
RUN mkdir -p /tmp/pandoc/uploads /tmp/pandoc/outputs \
 && chown -R url2code:url2code /tmp/pandoc

# Replace url2code's bundled example tools.yaml with
# pandoc's, and ship the format catalog alongside it.
COPY --chown=url2code:url2code config /app/config

# Wrapper script that bridges three pandoc / url2code
# quirks (see bin/pandoc-convert for the inline rationale).
# cat-yaml-as-json is provided by url2code:>=1.0.7 itself
# (lives at /app/bin/cat-yaml-as-json in the base layer);
# this image's bin/ COPY layers on top without clobbering
# it.
COPY --chown=url2code:url2code bin /app/bin
RUN chmod 0755 /app/bin/pandoc-convert

USER url2code

# CMD inherited from the base image
# (uvicorn url2code.main:app --host 0.0.0.0 --port 8000)
# is preserved; ENTRYPOINT is unset.
