#!/usr/bin/env python3
"""Re-host upstream's published native libraries under the asset names this fork's SDKs request.

Nothing is built here. Every byte is the file simplex-chat/simplex-chat-libs published
for the same tag, and the only authority for what we publish is the digest our own
SDKs pin: a download whose sha256 does not equal that pin is deleted before it can
be uploaded, so the job cannot publish a byte no consumer of these releases asked
for. Run it again after scripts/ci/packages_release.py moves a pin and the new
version appears here.

The release notes are written from the same data, which is why they can state
provenance instead of implying the build happened in this repository.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

CHAT_REPO = "popopx-chat/popopx-chat"
CHAT_REF = os.environ.get("CHAT_REF", "master")
UPSTREAM = "simplex-chat/simplex-chat-libs"
PINS = {
    "nodejs": f"https://raw.githubusercontent.com/{CHAT_REPO}/{CHAT_REF}/packages/popopx-chat-nodejs/src/release.ts",
    "python": f"https://raw.githubusercontent.com/{CHAT_REPO}/{CHAT_REF}/packages/popopx-chat-python/src/simplex_chat/_version.py",
}
OUT = Path(os.environ.get("MIRROR_DIR", "/tmp/mirror"))
DRY = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
OUR_REPO = os.environ.get("GITHUB_REPOSITORY", "popopx-chat/popopx-chat-libs")


def run(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(args, capture_output=capture, text=True)
    if check and done.returncode != 0:
        raise SystemExit(f"command failed ({done.returncode}): {' '.join(args)}\n{done.stderr}")
    return done


def read(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode()


def pins() -> dict[tuple[str, str], str]:
    """(tag, asset) -> sha256, taken from the two SDKs that download these files.

    Keyed by the pair because core-7.1.0.14 and core-7.1.0.20 share five asset
    names with different digests, and the nodejs file pins both .zip and .node
    assets under different release tags.
    """
    want: dict[tuple[str, str], str] = {}
    node = read(PINS["nodejs"])
    body = node.split("export const SHA256", 1)[1].split("= {", 1)[1].split("}", 1)[0]
    addon_tag = re.search(r'ADDON_RELEASE[^"]*"([^"]+)"', node).group(1)
    libs_tag = re.search(r'LIBS_RELEASE = "([^"]+)"', node).group(1)
    for asset, digest in re.findall(r'"([^"]+)":\s*"([0-9a-f]{64})"', body):
        want[(addon_tag if asset.endswith(".node") else libs_tag, asset)] = digest

    python = read(PINS["python"])
    py_tag = re.search(r'LIBS_RELEASE = "([^"]+)"', python).group(1)
    py_body = python.split("LIBS_SHA256 = {", 1)[1].split("}", 1)[0]
    for asset, digest in re.findall(r'"([^"]+)":\s*"([0-9a-f]{64})"', py_body):
        key = (py_tag, asset)
        if want.get(key, digest) != digest:
            raise SystemExit(f"the two SDKs pin different digests for {key}")
        want[key] = digest
    if not want:
        raise SystemExit("no digests parsed - the pin files changed shape")
    return want


def sha256(path: Path) -> str:
    done = run(["sha256sum", str(path)])
    return done.stdout.split()[0]


def download(upstream_asset: str, tag: str, target: Path) -> None:
    url = f"https://github.com/{UPSTREAM}/releases/download/{tag}/{upstream_asset}"
    run(["curl", "--fail-with-body", "-sSL", "--retry", "5", "--retry-all-errors",
         "--retry-delay", "5", "--max-time", "900", "-o", str(target), url], capture=False)


def release(tag: str) -> dict:
    done = run(["gh", "api", f"repos/{OUR_REPO}/releases/tags/{tag}"], check=False)
    return json.loads(done.stdout) if done.returncode == 0 else {}


def digest_matches(record: dict, digest: str) -> bool:
    """Whether an asset we already publish is proven to be the pinned bytes by the
    digest GitHub recorded for it. Without that field the asset proves nothing, so
    it is fetched again rather than trusted."""
    return (record.get("digest") or "").removeprefix("sha256:") == digest


def notes(tag: str, published: list[tuple[str, int, str]]) -> str:
    platforms = ", ".join(sorted(name.split("popopx-chat-libs-")[1].split(".zip")[0]
                                 if "popopx-chat-libs-" in name else name.split("popopx-chat-nodejs-")[1].split(".node")[0]
                                 for name, _, _ in published))
    rows = "\n".join(f"| `{name}` | {size} | `{digest}` |" for name, size, digest in published)
    return f"""POPOPX mirror of SimpleX Chat's prebuilt native libraries ({platforms}).

Nothing was built here. Each asset below is the byte-for-byte file `{UPSTREAM}` published
for the tag `{tag}`, re-hosted unmodified under the asset name this fork's SDKs request.
The libraries inside still carry upstream's own file names and symbols - `libsimplex.so`,
`libHSsimplexmq-*.so` - and the upstream tag and digest are what identifies them.

Publishing is gated on the digests this fork pins in
`packages/popopx-chat-nodejs/src/release.ts` and
`packages/popopx-chat-python/src/simplex_chat/_version.py`: `scripts/mirror_native_libs.py`
downloads each asset, compares its sha256 with the pin, and deletes the file rather than
publishing it if they differ.

| asset | bytes | sha256 |
| --- | --- | --- |
{rows}

Licence: AGPL-3.0-only (`LICENSE`), the licence of the sources these binaries are built
from. Corresponding source: the release `{UPSTREAM}/{tag}` and this fork's AGPL source
tree at <https://github.com/{CHAT_REPO}>.
"""


def edit_release(tag: str, body: str, title: str) -> None:
    notes_file = OUT / "notes.md"
    notes_file.write_text(body)
    if release(tag):
        run(["gh", "release", "edit", tag, "--title", title, "--notes-file", str(notes_file)])
    else:
        run(["gh", "release", "create", tag, "--title", title, "--notes-file", str(notes_file), "--target", "master"])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = pins()
    by_tag: dict[str, dict[str, str]] = {}
    for (tag, asset), digest in want.items():
        by_tag.setdefault(tag, {})[asset] = digest
    print(f"{len(want)} pinned asset(s) across {len(by_tag)} release tag(s), dry_run={DRY}", flush=True)

    for tag in sorted(by_tag):
        existing = {} if DRY else release(tag)
        published: list[tuple[str, int, str]] = []
        for asset, digest in sorted(by_tag[tag].items()):
            target = OUT / asset
            record = next((a for a in existing.get("assets", []) if a["name"] == asset), None)
            if record and digest_matches(record, digest):
                published.append((asset, record["size"], digest))
                print(f"keep {asset}: GitHub recorded the pinned digest", flush=True)
                continue
            upstream_asset = asset.replace("popopx-", "simplex-", 1)
            print(f"fetch {tag}/{upstream_asset} -> {asset}", flush=True)
            download(upstream_asset, tag, target)
            got = sha256(target)
            if got != digest:
                target.unlink()
                raise SystemExit(f"REFUSED {asset}: sha256 {got} does not match the pin {digest}")
            size = target.stat().st_size
            published.append((asset, size, digest))
            if not DRY:
                run(["gh", "release", "upload", tag, str(target), "--clobber"])
        title = f"{tag} (mirror of {UPSTREAM})"
        print(f"--- {tag}: {len(published)} asset(s)", flush=True)
        if not DRY:
            edit_release(tag, notes(tag, published), title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
