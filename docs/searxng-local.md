# Local SearXNG Instance

This project now bundles a local SearXNG sidecar service in `docker/docker-compose.yml`.

## How it runs

- Compose starts a separate `searxng` container together with the app.
- The app containers talk to it at `http://searxng:8080` on the Compose network.
- Host-side Python runs can use `http://127.0.0.1:8899`.
- News queries try the local SearXNG instance first, then fall back to Tavily if needed.

## What it needs

- `docker compose up -d` to start the stack
- `docker/sidecars/searxng/settings.yml` mounted into the container
- Internet access for the SearXNG container itself
- Optional proxy variables from the host shell if upstream search engines need them

## Notes

- The instance does not require a separate API key at the project boundary.
- SearXNG itself is just a search aggregator; upstream search engines may still have their own limits or token requirements.
- If you stop the `searxng` service, news search in this project will stop working until it is started again.
- For maintenance and upgrade steps, see [docs/searxng-maintenance.md](/D:/softwares/MY_trading/daily_stock_analysis/docs/searxng-maintenance.md).
