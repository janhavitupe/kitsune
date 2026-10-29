"""Load a piece's history into a Kitsune backend: the demo artwork, in order, with branches, messages,
notes and merges. Run it against a local backend while building and against the deployed one before
recording.

    backend/.venv/Scripts/python scripts/seed_demo.py path/to/art
    backend/.venv/Scripts/python scripts/seed_demo.py path/to/art --backend https://kitsune-api.onrender.com

Without a manifest, every PNG/JPG in the folder is committed to main in file-name order. With
`kitsune-demo.json` in the folder, it says exactly what happens:

    {
      "name": "Hilltop wanderer",
      "steps": [
        {"image": "01-sketch.png", "message": "First color pass"},
        {"image": "02-dusk.png", "notes": [{"kind": "client", "text": "Can the sky be dusk?"}]},
        {"new_branch": "red-coat", "from": "v2"},
        {"image": "03-red.png", "branch": "red-coat"},
        {"image": "04-blue.png"},
        {"merge": "red-coat", "into": "main", "take": {"0": "source"}}
      ]
    }

Steps: an image commit (optional "branch", "message", "notes"), a new branch from a version, or a
merge (optional "take": conflict index -> "source" | "target").
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

IMAGE_TYPES = {".png", ".jpg", ".jpeg"}


class SeedError(RuntimeError):
    pass


def _ok(r: httpx.Response) -> dict | list:
    if r.status_code >= 400:
        raise SeedError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:200]}")
    return r.json()


def default_steps(folder: Path) -> list[dict]:
    return [{"image": p.name} for p in sorted(folder.iterdir()) if p.suffix.lower() in IMAGE_TYPES]


def wait_for_analysis(api: httpx.Client, repo_id: int, timeout_s: float = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        commits = _ok(api.get(f"/api/repos/{repo_id}/commits"))
        if all(c["analysis_status"] in ("done", "failed") for c in commits):
            return
        time.sleep(1)
    raise SeedError("Analysis didn't finish in time")


def seed(api: httpx.Client, folder: Path, manifest: dict | None = None, log=print) -> int:
    """Create the piece and replay the steps. Returns the repo id."""
    manifest = manifest or {"name": folder.name, "steps": default_steps(folder)}
    if not manifest["steps"]:
        raise SeedError(f"No images in {folder}")
    repo = _ok(api.post("/api/repos", json={"name": manifest.get("name") or folder.name}))
    rid = repo["id"]
    versions: dict[str, int] = {}  # "v3" -> commit id

    for i, step in enumerate(manifest["steps"], 1):
        if "image" in step:
            path = folder / step["image"]
            data = {"branch": step.get("branch", "main")}
            if step.get("message"):
                data["message"] = step["message"]
            with path.open("rb") as f:
                c = _ok(api.post(f"/api/repos/{rid}/commits", files={"image": (path.name, f)}, data=data))
            versions[f"v{c['seq']}"] = c["id"]
            for note in step.get("notes", []):
                _ok(api.post(f"/api/commits/{c['id']}/notes", data={"kind": note.get("kind", "artist"), "text": note["text"]}))
            log(f"{i:2d}. v{c['seq']} on {c['branch']}: {path.name}")
        elif "new_branch" in step:
            src = step.get("from")
            if src and src not in versions:
                raise SeedError(f"Step {i}: unknown version {src}")
            body = {"name": step["new_branch"], "from_commit": versions[src] if src else None}
            _ok(api.post(f"/api/repos/{rid}/branches", json=body))
            log(f"{i:2d}. branch {step['new_branch']} from {src or 'main'}")
        elif "merge" in step:
            wait_for_analysis(api, rid)
            plan = _ok(api.post(f"/api/repos/{rid}/merges", json={"source": step["merge"], "target": step.get("into", "main")}))
            c = _ok(api.post(f"/api/merges/{plan['id']}/resolve", json={"choices": step.get("take", {})}))
            versions[f"v{c['seq']}"] = c["id"]
            log(f"{i:2d}. v{c['seq']}: {c['message']}")
        else:
            raise SeedError(f"Step {i}: needs image, new_branch or merge")

    wait_for_analysis(api, rid)
    return rid


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model text on a Windows console
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder", type=Path)
    p.add_argument("--backend", default="http://127.0.0.1:8000")
    p.add_argument("--manifest", type=Path, help="default: kitsune-demo.json in the folder, if present")
    args = p.parse_args()

    manifest_path = args.manifest or args.folder / "kitsune-demo.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    try:
        with httpx.Client(base_url=args.backend, timeout=120) as api:
            rid = seed(api, args.folder, manifest)
    except (SeedError, httpx.HTTPError) as e:
        sys.exit(f"Seeding failed: {e}")
    print(f"\nDone: repo {rid}. Open the front end with ?repo={rid}")


if __name__ == "__main__":
    main()
