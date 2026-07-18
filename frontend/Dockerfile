#
# Production image for the React frontend, served by Nginx.
#
# Build context: frontend/
#   docker build --build-arg REACT_APP_BACKEND_URL= \
#       --tag app2-frontend:<tag> frontend
#
# REACT_APP_BACKEND_URL defaults to an empty string. Create React App bakes
# REACT_APP_* variables into the JS bundle at build time; with an empty
# value, frontend/src/lib/api.js's `${BACKEND_URL}/api` template literal
# resolves to the relative path "/api", so the built app calls the API
# same-origin through this image's own Nginx reverse proxy rather than any
# hard-coded hostname.

# ---------------------------------------------------------------------------
# Builder stage
# ---------------------------------------------------------------------------
FROM node:24-alpine AS builder

# node:24-alpine already bundles Yarn Classic 1.22.22 — assert that exact
# version rather than reinstalling it, so the build fails loudly if a future
# base-image update ever ships a different bundled version.
RUN test "$(yarn --version)" = "1.22.22"

WORKDIR /app

# Dependency layer first, for build caching.
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --non-interactive

# Application source.
COPY . .

ARG REACT_APP_BACKEND_URL=
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}

RUN CI=true GENERATE_SOURCEMAP=false yarn build

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
# nginxinc/nginx-unprivileged is the official Nginx-maintained image built
# specifically to run as a non-root user: its own upstream Dockerfile
# already creates and runs as uid/gid 101, already listens on 8080, and
# already relocates nginx's pid file and every temp/cache path under /tmp
# (all writable by that user) — none of that is retrofitted here. Verified
# via the Docker Hub API (this build sandbox blocks registry image pulls;
# see the accompanying report) that the exact tag 1.30.4-alpine exists,
# resolving to digest
# sha256:dcea25a6593307a74b09e59a47f8695c4d56943750e45add532ae0bf8b24bfd6.
FROM nginxinc/nginx-unprivileged:1.30.4-alpine AS runtime

# The base image's own default web content lives under
# /usr/share/nginx/html, which — unlike its pid/cache/temp paths — is not
# pre-chowned to the unprivileged user, so replacing it needs a temporary
# root step. The final runtime user below remains non-root.
USER root

RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder --chown=101:0 /app/build /usr/share/nginx/html
COPY --chown=101:0 nginx.conf /etc/nginx/conf.d/default.conf

USER 101

EXPOSE 8080

# wget is part of the base Alpine image (busybox) already — nothing extra
# installed solely for this healthcheck.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]
