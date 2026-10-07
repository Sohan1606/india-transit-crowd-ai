#!/usr/bin/env python3
"""Materialize Git LFS objects for this repository without a git-lfs binary.

The two large synthetic Mumbai CSVs are stored through Git LFS on the feature branch. A sandbox or CI
runner that has no ``git-lfs`` installed would otherwise be left holding 130-byte pointer files, and
nothing downstream (audit, gate, training) could read a pointer as a dataset. This tool speaks the LFS
Batch API over HTTPS, downloads the object, and **verifies the SHA-256 against the pointer** before
replacing it - so a truncated or wrong object can never be mistaken for the dataset.

    python3 scripts/fetch_lfs_object.py --path data/development/synthetic/<file>.csv
    python3 scripts/fetch_lfs_object.py --all      # every pointer under the tree
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repo_slug() -> str:
    url = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    if not url:
        raise SystemExit("remote.origin.url is not configured; add it first:\n"
                         "  git remote add origin https://github.com/<owner>/<repo>.git")
    for marker in ("github.com/", "github.com:"):
        if marker in url:
            return url.split(marker, 1)[1].removesuffix(".git")
    raise SystemExit(f"unsupported remote URL (only github.com is handled here): {url}")


def parse_pointer(path: Path) -> tuple[str, int] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("version https://git-lfs"):
        return None
    oid = size = None
    for line in text.splitlines():
        if line.startswith("oid sha256:"):
            oid = line.split(":", 1)[1].strip()
        elif line.startswith("size "):
            size = int(line.split(" ", 1)[1].strip())
    return (oid, size) if oid and size else None


def pointers_in(tree: Path) -> list[Path]:
    return [candidate for candidate in sorted(tree.rglob("*"))
            if candidate.is_file() and parse_pointer(candidate)]


def request(url: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    return urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers or {}), timeout=120)


def download_targets(slug: str, objects: list[dict], action: str = "download"):
    body = json.dumps({"operation": action, "transfers": ["basic", "multipart"], "objects": objects,
                       "hash_algo": "sha_256"}).encode()
    headers = {"Accept": "application/vnd.git-lfs+json", "Content-Type": "application/vnd.git-lfs+json"}
    with request(f"https://github.com/{slug}.git/info/lfs/objects/batch", body, headers) as response:
        return json.load(response)


def fetch_one(slug: str, oid: str, size: int, destination: Path) -> None:
    payload = download_targets(slug, [{"oid": oid, "size": size}])
    actions = payload.get("actions") or {}
    links = (payload.get("objects") or [{}])[0].get("actions") or actions
    link = links.get("download") or actions.get("download")
    if not link or not link.get("href"):
        raise SystemExit(f"LFS batch returned no download action for {oid[:12]}: "
                         f"{json.dumps(payload)[:400]}")
    headers = dict(link.get("header") or {})
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    with request(link["href"], None, headers) as response, temporary.open("wb") as handle:
        total = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            total += len(chunk)
            if total % (16 << 20) < (1 << 20):
                print(f"  {oid[:8]}… {total / 1_048_576:.0f} / {size / 1_048_576:.0f} MB", flush=True)
    if total != size:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"truncated download: got {total} bytes, pointer says {size}")
    actual = digest.hexdigest()
    if actual != oid:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch: sha256 {actual} != pointer oid {oid}")
    shutil.move(temporary, destination)
    print(f"OK {destination.relative_to(ROOT)}  {size:,} bytes  sha256 {actual[:16]}… verified against pointer")

    # A materialised source must never be staged by an indiscriminate `git add -A`: the pointer belongs in git,
    # the bytes belong on the machine that fetched them. Without this, committing after a fetch quietly puts a
    # 149 MB non-redistributable file into history and into any package built from the tree.
    subprocess.run(["git", "update-index", "--skip-worktree", str(destination.relative_to(ROOT))],
                   cwd=ROOT, check=False, capture_output=True)
    print(f"[git] {destination.name}: marked skip-worktree, so the committed entry stays a pointer "
          f"(undo with git update-index --no-skip-worktree <path>)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", action="append", default=[], help="pointer file to materialize (repeatable)")
    parser.add_argument("--all", action="store_true", help="materialize every LFS pointer in the tree")
    parser.add_argument("--under", default="data", help="directory to scan with --all (default: data)")
    parser.add_argument("--check", action="store_true", help="report pointer state without downloading")
    args = parser.parse_args()

    if args.all:
        targets = pointers_in(ROOT / args.under)
    else:
        targets = [Path(p) if Path(p).is_absolute() else ROOT / p for p in args.path]
    if not targets:
        print("no LFS pointer files found under", args.under)
        return
    slug = repo_slug()
    for target in targets:
        pointer = parse_pointer(target) if target.exists() else None
        if args.check:
            print(f"{target.relative_to(ROOT)}: " + ("pointer, not materialized" if pointer else "real content"
                                                      if target.exists() else "missing"))
            continue
        if pointer is None:
            if target.exists():
                print(f"{target.relative_to(ROOT)}: already materialized ({target.stat().st_size:,} bytes)")
                continue
            raise SystemExit(f"{target} does not exist and is not a pointer; run a git fetch first")
        oid, size = pointer
        print(f"fetching {target.relative_to(ROOT)} ({size:,} bytes) via the LFS batch API …", flush=True)
        fetch_one(slug, oid, size, target)


if __name__ == "__main__":
    main()
