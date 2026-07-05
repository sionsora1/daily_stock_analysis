# SearXNG Maintenance Guide

This repo bundles SearXNG as a sidecar service under `docker/sidecars/searxng/`.
The goal is to keep the search service versioned with the main app while still
running it as an independent container.

## Files To Know

- `docker/docker-compose.yml`: starts the sidecar and wires the app to it
- `docker/sidecars/searxng/settings.yml`: SearXNG runtime settings
- `docs/searxng-local.md`: user-facing usage notes

## Start And Restart

- Start the full stack with `docker compose -f docker/docker-compose.yml up -d`
- Restart only SearXNG with `docker compose -f docker/docker-compose.yml restart searxng`
- Recreate everything after a config change with `docker compose -f docker/docker-compose.yml up -d --build`

## Upgrade Flow

- Update the SearXNG image tag in `docker/docker-compose.yml`
- Keep `docker/sidecars/searxng/settings.yml` minimal and compatible with the new image
- Run `docker compose -f docker/docker-compose.yml config` before committing
- Rebuild the stack and confirm `http://127.0.0.1:8899/search?format=json&q=test` still works

## What Usually Breaks

- The Docker daemon is not running
- The `settings.yml` path in Compose is stale or renamed
- Proxy settings are missing when upstream search engines require them, or they point to a local-only address that the container cannot reach
- SearXNG returns HTML only because JSON output is not enabled
- The local instance is healthy, but the news query has no usable results and the app falls back to Tavily

## Troubleshooting Checklist

1. Check containers with `docker compose -f docker/docker-compose.yml ps`
2. Open the local endpoint at `http://127.0.0.1:8899/search?q=test&format=json`
3. Confirm the app logs show `实例=http://127.0.0.1:8899` or `实例=http://searxng:8080`
4. If the app still falls back, inspect whether the returned results are too old or lack publish dates
5. If the container refuses to start, check Docker Desktop, proxy reachability, and the mounted settings file

## Maintenance Notes

- Keep the sidecar independent from the Python runtime
- Keep proxy settings optional and environment-driven; do not hard-code a local-only proxy into the image or Compose file
- Prefer updating `docker/sidecars/searxng/settings.yml` over adding new app code when the issue is only search service behavior
- If you change the search precedence again, update both this file and `docs/searxng-local.md`
