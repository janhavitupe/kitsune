# Kitsune

**Version control for digital artists.** Git tracks lines of code; Kitsune tracks the sky, the hair, the lighting.

Save versions of a piece, branch to try ideas, and compare any two versions with a before/after slider. Coming next: changed areas named region by region ("sky", "left figure's hair") with a plain-words commit message, and the ability to pull back just one region from an old version.

> Built for the Meta Global AI Developer Hackathon (indie track). Work in progress.

## Status

| Feature | Status |
| --- | --- |
| Version timeline with branches | ✅ |
| Before/after slider and side-by-side compare | ✅ |
| Semantic visual diff (SAM 3.1 + Muse Spark) | in progress |
| Auto commit messages | in progress |
| Region cherry-pick and smart merge | planned |
| Voice notes, search, studio assistant | planned |

## Run locally

Requires Python 3.11+ and Node 20+.

```bash
# 1. Config: copy and fill in (the app runs without a key; AI features need one)
cp .env.example .env

# 2. Backend: http://127.0.0.1:8000 (API docs at /docs)
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Front end, in a second terminal: http://localhost:5173
cd frontend
npm install
npm run dev
```

Data (images, thumbnails, SQLite) goes to `data/` at the repo root by default.

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest      # macOS/Linux: .venv/bin/python -m pytest
```

## Probe the Model API

Once `MODEL_API_KEY` is in `.env`, check model ids and response shapes:

```bash
backend/.venv/Scripts/python scripts/probe_model_api.py
```

Raw responses are saved to `scripts/probe_out/` (gitignored).

## Layout

```
backend/   FastAPI app: routers, services, AI gateway (app/ai), SQLite schema
frontend/  React + Vite + Tailwind: timeline, compare slider, side by side
scripts/   probe and seed scripts
data/      local blobs, thumbnails and database (gitignored)
```
