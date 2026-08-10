# LanternTrace spread-model literature review

Search updated **2026-08-09**. Scope: primary studies that estimate spotted lanternfly
(*Lycorma delicatula*) population growth, establishment, phenology, natural dispersal,
human-mediated dispersal, or dynamic range expansion. General biology papers are included
only where they parameterize a modeled process. This is a reproducible narrative search,
not a claim that every non-English thesis or unpublished agency analysis has been captured.

## What the literature supports

- **Two dispersal regimes are necessary.** Natural/diffusive boundary movement is about
  20–25 km/year, while human-mediated jumps create distant satellite populations. A 2025
  directional analysis estimated 25 ± 11 km/year after removing jumps; 89% of identified
  jumps were under 200 km.
- **Growth can be rapid after establishment.** A stage-structured life-cycle model estimated
  an annual multiplication factor of 5.47 under its assumptions. This is a population-scale
  growth prior, not a map-cell abundance observation.
- **Temperature gates development and establishment.** Degree-day, cold survival, and
  temperature-driven stage/age PDE studies show why a constant growth coefficient is
  inadequate. Recent cold-tolerance work also warns that coarse climate models may exclude
  northern areas too aggressively.
- **Host availability matters but is not a hard requirement.** Tree-of-heaven is the preferred
  adult host and is repeatedly important in suitability models, but multiple North American
  hosts support development. The model therefore uses a graded host coefficient rather than
  an impassable host/no-host mask.
- **Transport dominates long-range spread.** Agent-based, PoPS, Cox-hazard, and county-network
  models independently associate spread with human population, highways, rail, garden centers,
  and human footprint. Transport is modeled as a separate jump source, not inflated diffusion.
- **Elevation, land/water, and habitat resistance can constrain establishment.** Published
  MaxEnt and resistance-distance work supports spatially variable resistance. Terrain is a
  resistance term—not a claim that every mountain ridge is absolutely impassable.

## Primary modeling studies

| Year | Study | Model | Result used by LanternTrace |
|---|---|---|---|
| 2013 | Park, Kim & Lee, [Genetic structure… heterogeneous landscapes](https://doi.org/10.1017/S0007485313000011) | population genetics / gene flow | heterogeneous spread and evidence of long-distance movement in Korea |
| 2017 | Jung et al., [Model-based prediction… using CLIMEX](https://doi.org/10.1016/j.japb.2017.07.020) | CLIMEX climate envelope | temperature- and moisture-limited establishment prior |
| 2019 | Wakie et al., [Establishment risk in the United States and globally](https://doi.org/10.1093/jee/toz259) | MaxEnt | dry-quarter temperature, elevation, degree-days, isothermality, and cold-quarter precipitation |
| 2021 | Cook et al., [Spatial dynamics… Northeastern United States](https://doi.org/10.3897/neobiota.70.67950) | spread-rate estimation + Cox hazard | **Implemented benchmark comparator:** fixed $p_{ij}=e^{-0.045d_{ij}}$ and $1-\prod_j(1-p_{ij})$ proximity equations, transferred from county centroids to grid-cell centers; spatial proximity and human population increased invasion hazard in the original study |
| 2021 | Strömbom et al., [Modeling the life cycle…](https://doi.org/10.1016/j.mbs.2021.108670) | stage-structured population model | annual multiplication factor 5.47; control threshold implications |
| 2022 | Jones et al., [Predicted to establish in California by 2033](https://doi.org/10.1038/s42003-022-03447-0) | calibrated PoPS process model | reproduction, temperature, tree-of-heaven, short-distance kernel, and rail-network jumps; 84.4% validation accuracy |
| 2022 | Lewkiewicz et al., [Temperature sensitivity… age-structured PDE models](https://doi.org/10.1007/s00285-022-01800-9) | temperature-driven stage/age PDE | development, mortality, fecundity, diapause, and annual reproductive number depend on temperature |
| 2022 | Barringer & Ciafré / related host experiments summarized by Nixon et al., [Distribution, survival, and development on host plants](https://doi.org/10.1093/ee/nvaa126) | field trapping + survival/development experiments | graded host suitability; tree-of-heaven preference strengthens in adults |
| 2023 | Ladin et al., [Human-mediated dispersal drives spread](https://doi.org/10.1038/s41598-022-25989-3) | MaxEnt + agent-based spread model | tree-of-heaven (59% contribution), human footprint, climate, density-dependent jumps; human movement is essential |
| 2024 | Strömbom et al., [Modeling human activity-related spread](https://doi.org/10.1371/journal.pone.0307754) | county adjacency + highway network | primary interstates, garden centers, and population reproduce 2014–2021 spread with 81% county accuracy |
| 2024 | Zhao, Yang & Chen, [Globally suitable areas… optimized MaxEnt](https://doi.org/10.1002/ece3.70252) | tuned MaxEnt + climate scenarios | dry-quarter temperature dominates; suitable area expands in future climate scenarios |
| 2025 | Barker et al., [Real-Time Integrative Mapping of Phenology and Climatic Suitability](https://doi.org/10.3390/insects16080783) | DDRP degree-day / stress model | within-population developmental variation, phenology, life-cycle completion, cold/heat stress |
| 2025 | Belouard et al., [A method to quantify jump dispersal](https://doi.org/10.3897/neobiota.98.147310) | directional occurrence analysis (`jumpID`) | 25 ± 11 km/year diffusion-only spread; 152 jumps; 89% of jumps under 200 km |
| 2025 | Ruzzier et al., [Predicting global distribution and invasion scenarios](https://doi.org/10.3897/neobiota.103.154246) | SDM + resistance-distance constrained dispersal | habitat/host resistance and an approximately 25 km annual intrinsic spread limit |
| 2025 | Tran et al., [Cold tolerance strategy and lower temperature thresholds](https://doi.org/10.1093/ee/nvaf007) | thermal survival models | broad sensitivity analysis is safer than hard northern exclusion thresholds |
| 2026 | Belouard et al., [Leveraging spatial scale and temporal variation to track spread rate](https://doi.org/10.3897/neobiota.106.177041) | multiscale boundary optimization | peak median boundary displacement about 20.3–20.7 km/year in 2017–2019 |

## Movement and host parameter studies

- Keller et al. (2020), [Nymph dispersal through contiguous deciduous forest](https://doi.org/10.1093/ee/nvaa074):
  most movement was tens of metres or less over seven days; apparent uphill tendency needs replication.
- Baker et al. (2019), [Anemotactic flight tendencies](https://doi.org/10.3390/insects10090302):
  short adult flight bouts and directional behavior inform local anisotropy, not regional jumps.
- Nixon et al. (2020), [Host distribution, survival, and development](https://doi.org/10.1093/ee/nvaa126):
  eight tested plant species supported first-instar-to-adult development; host absence is not a hard wall.
- Murman et al. (2020), [Distribution, survival, and development on North American hosts](https://doi.org/10.1093/ee/nvaa126):
  supports stage-dependent host weighting.

## LanternTrace equation and ablations

Every candidate retains diffusion physics:

`∂u/∂t = ∇·(D(x,t)∇u) − v·∇u + r(x,t)u(1−u) + J(u,x) + εθ(u,x)`

- `u` is relative establishment intensity, not insect count.
- `D` is local diffusion, seasonally and spatially modified in some candidates.
- `v` is weak directional advection.
- `r` is logistic growth modified by host/climate/human-footprint suitability.
- `J` is a separate corridor-coupled satellite/jump process.
- `εθ` is a 10-hidden-unit neural residual trained on early-year transitions and blended
  conservatively into the physics step.

The 20 candidates are ablations, not 20 arbitrary forecasts. They add growth, advection,
host, climate, elevation, slope, land/water, corridor anisotropy, urban proximity, seasonal
forcing, jumps, and the learned residual individually and in evidence-motivated combinations.

For interactive historical playback, each top-five model is advanced at monthly time steps
from 2019 through 2025. Dated public reports are assimilated at each step, anchoring the
latent field while each candidate controls spread between and around those observations.
These are descriptive backcasts against the report stream, not independent validation.
Map boundaries are interpolated from a lightly smoothed intensity field for legibility; the
simulation itself remains on the documented 0.2-degree grid.

## Validation and limitations

Models train on 2014–2021 public-coordinate occurrence transitions and are ranked on rolling
2021→2022 through 2024→2025 predictions. The ranking emphasizes recall because a cell with no
public report is not a confirmed absence. F1, pseudo-absence precision, and Brier score remain
in the composite to penalize unconstrained expansion, but negative-cell penalties are weighted
by an urban-node reporting-effort proxy. This reduces the penalty in likely underreported cells;
it does not convert those cells into biological presences.

The map separately shows a short-range reporting-gap interpolation around locally connected
evidence. Its blue dashed boundary is descriptive continuity between nearby reports, not an
observation and not part of the coral repeat-report core.

This is a research prototype. GBIF/iNaturalist reports have spatially and temporally varying
effort, duplicate biological events may remain, host observations are also effort-biased,
urban proximity is a coarse reporting-effort proxy, and the forecast has no independent prospective field
validation. It must not be used as an operational quarantine or treatment recommendation.
