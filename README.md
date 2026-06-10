# AI Visibility Audit

Track brand visibility across AI assistants (ChatGPT, Gemini, Google AI
Mode, and Google AI Overview). Generate prompts, run them on a schedule,
and see how often your brand and your competitors get mentioned, cited,
and recommended.

## Screenshots

> Showing the built-in sample dataset — load it in one click, no API keys required.

**Responses** — every AI answer, with brand mentions, sentiment, and rank surfaced:

![Responses](assets/responses.png)

**Dashboard** — visibility, the GEO funnel, competitor share, and citation gaps at a glance:

![Dashboard](assets/dashboard.png)

**Topics** — where you win and where you lose, grouped by theme:

![Topics](assets/topics.png)

**Prompts** — the queries being measured, each with hit rate, position, and trend:

![Prompts](assets/prompts.png)

## Quick start

```bash
git clone https://github.com/syntropicsignal-ai/ai-visibility-audit.git
cd ai-visibility-audit
docker compose up
```

Then open http://localhost:5173. The web app walks you through entering
API keys on first visit — or you can load a sample dataset and explore
the whole product with no keys at all.

Migrations run automatically on container start. Keys you enter in
setup are saved locally to `api/data/config.json` (gitignored) and
applied to the running API immediately — no restart needed.

## Deploy

To run the published images instead of building from source:

```bash
curl -O https://raw.githubusercontent.com/syntropicsignal-ai/ai-visibility-audit/main/docker-compose.prod.yml
curl -o .env https://raw.githubusercontent.com/syntropicsignal-ai/ai-visibility-audit/main/.env.example
docker compose -f docker-compose.prod.yml up -d
```

Add your API keys to `.env` (or via the setup UI), then open
http://localhost:8080.

## What you need

- Docker Desktop (or Docker Engine + Compose v2)
- API keys: Gemini and Exa (prompt generation + analysis), DataForSEO
  (Google AI Overview + keyword signals). OpenAI is optional — it only
  powers the WildChat corpus stage of prompt generation.
- Bright Data — unlocks the ChatGPT, Gemini, and Google AI Mode sources,
  the main AI assistants this tool measures. Without it you'll track
  Google AI Overview only (via DataForSEO).

## Project layout

```
api/        FastAPI backend (Python, uv)
web/        Vue 3 frontend (TypeScript, Vite)
docker/     Container build files
```

## License

[AGPL-3.0](LICENSE).
