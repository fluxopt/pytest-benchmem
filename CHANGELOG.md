# Changelog

## [0.4.8](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.7...v0.4.8) (2026-07-01)


### Bug Fixes

* scaling overlays multiple runs + CLI axis/series controls ([#150](https://github.com/fluxopt/pytest-benchmem/issues/150)) ([#151](https://github.com/fluxopt/pytest-benchmem/issues/151)) ([ab0140e](https://github.com/fluxopt/pytest-benchmem/commit/ab0140e9523bbedd6c9060a1a31e1919d9ae404c))

## [0.4.7](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.6...v0.4.7) (2026-06-29)


### Features

* **plot:** clearer titles, axis labels, unit notes, and colorbars ([#148](https://github.com/fluxopt/pytest-benchmem/issues/148)) ([9a7b66e](https://github.com/fluxopt/pytest-benchmem/commit/9a7b66e28e23183eca176280eb1929a15855c7c9))

## [0.4.6](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.5...v0.4.6) (2026-06-29)


### Features

* plot -o exports a static image when the suffix is png/svg/pdf/... ([#145](https://github.com/fluxopt/pytest-benchmem/issues/145)) ([#146](https://github.com/fluxopt/pytest-benchmem/issues/146)) ([ab2ab2c](https://github.com/fluxopt/pytest-benchmem/commit/ab2ab2c06193d68a90413acf28fcfff6c0e1d76e))


### Bug Fixes

* keep the baseline frame in the animated scatter (drop only when static) ([#142](https://github.com/fluxopt/pytest-benchmem/issues/142)) ([e600841](https://github.com/fluxopt/pytest-benchmem/commit/e600841b3cb3561c98e9a74dc36bf569bbe97ca0))

## [0.4.5](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.4...v0.4.5) (2026-06-29)


### Bug Fixes

* plot --view scatter drew the baseline series as redundant ratio-1.0 points ([#140](https://github.com/fluxopt/pytest-benchmem/issues/140)) ([aa24710](https://github.com/fluxopt/pytest-benchmem/commit/aa24710e54bb1d1bc290ee34558b57a18d61fb8f)), closes [#139](https://github.com/fluxopt/pytest-benchmem/issues/139)

## [0.4.4](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.3...v0.4.4) (2026-06-29)


### Features

* `--pivot` comparison axis for compare/plot (fold one run along a config dim) ([#137](https://github.com/fluxopt/pytest-benchmem/issues/137)) ([d0672f7](https://github.com/fluxopt/pytest-benchmem/commit/d0672f74d7040b4f777df342c346052fc9f77678))

## [0.4.3](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.2...v0.4.3) (2026-06-29)


### Features

* benchmem compare accepts a single run (plain table) ([#123](https://github.com/fluxopt/pytest-benchmem/issues/123)) ([96275d9](https://github.com/fluxopt/pytest-benchmem/commit/96275d93628323ffd4f3cc74decdebdcb132004e))

## [0.4.2](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.1...v0.4.2) (2026-06-18)


### Bug Fixes

* **docs:** pin mkdocs-typer2 &gt;=0.4.1 and drop NO_COLOR workaround ([#120](https://github.com/fluxopt/pytest-benchmem/issues/120)) ([db1453f](https://github.com/fluxopt/pytest-benchmem/commit/db1453f8a557b221563e83e8223f3f754c70bdb7))

## [0.4.1](https://github.com/fluxopt/pytest-benchmem/compare/v0.4.0...v0.4.1) (2026-06-17)


### Features

* `benchmem flamegraph` — one-step render of a kept profile (closes [#114](https://github.com/fluxopt/pytest-benchmem/issues/114)) ([#118](https://github.com/fluxopt/pytest-benchmem/issues/118)) ([95d2f8d](https://github.com/fluxopt/pytest-benchmem/commit/95d2f8d127bbc64b43423a3555893f1fd61c8a01))
* isolated RSS metric — opt-in whole-process peak memory (Phase 1 of [#109](https://github.com/fluxopt/pytest-benchmem/issues/109)) ([#110](https://github.com/fluxopt/pytest-benchmem/issues/110)) ([782fec9](https://github.com/fluxopt/pytest-benchmem/commit/782fec9f853c914ea9d11a09a7aa67b48437c73a))
* native-trace capture for the kept memory profile (closes [#113](https://github.com/fluxopt/pytest-benchmem/issues/113)) ([#117](https://github.com/fluxopt/pytest-benchmem/issues/117)) ([9ff5f2a](https://github.com/fluxopt/pytest-benchmem/commit/9ff5f2ad6e001d8cb907f8d153842eb0a02218ab))
* reuse pedantic `setup` for memory samples — stateful benchmarks stay accurate (closes [#105](https://github.com/fluxopt/pytest-benchmem/issues/105)) ([#106](https://github.com/fluxopt/pytest-benchmem/issues/106)) ([d1de57a](https://github.com/fluxopt/pytest-benchmem/commit/d1de57a9b33ff7a43e2060b6f5f3288ccff5a0c8))
* rss isolate is marker-only opt-in; warn on heavy pickled actions ([#115](https://github.com/fluxopt/pytest-benchmem/issues/115)) ([fc2e4cf](https://github.com/fluxopt/pytest-benchmem/commit/fc2e4cfbe377e6f1d519f8c13642d60ba607a221))
* warmup pass + measure memory before timing (cold floor) ([#108](https://github.com/fluxopt/pytest-benchmem/issues/108)) ([95c021b](https://github.com/fluxopt/pytest-benchmem/commit/95c021b50755d8a88b0a606eee0a6005b7d9c72a))

## [0.4.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.3.0...v0.4.0) (2026-06-16)


### ⚠ BREAKING CHANGES

* benchmem plot --metric is removed; use --columns (e.g. 'plot run.json --columns peak'). Mirrors the compare --metric -> --columns rename.

### Features

* plot selects the metric via --columns (parity with compare) + 0.3.0 README refresh ([#102](https://github.com/fluxopt/pytest-benchmem/issues/102)) ([85443dd](https://github.com/fluxopt/pytest-benchmem/commit/85443dd57548e0801e5d33555bc6e3c6c62d41f3))
* timed|untimed divider in compare; CLI-showcase README + Python 3.14 ([#104](https://github.com/fluxopt/pytest-benchmem/issues/104)) ([411987f](https://github.com/fluxopt/pytest-benchmem/commit/411987f32f6e1a54e53cc9a56f675f8182bb6ba6))

## [0.3.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.2.1...v0.3.0) (2026-06-16)

This release reshapes how a memory measurement is taken, stored, and reported. Each
`benchmark_memory` run now **samples adaptively** and keeps its **full per-repeat series**
instead of a single number — so you can ask how noisy a metric is (`--stat
min|mean|max|median|stddev`) — and the terminal prints **one combined timing + memory
table**. `benchmem compare` is **rebuilt on pytest-benchmark's table model** (rows per
benchmark × run, a metric × stat column grid, relative `(×)` multipliers, `--group-by` /
`--columns`). Plus a `benchmem sweep` CLI for cross-version runs, `--where` / `--free-axes`
plot controls, action-scoped memory ceilings (`@pytest.mark.benchmem(max_peak=...)`), and
`--benchmark-memory-profile` to keep a memray `.bin` for regressions.

Consolidating the metric surface around the per-repeat series retired a few redundant
knobs — see the migration notes below.

### ⚠ BREAKING CHANGES

Pre-1.0 changes vs 0.2.1, each quick to migrate:

* **Saved memory JSON from 0.2.x no longer loads.** The blob under
  `extra_info["benchmem"]` is now three flat per-repeat arrays (`peak_bytes` /
  `allocations` / `total_bytes`), with the headline derived on read; the old denormalized
  shape is not parsed. **Migrate:** re-run the suite with `--benchmark-memory` to
  regenerate the runs. Timing-only pytest-benchmark files are unaffected. ([#75](https://github.com/fluxopt/pytest-benchmem/issues/75))
* **The `peak_max` metric is removed** — it was `peak` reduced by max (a stat of a stat), so
  it couldn't itself take a `--stat`. **Migrate:** `--columns peak --stat max`. ([#75](https://github.com/fluxopt/pytest-benchmem/issues/75))
* **The `memory` alias for `peak` is removed** — it read like a category, not a synonym.
  **Migrate:** `--columns peak`. ([#75](https://github.com/fluxopt/pytest-benchmem/issues/75))
* **The `gross` metric and the per-blob `mode` tag are removed** — both were leftovers of the
  reverted RSS engine (`gross` had no producer and always errored; `mode` was a constant).
  Reading a legacy blob ignores a stray `mode` key, so **no migration is needed**. ([#67](https://github.com/fluxopt/pytest-benchmem/issues/67))
* **`benchmem compare` selects metrics with `--columns`, not `--metric`.** The table is now a
  metric × stat grid, so a comma list of metrics (`--columns`) paired with `--stat` replaces the
  single `--metric`. **Migrate:** `--metric peak` → `--columns peak`. ([#98](https://github.com/fluxopt/pytest-benchmem/issues/98), [#101](https://github.com/fluxopt/pytest-benchmem/issues/101))

### Features

**Memory measurement**
* **Adaptive sampling** — passes run until the peak floor settles instead of a fixed count; `--benchmark-memory-repeats` still forces a fixed count for reproducible gating. ([#97](https://github.com/fluxopt/pytest-benchmem/issues/97), [#79](https://github.com/fluxopt/pytest-benchmem/issues/79))
* **Per-repeat series** with `--stat` distributions, min/mean/max spread columns, and `--benchmark-memory-columns` / `-stats` selection. ([#72](https://github.com/fluxopt/pytest-benchmem/issues/72), [#76](https://github.com/fluxopt/pytest-benchmem/issues/76))
* **Action-scoped absolute ceilings** via `@pytest.mark.benchmem(max_peak=…, max_allocated=…, max_allocations=…)`. ([#86](https://github.com/fluxopt/pytest-benchmem/issues/86))
* **`--benchmark-memory-profile DIR`** keeps the memray `.bin` for regressions (or every measured benchmark), to render with `memray flamegraph`. ([#100](https://github.com/fluxopt/pytest-benchmem/issues/100), closes [#24](https://github.com/fluxopt/pytest-benchmem/issues/24))
* Actionable error when a memray `Tracker` is already active (e.g. pytest-memray on the same test). ([#89](https://github.com/fluxopt/pytest-benchmem/issues/89))

**Tables & compare**
* **One combined timing + memory table** by default. ([#65](https://github.com/fluxopt/pytest-benchmem/issues/65), [#68](https://github.com/fluxopt/pytest-benchmem/issues/68))
* **`benchmem compare` rebuilt on pytest-benchmark's table model** — rows per (benchmark × run), a metric × stat column grid with `--columns` / `--group-by` / `--metric both`, relative `(×)` multipliers, plus `--csv` / `--sort`. ([#98](https://github.com/fluxopt/pytest-benchmem/issues/98), [#101](https://github.com/fluxopt/pytest-benchmem/issues/101), [#74](https://github.com/fluxopt/pytest-benchmem/issues/74))

**Plotting**
* **`--where KEY=VALUE`** row filter, **`--free-axes x|y|both`** for faceted views, and min…max spread whiskers on scaling plots. ([#93](https://github.com/fluxopt/pytest-benchmem/issues/93), [#95](https://github.com/fluxopt/pytest-benchmem/issues/95), [#99](https://github.com/fluxopt/pytest-benchmem/issues/99))

**CLI**
* **`benchmem sweep`** — cross-version sweeps without a harness. ([#87](https://github.com/fluxopt/pytest-benchmem/issues/87))
* Caller-labelled snapshots, decoupling series names from filenames. ([#57](https://github.com/fluxopt/pytest-benchmem/issues/57))

### Bug Fixes

* `compare` no longer crashes when two runs share a file stem. ([#64](https://github.com/fluxopt/pytest-benchmem/issues/64))

## [0.2.1](https://github.com/fluxopt/pytest-benchmem/compare/v0.2.0...v0.2.1) (2026-06-13)


### Features

* add `rss` memory mode — kernel resident high-water via a forked child ([#51](https://github.com/fluxopt/pytest-benchmem/issues/51)) ([c4ccd12](https://github.com/fluxopt/pytest-benchmem/commit/c4ccd1267b9b795d88f377e005b6b6f060ccc40a))
* add peak_max and gross metrics; error on metric/mode mismatch ([#55](https://github.com/fluxopt/pytest-benchmem/issues/55)) ([df45d1f](https://github.com/fluxopt/pytest-benchmem/commit/df45d1fc44ece79db297ae5b0dbc1537f5cb3e8f))
* built-in node.* dims (module/func/class/group), selectable in plots ([#54](https://github.com/fluxopt/pytest-benchmem/issues/54)) ([937ca0f](https://github.com/fluxopt/pytest-benchmem/commit/937ca0f470d467046d81d1db549a51cfa44dfdd0))
* tag memory blobs with a `mode` and refuse to mix modes ([#40](https://github.com/fluxopt/pytest-benchmem/issues/40)) ([4251e16](https://github.com/fluxopt/pytest-benchmem/commit/4251e16a79d4ec66d5b39a41c924633c256287ee))


### Bug Fixes

* accept str and single-path snapshots in plot_* and load_long_df ([#52](https://github.com/fluxopt/pytest-benchmem/issues/52)) ([fdbc343](https://github.com/fluxopt/pytest-benchmem/commit/fdbc3432c8709ba0c3ed2f4c85df6ff4f45a4a30))
* keep only scalar dims, dropping unserializable and structured values ([#45](https://github.com/fluxopt/pytest-benchmem/issues/45)) ([71cb05d](https://github.com/fluxopt/pytest-benchmem/commit/71cb05d464d66bb55699e582103261f335a3e1a3))
* metric ergonomics — correct allocated label, accept memory alias ([#53](https://github.com/fluxopt/pytest-benchmem/issues/53)) ([a61c9be](https://github.com/fluxopt/pytest-benchmem/commit/a61c9befb6aae6feca5f504f9fb9e16b35ed5f3f))


### Reverts

* remove the `rss` memory mode ([#51](https://github.com/fluxopt/pytest-benchmem/issues/51)) ([#56](https://github.com/fluxopt/pytest-benchmem/issues/56)) ([99d908d](https://github.com/fluxopt/pytest-benchmem/commit/99d908d582094d982f421cc381639f53b6585a56))

## [0.2.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.1.0...v0.2.0) (2026-06-13)


### ⚠ BREAKING CHANGES

* mirror memray's metrics — add total memory allocated ([#39](https://github.com/fluxopt/pytest-benchmem/issues/39))
* memory regression gate, @pytest.mark.benchmem, bytes blob migration ([#32](https://github.com/fluxopt/pytest-benchmem/issues/32))

### Features

* empirical scaling fit — report O(n^x) over a size sweep ([#36](https://github.com/fluxopt/pytest-benchmem/issues/36)) ([4bc6e46](https://github.com/fluxopt/pytest-benchmem/commit/4bc6e4683142c46c9c60765dbf1f8e39adb3388f))
* memory regression gate, [@pytest](https://github.com/pytest).mark.benchmem, bytes blob migration ([#32](https://github.com/fluxopt/pytest-benchmem/issues/32)) ([654c582](https://github.com/fluxopt/pytest-benchmem/commit/654c582a15a8f8ef8e79a7c1d41767660d5f962a))
* mirror memray's metrics — add total memory allocated ([#39](https://github.com/fluxopt/pytest-benchmem/issues/39)) ([0b6fad6](https://github.com/fluxopt/pytest-benchmem/commit/0b6fad6f90ef124b1c80ca368c1d4db6fe5b34af))


### Bug Fixes

* correct release-please pre-major key so feat! bumps 0.2.0 not 1.0.0 ([#41](https://github.com/fluxopt/pytest-benchmem/issues/41)) ([fac21e0](https://github.com/fluxopt/pytest-benchmem/commit/fac21e08bfaf5816f067fd78da57aa623c1b563d))

## [0.1.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.1.0...v0.1.0) (2026-06-13)


### ⚠ BREAKING CHANGES

* rename package peakbench → pytest-benchmem ([#10](https://github.com/fluxopt/pytest-benchmem/issues/10))
* pivot to the memory companion to pytest-benchmark ([#7](https://github.com/fluxopt/pytest-benchmem/issues/7))

### Features

* --benchmark-memory flag to augment existing benchmark() calls ([#16](https://github.com/fluxopt/pytest-benchmem/issues/16)) ([aff17c7](https://github.com/fluxopt/pytest-benchmem/commit/aff17c76ad742cedc963e7914bd575846ddc6035))
* pivot to the memory companion to pytest-benchmark ([#7](https://github.com/fluxopt/pytest-benchmem/issues/7)) ([52f2b6b](https://github.com/fluxopt/pytest-benchmem/commit/52f2b6b56af1ee61f84fcd0ab9dc0947004fd31d))
* resolve [#2](https://github.com/fluxopt/pytest-benchmem/issues/2) — drop select=, bless filter-before-convert ([89fbfcd](https://github.com/fluxopt/pytest-benchmem/commit/89fbfcdde439eb6f1535df8e65d2295b2ea69add))


### Miscellaneous Chores

* release pytest-benchmem as 0.1.0 ([#13](https://github.com/fluxopt/pytest-benchmem/issues/13)) ([8e51760](https://github.com/fluxopt/pytest-benchmem/commit/8e51760d7bdfe4e44ea77856e8a0c4e158de0099))


### Code Refactoring

* rename package peakbench → pytest-benchmem ([#10](https://github.com/fluxopt/pytest-benchmem/issues/10)) ([1e48259](https://github.com/fluxopt/pytest-benchmem/commit/1e482590bef2767df1619bcae15a6d132f4cc610))

## [0.1.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.0.1...v0.1.0) (2026-06-13)


### ⚠ BREAKING CHANGES

* rename package peakbench → pytest-benchmem ([#10](https://github.com/fluxopt/pytest-benchmem/issues/10))
* pivot to the memory companion to pytest-benchmark ([#7](https://github.com/fluxopt/pytest-benchmem/issues/7))

### Features

* pivot to the memory companion to pytest-benchmark ([#7](https://github.com/fluxopt/pytest-benchmem/issues/7)) ([52f2b6b](https://github.com/fluxopt/pytest-benchmem/commit/52f2b6b56af1ee61f84fcd0ab9dc0947004fd31d))


### Miscellaneous Chores

* release pytest-benchmem as 0.1.0 ([#13](https://github.com/fluxopt/pytest-benchmem/issues/13)) ([8e51760](https://github.com/fluxopt/pytest-benchmem/commit/8e51760d7bdfe4e44ea77856e8a0c4e158de0099))


### Code Refactoring

* rename package peakbench → pytest-benchmem ([#10](https://github.com/fluxopt/pytest-benchmem/issues/10)) ([1e48259](https://github.com/fluxopt/pytest-benchmem/commit/1e482590bef2767df1619bcae15a6d132f4cc610))

## 0.0.1 (2026-06-13)


### Features

* resolve [#2](https://github.com/fluxopt/pytest-benchmem/issues/2) — drop select=, bless filter-before-convert ([89fbfcd](https://github.com/fluxopt/pytest-benchmem/commit/89fbfcdde439eb6f1535df8e65d2295b2ea69add))
