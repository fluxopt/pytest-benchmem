# Changelog

## [0.3.0](https://github.com/fluxopt/pytest-benchmem/compare/v0.2.1...v0.3.0) (2026-06-16)


### ⚠ BREAKING CHANGES

* store memory as per-repeat series; drop peak_max and the memory alias ([#75](https://github.com/fluxopt/pytest-benchmem/issues/75))
* drop the gross metric and the now-obsolete mode tag ([#67](https://github.com/fluxopt/pytest-benchmem/issues/67))

### Features

* `--benchmark-memory-profile` — keep the memray .bin for regressions (closes [#24](https://github.com/fluxopt/pytest-benchmem/issues/24)) ([#100](https://github.com/fluxopt/pytest-benchmem/issues/100)) ([85fb0fd](https://github.com/fluxopt/pytest-benchmem/commit/85fb0fd4b4ee608f3c2a13ed67592dc0dd06cb74))
* `--free-axes` to unmatch faceted plot axes (x|y|both) ([#95](https://github.com/fluxopt/pytest-benchmem/issues/95)) ([2570988](https://github.com/fluxopt/pytest-benchmem/commit/257098866c344df7278af83a4fc51336e9a1b61d))
* `--where` row filter for plots (KEY=VALUE, repeatable) ([#93](https://github.com/fluxopt/pytest-benchmem/issues/93)) ([4a1220b](https://github.com/fluxopt/pytest-benchmem/commit/4a1220bb072da9cb9f030aeef25215345879e606))
* `benchmem sweep` CLI — cross-version sweeps without a harness ([#87](https://github.com/fluxopt/pytest-benchmem/issues/87)) ([8230ddb](https://github.com/fluxopt/pytest-benchmem/commit/8230ddb40504e24fa2b84af6e54af0af7a75987d))
* action-scoped absolute memory ceilings via [@pytest](https://github.com/pytest).mark.benchmem(max_*) ([#86](https://github.com/fluxopt/pytest-benchmem/issues/86)) ([9afac1f](https://github.com/fluxopt/pytest-benchmem/commit/9afac1fb171aefd2fdfff746c071714c6ecb7906))
* actionable error when memray's Tracker is already active ([#89](https://github.com/fluxopt/pytest-benchmem/issues/89)) ([bdd24e9](https://github.com/fluxopt/pytest-benchmem/commit/bdd24e9add0da00428371a3669e8348a2ae5f338))
* adaptive memory sampling instead of a fixed repeat count ([#97](https://github.com/fluxopt/pytest-benchmem/issues/97)) ([1e79ef1](https://github.com/fluxopt/pytest-benchmem/commit/1e79ef180bc83ca85c9dac9467172fbe1e15cda8))
* benchmem compare --csv and --sort ([#74](https://github.com/fluxopt/pytest-benchmem/issues/74)) ([5da39dc](https://github.com/fluxopt/pytest-benchmem/commit/5da39dc1a95c28ff31e566fa0f1509adfb857e82))
* bring compare and sweeps onto the combined-table guidelines ([#68](https://github.com/fluxopt/pytest-benchmem/issues/68)) ([0caf794](https://github.com/fluxopt/pytest-benchmem/commit/0caf7949caa30eeaf956359dd615fd4b23136848))
* capture per-repeat memory series and report distributions via --stat ([#72](https://github.com/fluxopt/pytest-benchmem/issues/72)) ([36f8856](https://github.com/fluxopt/pytest-benchmem/commit/36f8856ed6c505cc2d97ccc3802b25990175c192))
* let callers label snapshots, decoupling series names from filenames ([#57](https://github.com/fluxopt/pytest-benchmem/issues/57)) ([10228e1](https://github.com/fluxopt/pytest-benchmem/commit/10228e11d180105856d6e58ad05d4b964e0ab2cc))
* one table for timing + memory (combined by default) ([#65](https://github.com/fluxopt/pytest-benchmem/issues/65)) ([2f6e8f8](https://github.com/fluxopt/pytest-benchmem/commit/2f6e8f8e0e9af74d183df03fc1ccc435bbb17b1e))
* rebuild `benchmem compare` columns on a metric × stat grid ([#101](https://github.com/fluxopt/pytest-benchmem/issues/101)) ([160e4af](https://github.com/fluxopt/pytest-benchmem/commit/160e4af94e46e1be0a2d413004f71c4d0b26e9eb))
* rebuild `benchmem compare` on pytest-benchmark's table model ([#98](https://github.com/fluxopt/pytest-benchmem/issues/98)) ([761c116](https://github.com/fluxopt/pytest-benchmem/commit/761c116f178d1de781c36661663baefb9be044db))
* show min…max spread whiskers on scaling plots ([#99](https://github.com/fluxopt/pytest-benchmem/issues/99)) ([a993c98](https://github.com/fluxopt/pytest-benchmem/commit/a993c98ee9d729780bbee920ac7100fd890dab54))
* spread varying memory metrics into min/mean/max columns ([#76](https://github.com/fluxopt/pytest-benchmem/issues/76)) ([01377ef](https://github.com/fluxopt/pytest-benchmem/commit/01377ef6456b5f24e4844a950654c032a9c2966d))
* suite-wide memory repeats + column/stat selection ([#79](https://github.com/fluxopt/pytest-benchmem/issues/79)) ([88251a7](https://github.com/fluxopt/pytest-benchmem/commit/88251a7cc24bda3e805437a6ad6d168c4a926a34))


### Bug Fixes

* anchor memory column scaling on the smallest value, not the largest ([#92](https://github.com/fluxopt/pytest-benchmem/issues/92)) ([aea8a33](https://github.com/fluxopt/pytest-benchmem/commit/aea8a335c918c8f1ceafbe7b41f2e93bad5e650c))
* compare no longer crashes when two runs share a file stem ([#64](https://github.com/fluxopt/pytest-benchmem/issues/64)) ([60d7e7b](https://github.com/fluxopt/pytest-benchmem/commit/60d7e7bad3904cb482bc9049e8498043543cb2d5))
* hoist byte units into the header in the standalone memory table ([#73](https://github.com/fluxopt/pytest-benchmem/issues/73)) ([8ad5a73](https://github.com/fluxopt/pytest-benchmem/commit/8ad5a731b2ee513f8e35186eb42e6792905928b6))


### Code Refactoring

* drop the gross metric and the now-obsolete mode tag ([#67](https://github.com/fluxopt/pytest-benchmem/issues/67)) ([90c7045](https://github.com/fluxopt/pytest-benchmem/commit/90c7045f8420e4c208760ea2b4b0fe4ff4b86187))
* store memory as per-repeat series; drop peak_max and the memory alias ([#75](https://github.com/fluxopt/pytest-benchmem/issues/75)) ([bc04805](https://github.com/fluxopt/pytest-benchmem/commit/bc04805d2c547c13b5dbf8bc3e99670e0864e328))

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
