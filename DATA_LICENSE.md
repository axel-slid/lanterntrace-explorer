# Data licensing and attribution

LanternTrace source code and third-party data have separate terms.

- The 2 August 2026 spotted-lanternfly occurrence snapshot comes from the GBIF occurrence index. Each record retains its GBIF key, dataset key, occurrence ID, and license. Among the 57,999 included analysis records, 48,835 are CC BY-NC 4.0, 6,738 are CC BY 4.0, and 2,426 are CC0 1.0. Reusers must follow each record's license and attribution requirements. The snapshot is not relicensed by this repository.
- The multi-host vegetation cache is a derived GBIF query result for tree-of-heaven, grape, black walnut, silver maple, willow, and red maple. It is supplied for exact computational replay and must not be interpreted as complete vegetation coverage, biomass, or an independently licensed occurrence dataset. Relative host weights use published first-instar survival durations from Nixon et al. (2020); individual GBIF record licenses remain in the cache.
- WorldClim 2.1 bioclimatic and elevation archives are downloaded from the official WorldClim distribution. Their source terms apply; the archives are not redistributed in this repository.
- The 2025 U.S. Census cartographic boundary archive is downloaded from the U.S. Census Bureau. U.S. federal cartographic data are public domain; source attribution is retained.
- OpenFreeMap/OpenStreetMap basemap content is used only at runtime and remains subject to its source attribution and terms.

The packaged desktop application includes the locked occurrence snapshot so Species Explorer is complete; the per-record upstream licenses above continue to apply. It excludes model-training caches and research-only inputs. See `research/input-lock.json` and `research/results/data_provenance.json` for exact sources and SHA-256 checksums.
