# Kitsune 🦊

**Version control for digital artists.** Git tracks lines of code; Kitsune tracks the sky, the hair, the lighting.

Save versions of a painting, branch to try ideas, and see exactly what changed between any two versions, region by region and in plain words. Bring back just the old sky without losing today's figure. Merge two directions region by region. Pin the reason for a change, or a client's voice message, to the version it's about, and find it again by asking "the version before I changed the sky".

> Built for the Meta Global AI Developer Hackathon (indie track), with Muse Code.

## What it does

| | Feature | How |
| --- | --- | --- |
| 🕰 | **Timeline** of every version, one lane per branch, merges shown | Content-addressed image store (SHA-256 of pixels), SQLite |
| ↔ | **Compare** any two versions: before/after slider, synced side-by-side zoom | |
| 🔍 | **Semantic visual diff**: changed areas outlined and named, with how they changed (warmer, darker, more muted, redrawn) | OpenCV change mask in Lab space ∩ **SAM 3.1** regions; change split by kind of color shift |
| ✍ | **Auto commit messages**: "Warmed the sky into a dusk palette and tightened the left figure's silhouette." | **Muse Spark** with the measured changes as structured hints |
| ↩ | **Region cherry-pick**: bring one region of an old version back into the latest one | Feathered composite + **Muse Image** seam blending, guarded so it can only touch the seam |
| 🔀 | **Smart merge**: changes on one branch only are taken, changes on both become pick-one cards | Three-way region diff against the common ancestor |
| 🎙 | **Notes and client feedback**, typed or recorded, pinned to a version | **Muse Voice Transcribe**; Spark turns long client feedback into a list of requested changes |
| 🔎 | **Searchable history**, including "before / after / when I changed X" | SQLite FTS5 over messages, notes, captions, changed regions; Spark captions each version and reads the query |
| 🎨 | **Explore branches**: three palette variations, each on its own branch, keep or discard | **Muse Image** recolor that keeps the original drawing exactly |
| 🤖 | **Studio assistant**: "Take the sky from v4, keep today's figure, and warm it to match" | **Muse Wonder** plans, then calls Kitsune's own features as tools, every step shown live |
| 📖 | **Process story**: the history as a portfolio breakdown | **Muse Wonder** |
| 🔒 | **Private mode**: captions and search never leave your own model endpoint | Open weights (Muse Spark Open) on **Baseten**, back-filled with **Modal**; **Fireworks** as fallback |

Every AI feature has an honest fallback, so nothing breaks when a model is slow or offline: messages fall back to the measured summary, search to rules, explore to color-space presets, the story to one assembled from the history. Every model result is cached by its inputs, and `AI_OFFLINE=1` replays the demo with no model calls at all.

**History is append-only.** Cherry-picks, merges, explore variations and the assistant always make new versions; nothing is ever overwritten.

## Meta models and partners

| Model / partner | Job in Kitsune | Code |
| --- | --- | --- |
| SAM 3.1 | Names regions for the diff, cherry-pick and merge | `backend/app/ai/sam.py`, `services/segmentation.py` |
| Muse Spark | Commit messages, captions, note summaries, reading search queries | `backend/app/ai/spark.py` |
| Muse Image | Seam blending for cherry-pick and merge; explore variations | `backend/app/ai/image.py` |
| Muse Voice Transcribe | Voice notes and client voice feedback | `backend/app/ai/voice.py` |
| Muse Wonder | Studio assistant (tool use) and process story | `backend/app/ai/wonder.py`, `services/agent.py` |
| Open weights on Baseten / Fireworks | Private-mode captions and query reading | `backend/app/ai/openweights.py` |
| Modal | Parallel caption back-fill | `modal/backfill_captions.py` |
| Muse Code | Used to build Kitsune | |

All hosted models go through one gateway (`backend/app/ai/`) that caches every result by a hash of its inputs.

## Architecture

```
React + Vite + Tailwind (Vercel) ──HTTPS / SSE──▶ FastAPI (Render, one process, persistent disk)
  timeline · compare · overlay                      routers → services → ai/ gateway ──▶ Meta Model API
  notes · search · merge · assistant                  │          │          │            (SAM, Spark, Image,
                                                    SQLite    blob store   ai_cache        Voice, Wonder)
                                                    + FTS5    (sha256)     (input hash) ──▶ Baseten / Fireworks
```

A commit returns immediately; segmentation, the diff against its parent, the auto message, the caption and the search index are built in the background.

## Run locally

Requires Python 3.11+ and Node 20+.

```bash
cp .env.example .env              # add MODEL_API_KEY to turn the AI features on; everything else works without it

cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# second terminal
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Data goes to `data/` at the repo root. Load a demo history from a folder of images:

```bash
backend/.venv/Scripts/python scripts/seed_demo.py path/to/art      # see the script for the kitsune-demo.json format
```

## Deploy

**Backend on Render:** New → Blueprint → this repo. `render.yaml` sets up a Python web service with a 5 GB persistent disk (needs the Starter plan) and asks for `CORS_ORIGINS`, `MODEL_API_KEY` and the open-weights settings.

**Front end on Vercel:** import the repo with root directory `frontend`, and set `VITE_API_URL` to the Render URL. Then put the Vercel URL in the backend's `CORS_ORIGINS`.

Before the demo: seed it (`--backend https://<render-url>`), click through every feature once to warm the cache, then set `AI_OFFLINE=1` so the demo replays without depending on the model API. Uploads and AI requests are rate-limited per IP (`RATE_LIMIT_*` settings).

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest        # 108 tests; model calls are faked, never real
```

Other scripts: `scripts/probe_model_api.py` (check model ids and response shapes), `scripts/time_openweights.py` (Baseten vs Fireworks latency).

## Layout

```
backend/   FastAPI: routers/, services/ (diff, segmentation, cherry-pick, merge, search, agent…), ai/ (one file per model)
frontend/  React: timeline, compare + region overlay, notes, search, merge, explore, assistant, story
modal/     Modal caption back-fill
scripts/   probe, seed, timing
```

## Limitations and next steps

- Flattened PNG/JPG only; PSD layers are future work.
- A cherry-picked region is placed where it was; if the composition moved, it won't follow.
- Next: a `kitsune` CLI and a "commit on save" watcher for any paint app, a Krita plugin, an iPad share-sheet shortcut, and shared repos for client review.
