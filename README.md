# POPOPX library builds

This repository is used for downloads by POPOPX Chat's SDK libraries:

- [POPOPX Chat Node.js library](https://github.com/popopx-chat/popopx-chat/tree/master/packages/popopx-chat-nodejs)
  fetches `popopx-chat-libs-<platform>.zip` from the tag `core-<version>`, and
  `popopx-chat-nodejs-<platform>.node` from the tag `nodejs-addon-<commit>`.
- [POPOPX Chat Python library](https://github.com/popopx-chat/popopx-chat/tree/master/packages/popopx-chat-python)
  fetches `popopx-chat-libs-<platform>.zip` from the tag `core-<version>`.

Each SDK downloads one asset per platform (`linux-x86_64`, `linux-aarch64`, `macos-x86_64`,
`macos-aarch64`, `windows-x86_64`) and refuses the file unless its SHA-256 equals the digest pinned in
this fork's source tree: `packages/popopx-chat-nodejs/src/release.ts` and
`packages/popopx-chat-python/src/simplex_chat/_version.py`. Those pins are written by
`scripts/ci/packages_release.py`, never by hand.

## What the releases are

A release whose assets were not built here says so in its body and names the upstream tag and the digest it was
checked against: the bytes are SimpleX Chat Ltd's published build, mirrored **unmodified** and re-hosted under
the asset name this fork's SDKs request. Hosting them here is a distribution decision for this fork, not a claim
of authorship - the libraries inside still carry upstream's own file names and symbols. As of 2026-11-16 every
release in this repository is such a mirror; a fork-built release will state that instead.

Licence: AGPL-3.0-only (`LICENSE`), the licence of the sources these binaries are built from. Corresponding
source: upstream's `simplex-chat` and `simplexmq` releases for the version in the tag, and this fork's AGPL
source tree at <https://github.com/popopx-chat/popopx-chat>.

## releases.toml

`releases.toml` is a ledger that `scripts/ci/packages_release.py` reads and writes through the GitHub API:

- `[core.<branch>]` maps each released core version to the commit it was released from.
- `[npm.<name>]` and `[pypi.<name>]` do the same for each published package version.

The section names are **generated** by that script from the packages' own `name` fields (`npm_key()` reads
`package.json`, `pypi_key()` reads `pyproject.toml`), so a section name is a value shared between this file and
the release tooling. Respelling a section here renames nothing: it makes the tooling read no history for that
package, and it then treats already-published versions as unpublished. They keep upstream's spelling for as long
as this fork publishes packages under those names, and recorded rows are never rewritten - a recorded version
keeps the commit it was first released from.

`core-release` is a marker inherited from the imported history. Nothing in this fork reads it; the same fact is
the `7.1.0.11` row of `[core.master]` above.
