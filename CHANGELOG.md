# Changelog

All notable changes to lightcrawl are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); dates are
ISO 8601.

## [Unreleased] — v0.3 (in progress)

v0.3 upgrades lightcrawl from "enhanced WebFetch" to "local firecrawl"
with map / crawl / cache as the headline features. See `v0.3-design.md`
for the full plan. This entry is updated PR-by-PR.

### Breaking changes

- **`remove_base64_images` default flipped from `False` to `True`.**
  Affects `FetchRequest.remove_base64_images`, the
  `html_to_markdown(remove_base64_images=...)` function-level default,
  and the `lightcrawl fetch` CLI subcommand (which now honors the new
  dataclass default when the flag is absent — see Fixed below).
  v0.2 stripped every `<img>` by default for byte-identical v0.1 output;
  v0.3 strips only `data:` URI images, letting external `<img>` tags
  flow into markdown. To restore v0.2 behavior, pass
  `remove_base64_images=False` programmatically or use the new
  `--no-remove-base64-images` CLI flag.

### Fixed

- CLI now honors the new `remove_base64_images=True` default. The v0.3
  PR 1 initial commit (`bcf0ec2`) flipped the `FetchRequest` dataclass
  default but `cli.py` was still passing `args.remove_base64_images`
  (an argparse `store_true` False on absence) straight through,
  silently overriding the new default. The `--remove-base64-images`
  flag now uses `argparse.BooleanOptionalAction`; absence means
  "fall through to dataclass default", explicit `--remove-base64-images`
  forces True, and the auto-generated `--no-remove-base64-images`
  forces False.

### Added

- `src/lightcrawl/canonical.py` — pure-function URL canonicalization and
  `url_hash(canonical_url, profile=...)` used as the single source of
  truth for cache keys and crawl dedup. The `profile` dimension is a
  security boundary: an authed fetch of a URL with `profile=twitter`
  produces a different hash than an unauthed fetch of the same URL,
  preventing cross-profile cache replay.

## [0.2.0] — 2026-05-18

See `git log v0.2.0` and PR #16–#21 for the full v0.2 changeset.

## [0.1.0]

Initial public CLI + skill release.
