# Hosting

One always-on process runs everything: `python3 -m movie_night.serve` (see the Dockerfile). It polls the household chat, runs the watchlist sync daily, and answers `GET /health`.

## What any host needs

| Setting | Value |
|---|---|
| Build | The repo's `Dockerfile` |
| Persistent volume | Mounted at `/data` (film cache, agent state, session history; a few MB) |
| Health check | `GET /health` on `$PORT` (the host usually sets `PORT`; default 8080) |
| `LINQ_TOKEN` | Linq API token (secret) |
| `TMDB_TOKEN` | TMDB API Read Access Token, the long `eyJ…` one (secret) |
| `MNA_CHAT_ID` | The household group chat id |
| `MNA_LETTERBOXD_USER` | Optional, default `chucklee` |
| `SYNC_HOUR_UTC` | Optional, default `10` |

Run exactly one instance. Two would both answer "movie night?".

On first boot there's no film cache, so the agent waits for the initial sync (about 25 minutes for ~1,100 films) before it responds. After that, restarts are instant.

## Railway (recommended)

1. Create a project and pick **Deploy from GitHub repo**, then choose `chuckmlee/movie-night-agent`. It builds from the Dockerfile.
2. On the service, add the variables above.
3. Add a **volume** mounted at `/data`.
4. The health check (`/health`), restart policy and single replica come from `railway.json`.
5. Deploy. Merges to `main` redeploy automatically.

## Webhooks (later)

`POST /linq` logs raw Linq webhook events to `/data/webhook-events.jsonl`, so we can check their shape before relying on them. Polling stays the source of truth until then. The endpoint isn't authenticated yet, so add Linq's signature check before it does anything more than log.
