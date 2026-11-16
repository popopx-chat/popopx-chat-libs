#!/usr/bin/env python3
"""Re-host upstream's published native libraries under the asset names this fork's SDKs request.

Nothing is built here. Every byte is the file simplex-chat/simplex-chat-libs published
for the same tag, and the only authority for what we publish is the digest our own SDKs
pin: the same value the SDK compares the downloaded asset against, so a file this job
accepts is exactly a file a consumer of these releases asks for.

Two gates, before any byte is uploaded:

1. upstream's release record must state a sha256 equal to our pin for that asset, and
2. the downloaded file's own sha256 must equal it too.

Either one failing stops the job. Run it again after scripts/ci/packages_release.py
moves a pin and the new version appears here; an asset already published with the
pinned digest is left alone.
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

    Keyed by the pair because core-7.1.0.14 and core-7.1.0.20 share five asset names
    with different digests, and the nodejs file pins both .zip and .node assets under
    different release tags.
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
    return run(["sha256sum", str(path)]).stdout.split()[0]


def api(path: str) -> dict:
    done = run(["gh", "api", path], check=False)
    return json.loads(done.stdout) if done.returncode == 0 else {}


def our_release(tag: str) -> dict:
    return api(f"repos/{OUR_REPO}/releases/tags/{tag}")


def upstream_release(tag: str) -> dict:
    return api(f"repos/{UPSTREAM}/releases/tags/{tag}")


def recorded_digest(asset: dict, digest: str) -> bool:
    """Whether GitHub's own release record already proves these are the pinned bytes."""
    return (asset.get("digest") or "").removeprefix("sha256:") == digest


def download(upstream_asset: str, tag: str, target: Path) -> None:
    url = f"https://github.com/{UPSTREAM}/releases/download/{tag}/{upstream_asset}"
    run(["curl", "--fail-with-body", "-sSL", "--retry", "5", "--retry-all-errors",
         "--retry-delay", "5", "--max-time", "900", "-o", str(target), url], capture=False)


def notes(tag: str, planned: list[tuple[str, int, str]]) -> str:
    platforms = ", ".join(sorted(re.sub(r"popopx-chat-(libs|nodejs)-", "", name).rsplit(".", 1)[0]
                                 for name, _, _ in planned))
    rows = "\n".join(f"| `{name}` | {size} | `{digest}` |" for name, size, digest in planned)
    return f"""POPOPX mirror of SimpleX Chat's prebuilt native libraries ({platforms}).

Nothing was built here. Each asset below is the byte-for-byte file `{UPSTREAM}` published
for the tag `{tag}`, re-hosted unmodified under the asset name this fork's SDKs request.
The libraries inside still carry upstream's own file names and symbols - `libsimplex.so`,
`libHSsimplexmq-*.so` - and the upstream tag and digest are what identifies them.

Publishing is gated on the digests this fork pins in
`packages/popopx-chat-nodejs/src/release.ts` and
`packages/popopx-chat-python/src/simplex_chat/_version.py`: `scripts/mirror_native_libs.py`
checks upstream's own recorded digest for each asset, then the sha256 of the file it
downloaded, and stops rather than publishing anything if either differs from the pin.

| asset | bytes | sha256 |
| --- | --- | --- |
{rows}

Licence: AGPL-3.0-only (`LICENSE`), the licence of the sources these binaries are built
from. Corresponding source: the release `{UPSTREAM}/{tag}` and this fork's AGPL source
tree at <https://github.com/{CHAT_REPO}>.
"""


def write_notes(tag: str, body: str, title: str) -> None:
    notes_file = OUT / f"{tag}-notes.md"
    notes_file.write_text(body)
    if our_release(tag):
        run(["gh", "release", "edit", tag, "--title", title, "--notes-file", str(notes_file)])
    else:
        branch = api(f"repos/{OUR_REPO}").get("default_branch", "master")
        run(["gh", "release", "create", tag, "--title", title, "--notes-file", str(notes_file),
             "--target", branch])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    want = pins()
    by_tag: dict[str, dict[str, str]] = {}
    for (tag, asset), digest in want.items():
        by_tag.setdefault(tag, {})[asset] = digest
    print(f"{len(want)} pinned asset(s) across {len(by_tag)} release tag(s), dry_run={DRY}", flush=True)

    plans: dict[str, list[tuple[str, int, str]]] = {}
    for tag in sorted(by_tag):
        source = upstream_release(tag)
        if not source:
            raise SystemExit(f"{UPSTREAM} has no release for {tag} - nothing to mirror")
        remote = {asset["name"]: asset for asset in source.get("assets", [])}
        for asset, digest in sorted(by_tag[tag].items()):
            upstream_asset = asset.replace("popopx-", "simplex-", 1)
            record = remote.get(upstream_asset)
            if not record:
                raise SystemExit(f"{UPSTREAM}/{tag} has no asset {upstream_asset}")
            if not recorded_digest(record, digest):
                raise SystemExit(f"REFUSED {tag}/{upstream_asset}: upstream recorded "
                                 f"{record.get('digest')} but our SDK pins {digest}")
            plans.setdefault(tag, []).append((asset, record["size"], digest))
        print(f"gate {tag}: {len(plans[tag])} asset(s) match the pins upstream-side", flush=True)
    if DRY:
        print("dry run: nothing downloaded, nothing published", flush=True)
        return 0

    for tag in sorted(plans):
        title = f"{tag} (mirror of {UPSTREAM})"
        # The release has to exist before an asset can be attached to it, and the notes
        # are already complete: the table is built from the pinned digests and upstream's
        # sizes, both verified above, not from what this loop happened to upload.
        write_notes(tag, notes(tag, plans[tag]), title)
        existing = our_release(tag)
        for asset, size, digest in plans[tag]:
            published = next((a for a in existing.get("assets", []) if a["name"] == asset), None)
            if published and recorded_digest(published, digest) and published["size"] == size:
                print(f"keep {tag}/{asset}", flush=True)
                continue
            print(f"fetch {tag}/{asset.replace('popopx-', 'simplex-', 1)} -> {asset}", flush=True)
            target = OUT / asset
            download(asset.replace("popopx-", "simplex-", 1), tag, target)
            got = sha256(target)
            if got != digest:
                raise SystemExit(f"REFUSED {tag}/{asset}: downloaded sha256 {got}, pin {digest}")
            if target.stat().st_size != size:
                raise SystemExit(f"REFUSED {tag}/{asset}: downloaded {target.stat().st_size} bytes, release says {size}")
            run(["gh", "release", "upload", tag, str(target), "--clobber"])
            target.unlink()
            print(f"published {tag}/{asset} ({size} bytes)", flush=True)
        write_notes(tag, notes(tag, plans[tag]), title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
