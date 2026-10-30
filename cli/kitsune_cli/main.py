"""kitsune: version control for artwork from the terminal, next to any paint app.

Point Kitsune at the file your paint app saves (Photoshop .psd, Krita .kra, OpenRaster .ora) or an
exported PNG/JPG, then commit, branch, diff,
merge and bring regions back like you would with git. Everything is stored in a Kitsune backend;
the browser UI shows the same history.

    kitsune init forest-girl.png            start tracking a file (first commit)
    kitsune commit -m "warmer sky"          save a version
    kitsune status                          has the file changed since the last version?
    kitsune log                             versions on this branch (--all for every branch)
    kitsune diff                            what changed in the last version (or: diff v3 v5)
    kitsune branch red-coat --from v2       new branch; `kitsune branch` lists them
    kitsune switch red-coat                 change branch and load its latest image into the file
    kitsune checkout v3                     load an old version into the file (or -o elsewhere.png)
    kitsune pick sky --from v3              bring the sky from v3 into this branch
    kitsune merge red-coat                  merge a branch into the current one
    kitsune note "client wants dusk"        attach a note to the latest version
    kitsune search "before the dusk sky"    search the history
    kitsune watch                           commit every time the paint app saves
    kitsune open                            open this piece in the browser

State lives in .kitsune/config.json in the folder where you ran `init`.
"""

import argparse
import hashlib
import json
import sys
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

STATE_DIR = ".kitsune"
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".psd", ".kra", ".ora"}
DEFAULT_BACKEND = "http://127.0.0.1:8000"
DEFAULT_WEB = "http://localhost:5173"


class CliError(RuntimeError):
    pass


@dataclass
class Workspace:
    root: Path  # the folder holding .kitsune/
    backend: str
    web: str
    repo_id: int
    file: str  # tracked image, relative to root
    branch: str = "main"
    synced: dict[str, str] = field(default_factory=dict)  # branch -> sha256 of the file bytes at its head

    @property
    def path(self) -> Path:
        return self.root / self.file

    def save(self) -> None:
        data = asdict(self)
        del data["root"]
        (self.root / STATE_DIR).mkdir(exist_ok=True)
        (self.root / STATE_DIR / "config.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def find(cls, start: Path) -> "Workspace":
        for folder in [start, *start.parents]:
            cfg = folder / STATE_DIR / "config.json"
            if cfg.exists():
                return cls(root=folder, **json.loads(cfg.read_text(encoding="utf-8")))
        raise CliError("Not a Kitsune folder. Run `kitsune init <image>` first.")

    def dirty(self) -> bool:
        return file_sha(self.path) != self.synced.get(self.branch)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def ok(r: httpx.Response):
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if r.status_code == 429:
            detail = f"rate limited, try again in {r.headers.get('Retry-After', 'a few')} seconds"
        raise CliError(f"{detail if isinstance(detail, str) else json.dumps(detail)} ({r.status_code})")
    return r.json() if r.content else None


def ago(iso: str) -> str:
    s = (datetime.now(UTC) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{int(s // size)}{unit} ago"
    return "just now"


def title(c: dict) -> str:
    analyzing = c["analysis_status"] in ("pending", "running")
    return c.get("message") or c.get("auto_message") or ("analyzing..." if analyzing else "Untitled version")


class Kitsune:
    """Each command is a method. `api` is any httpx.Client pointed at the backend (tests pass a TestClient)."""

    def __init__(self, api: httpx.Client, ws: Workspace | None, out=print):
        self.api = api
        self.ws = ws
        self.out = out

    # --- lookups -------------------------------------------------------------------------------

    def repo(self) -> dict:
        return ok(self.api.get(f"/api/repos/{self.ws.repo_id}"))

    def commits(self) -> list[dict]:
        return ok(self.api.get(f"/api/repos/{self.ws.repo_id}/commits"))

    def head(self, branch: str | None = None) -> dict | None:
        name = branch or self.ws.branch
        br = next((b for b in self.repo()["branches"] if b["name"] == name), None)
        if br is None:
            raise CliError(f"No branch '{name}'")
        if br["head_commit_id"] is None:
            return None
        return ok(self.api.get(f"/api/commits/{br['head_commit_id']}"))

    def version(self, ref: str, commits: list[dict] | None = None) -> dict:
        """'v3', '3' or 'HEAD' to a commit."""
        if ref.upper() == "HEAD":
            c = self.head()
            if c is None:
                raise CliError(f"Branch '{self.ws.branch}' has no versions yet")
            return c
        try:
            seq = int(ref.lower().removeprefix("v"))
        except ValueError:
            raise CliError(f"'{ref}' isn't a version. Use v3, 3 or HEAD.") from None
        for c in commits or self.commits():
            if c["seq"] == seq:
                return c
        raise CliError(f"No version v{seq}")

    def wait(self, commit_id: int, timeout_s: float) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            c = ok(self.api.get(f"/api/commits/{commit_id}"))
            if c["analysis_status"] in ("done", "failed") or time.monotonic() > deadline:
                return c
            time.sleep(0.5)

    def write_image(self, commit: dict, dest: Path) -> str:
        data = self.api.get(commit["image_url"])
        if data.status_code >= 400:
            ok(data)
        dest.write_bytes(data.content)
        return hashlib.sha256(data.content).hexdigest()

    # --- commands ------------------------------------------------------------------------------

    @classmethod
    def init(cls, api: httpx.Client, root: Path, image: Path, name: str | None, repo_id: int | None,
             backend: str, web: str, message: str | None, out=print) -> "Kitsune":
        if (root / STATE_DIR / "config.json").exists():
            raise CliError(f"{root} is already a Kitsune folder")
        if image.suffix.lower() not in IMAGE_TYPES:
            raise CliError("Kitsune reads .psd, .kra, .ora, .png and .jpg. Track one of those, or export a PNG from your paint app.")
        if not image.exists():
            raise CliError(f"{image} doesn't exist yet. Export it from your paint app first.")
        try:
            rel = image.resolve().relative_to(root.resolve())
        except ValueError:
            raise CliError("The image must be inside this folder") from None
        if repo_id is None:
            repo_id = ok(api.post("/api/repos", json={"name": name or image.stem}))["id"]
        else:
            ok(api.get(f"/api/repos/{repo_id}"))
        ws = Workspace(root=root, backend=backend, web=web, repo_id=repo_id, file=rel.as_posix())
        k = cls(api, ws, out)
        out(f"Tracking {ws.file} as piece #{repo_id}")
        if k.head() is None:
            k.commit(message, wait_s=0)
        else:
            out("The piece already has versions; run `kitsune status` to compare your file.")
        ws.save()
        return k

    def commit(self, message: str | None, wait_s: float = 20, allow_same: bool = False) -> dict | None:
        ws = self.ws
        if not ws.path.exists():
            raise CliError(f"{ws.file} is missing")
        sha = file_sha(ws.path)
        if not allow_same and sha == ws.synced.get(ws.branch):
            self.out("Nothing to commit: the file hasn't changed since the last version.")
            return None
        data = {"branch": ws.branch}
        if message:
            data["message"] = message
        with ws.path.open("rb") as f:
            c = ok(self.api.post(f"/api/repos/{ws.repo_id}/commits", files={"image": (ws.path.name, f)}, data=data))
        ws.synced[ws.branch] = sha
        ws.save()
        if wait_s and not message and c["parent_id"]:
            c = self.wait(c["id"], wait_s)
        self.out(f"v{c['seq']} on {c['branch']}: {title(c)}")
        return c

    def status(self) -> None:
        ws = self.ws
        head = self.head()
        self.out(f"On branch {ws.branch} · piece #{ws.repo_id} · {ws.file}")
        if head is None:
            self.out("No versions on this branch yet.")
        else:
            self.out(f"Latest: v{head['seq']} {title(head)} ({ago(head['created_at'])})")
        if not ws.path.exists():
            self.out(f"{ws.file} is missing.")
        elif ws.dirty():
            self.out("The file has changed since the latest version. `kitsune commit` to save it.")
        else:
            self.out("Nothing to commit.")

    def log(self, all_branches: bool = False, limit: int = 20) -> None:
        commits = self.commits()
        if not all_branches:
            # Walk first parents back from the head, so the log shows the history this branch was built on.
            by_id = {c["id"]: c for c in commits}
            head = self.head()
            chain, cur = [], head
            while cur is not None:
                chain.append(cur)
                cur = by_id.get(cur["parent_id"])
            commits = chain
        else:
            commits = commits[::-1]
        heads = {b["head_commit_id"]: b["name"] for b in self.repo()["branches"] if b["kind"] != "discarded"}
        if not commits:
            self.out("No versions yet.")
        for c in commits[:limit]:
            tag = f" ({heads[c['id']]})" if c["id"] in heads else ""
            notes = f"  [{c['note_count']} note{'s' * (c['note_count'] != 1)}]" if c["note_count"] else ""
            merge = "  [merge]" if c["merge_parent_id"] else ""
            self.out(f"v{c['seq']:<4} {c['branch']:<14} {ago(c['created_at']):>9}  {title(c)}{tag}{merge}{notes}")
        if len(commits) > limit:
            self.out(f"... {len(commits) - limit} older (use -n)")

    def diff(self, a: str | None, b: str | None) -> dict:
        commits = self.commits()
        if a and b:
            ca, cb = self.version(a, commits), self.version(b, commits)
        else:
            cb = self.version(a or "HEAD", commits)
            if cb["parent_id"] is None:
                raise CliError(f"v{cb['seq']} is the first version; nothing to compare it with")
            ca = next(c for c in commits if c["id"] == cb["parent_id"])
        if ca["seq"] > cb["seq"]:
            ca, cb = cb, ca
        d = ok(self.api.get("/api/diff", params={"from": ca["id"], "to": cb["id"]}))
        self.out(f"v{ca['seq']} -> v{cb['seq']}: {d['summary']}")
        for r in d["regions"]:
            hints = f" ({', '.join(r['hints'])})" if r["hints"] else ""
            self.out(f"  {r['label']:<24} {r['changed_ratio']:>4.0%} changed{hints}")
        if not d["regions"]:
            self.out("  No visible changes.")
        return d

    def branch(self, name: str | None, from_ref: str | None) -> None:
        if name is None:
            for b in self.repo()["branches"]:
                if b["kind"] == "discarded":
                    continue
                mark = "*" if b["name"] == self.ws.branch else " "
                head = ok(self.api.get(f"/api/commits/{b['head_commit_id']}")) if b["head_commit_id"] else None
                self.out(f"{mark} {b['name']:<20} {('v' + str(head['seq'])) if head else '(empty)'}")
            return
        src = self.version(from_ref) if from_ref else self.head()
        ok(self.api.post(f"/api/repos/{self.ws.repo_id}/branches",
                         json={"name": name, "from_commit": src["id"] if src else None}))
        self.out(f"Created branch {name}" + (f" from v{src['seq']}" if src else "") + f". `kitsune switch {name}` to work on it.")

    def switch(self, name: str, force: bool = False) -> None:
        ws = self.ws
        head = self.head(name)  # raises if the branch doesn't exist
        if ws.dirty() and not force:
            raise CliError("The file has changes that aren't committed. Commit them, or switch with --force to drop them.")
        ws.branch = name
        if head is None:
            self.out(f"On branch {name} (no versions yet).")
        elif ws.path.suffix.lower() == ".png":
            ws.synced[name] = self._load_into_file(head)
            self.out(f"On branch {name}. Loaded v{head['seq']} into {ws.file}; reload it in your paint app.")
        else:
            # A .psd or .kra holds layers Kitsune doesn't have, so the file is left alone.
            self.out(f"On branch {name} (latest v{head['seq']}). {ws.file} was left as it is: Kitsune only keeps the flattened "
                     f"image, so it can't rebuild your layers. `kitsune checkout v{head['seq']} -o v{head['seq']}.png` to see it.")
        ws.save()

    def checkout(self, ref: str, output: Path | None, force: bool = False) -> None:
        c = self.version(ref)
        if output:
            self.write_image(c, output)
            self.out(f"Wrote v{c['seq']} to {output}")
            return
        if self.ws.dirty() and not force:
            raise CliError("The file has changes that aren't committed. Commit them, use -o to write elsewhere, or --force.")
        self._load_into_file(c)
        self.out(f"Loaded v{c['seq']} into {self.ws.file}. Commit to continue from it on {self.ws.branch}.")

    def _load_into_file(self, c: dict) -> str:
        if self.ws.path.suffix.lower() != ".png":
            raise CliError("Loading versions into the file needs a PNG; use `kitsune checkout vN -o some.png`")
        return self.write_image(c, self.ws.path)

    def pick(self, label: str, from_ref: str) -> dict:
        ws = self.ws
        if ws.dirty():
            raise CliError("Commit your changes first: the region is brought into the latest version.")
        head, src = self.head(), self.version(from_ref)
        if head is None:
            raise CliError(f"Branch '{ws.branch}' has no versions yet")
        c = ok(self.api.post(f"/api/commits/{head['id']}/cherry-pick",
                             json={"source_commit": src["id"], "label": label}))
        ws.synced[ws.branch] = self._load_into_file(c) if ws.path.suffix.lower() == ".png" else ws.synced.get(ws.branch, "")
        ws.save()
        self.out(f"v{c['seq']}: {title(c)}")
        return c

    def merge(self, source: str, take: dict[str, str], abort_on_conflict: bool = True) -> dict | None:
        ws = self.ws
        if ws.dirty():
            raise CliError("Commit your changes before merging.")
        plan = ok(self.api.post(f"/api/repos/{ws.repo_id}/merges", json={"source": source, "target": ws.branch}))
        if plan["fast_forward"]:
            self.out(f"{ws.branch} hasn't moved since {source} branched off: fast-forward.")
        for ch in plan["auto"]:
            self.out(f"  auto: {ch['label']}")
        unresolved = [cf for cf in plan["conflicts"] if str(cf["index"]) not in take]
        if unresolved:
            self.out(f"{len(plan['conflicts'])} conflict(s). Both branches changed:")
            for cf in plan["conflicts"]:
                theirs = ", ".join(cf["target_labels"])
                self.out(f"  [{cf['index']}] {cf['label']} (on {ws.branch}: {theirs})")
            example = ",".join(f"{cf['index']}=source" for cf in plan["conflicts"])
            self.out(f"Choose a side for each and run again, e.g. kitsune merge {source} --take {example}")
            if abort_on_conflict:
                ok(self.api.post(f"/api/merges/{plan['id']}/abort"))
            return None
        c = ok(self.api.post(f"/api/merges/{plan['id']}/resolve", json={"choices": take}))
        if ws.path.suffix.lower() == ".png":
            ws.synced[ws.branch] = self._load_into_file(c)
            ws.save()
        self.out(f"v{c['seq']}: {title(c)}")
        return c

    def note(self, text: str, ref: str, client: bool) -> None:
        c = self.version(ref)
        ok(self.api.post(f"/api/commits/{c['id']}/notes", data={"kind": "client" if client else "artist", "text": text}))
        self.out(f"Note added to v{c['seq']}")

    def search(self, query: str) -> None:
        r = ok(self.api.get(f"/api/repos/{self.ws.repo_id}/search", params={"q": query}))
        if not r["results"]:
            self.out("No matches.")
        for hit in r["results"]:
            self.out(f"v{hit['seq']:<4} {hit['snippet']}  ({hit['reason']})")

    def watch(self, settle_s: float = 2.0, poll_s: float = 1.0, max_commits: int | None = None) -> None:
        """Commit each time the file is saved and then left alone for `settle_s` (paint apps write in bursts)."""
        ws = self.ws
        self.out(f"Watching {ws.file} on {ws.branch}. Save in your paint app to commit; Ctrl+C to stop.")
        made, last_mtime, changed_at = 0, None, None
        try:
            while max_commits is None or made < max_commits:
                mtime = ws.path.stat().st_mtime if ws.path.exists() else None
                if mtime != last_mtime:
                    last_mtime, changed_at = mtime, time.monotonic()
                elif changed_at and time.monotonic() - changed_at >= settle_s:
                    changed_at = None
                    if mtime is not None and ws.dirty() and self.commit(None, wait_s=0):
                        made += 1
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.out(f"\nStopped. {made} version(s) saved.")

    def open(self) -> str:
        url = f"{self.ws.web.rstrip('/')}/?repo={self.ws.repo_id}"
        webbrowser.open(url)
        self.out(url)
        return url


def parse_take(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    take = {}
    for part in raw.split(","):
        idx, _, side = part.partition("=")
        if side not in ("source", "target") or not idx.strip().isdigit():
            raise CliError(f"Bad --take '{part}'. Use index=source or index=target, e.g. 0=source,1=target")
        take[idx.strip()] = side
    return take


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kitsune", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    s = sub.add_parser("init", help="start tracking an image")
    s.add_argument("image", type=Path)
    s.add_argument("--name", help="piece name (default: the file name)")
    s.add_argument("--repo", type=int, help="link to an existing piece instead of creating one")
    s.add_argument("--backend", default=DEFAULT_BACKEND)
    s.add_argument("--web", default=DEFAULT_WEB, help="front-end URL for `kitsune open`")
    s.add_argument("-m", "--message")

    s = sub.add_parser("commit", help="save the current file as a new version")
    s.add_argument("-m", "--message")
    s.add_argument("--no-wait", action="store_true", help="don't wait for the auto message")
    s.add_argument("--allow-same", action="store_true", help="commit even if the file hasn't changed")

    sub.add_parser("status", help="has the file changed since the last version?")

    s = sub.add_parser("log", help="list versions")
    s.add_argument("--all", action="store_true", help="every branch, newest first")
    s.add_argument("-n", type=int, default=20)

    s = sub.add_parser("diff", help="what changed between two versions")
    s.add_argument("a", nargs="?")
    s.add_argument("b", nargs="?")

    s = sub.add_parser("branch", help="list branches, or create one")
    s.add_argument("name", nargs="?")
    s.add_argument("--from", dest="from_ref", help="version to branch from (default: this branch's latest)")

    s = sub.add_parser("switch", help="change branch and load its latest image")
    s.add_argument("name")
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("checkout", help="load an old version into the file")
    s.add_argument("version")
    s.add_argument("-o", "--output", type=Path)
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("pick", help="bring a region back from another version")
    s.add_argument("label", help="region name as `kitsune diff` shows it, e.g. sky")
    s.add_argument("--from", dest="from_ref", required=True)

    s = sub.add_parser("merge", help="merge a branch into the current one")
    s.add_argument("source")
    s.add_argument("--take", help="conflict choices, e.g. 0=source,1=target")

    s = sub.add_parser("note", help="attach a note to a version")
    s.add_argument("text")
    s.add_argument("--to", default="HEAD", help="version (default: HEAD)")
    s.add_argument("--client", action="store_true", help="it's client feedback")

    s = sub.add_parser("search", help="search the history")
    s.add_argument("query")

    s = sub.add_parser("watch", help="commit every time the file is saved")
    s.add_argument("--settle", type=float, default=2.0, help="seconds the file must be unchanged before committing")

    sub.add_parser("open", help="open this piece in the browser")
    return p


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model text on a Windows console
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "init":
            with httpx.Client(base_url=args.backend, timeout=120) as api:
                Kitsune.init(api, Path.cwd(), args.image, args.name, args.repo, args.backend, args.web, args.message)
            return 0
        ws = Workspace.find(Path.cwd())
        with httpx.Client(base_url=ws.backend, timeout=120) as api:
            k = Kitsune(api, ws)
            match args.cmd:
                case "commit":
                    k.commit(args.message, wait_s=0 if args.no_wait else 20, allow_same=args.allow_same)
                case "status":
                    k.status()
                case "log":
                    k.log(args.all, args.n)
                case "diff":
                    k.diff(args.a, args.b)
                case "branch":
                    k.branch(args.name, args.from_ref)
                case "switch":
                    k.switch(args.name, args.force)
                case "checkout":
                    k.checkout(args.version, args.output, args.force)
                case "pick":
                    k.pick(args.label, args.from_ref)
                case "merge":
                    k.merge(args.source, parse_take(args.take))
                case "note":
                    k.note(args.text, args.to, args.client)
                case "search":
                    k.search(args.query)
                case "watch":
                    k.watch(args.settle)
                case "open":
                    k.open()
        return 0
    except CliError as e:
        print(f"kitsune: {e}", file=sys.stderr)
        return 1
    except httpx.ConnectError:
        print("kitsune: can't reach the backend. Is it running? (check the backend URL in .kitsune/config.json)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
