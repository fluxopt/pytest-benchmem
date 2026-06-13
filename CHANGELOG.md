# Changelog

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
