#!/usr/bin/env python3
"""Event-date retrospective frontier benchmark for LanternTrace.

The legacy app score rewards recovery of cumulative occupied cells. This study
instead predicts cells first reported after the forecast origin. The proposed
Observation-Guided Reaction-Diffusion Ensemble (OG-RDE) combines local
diffusion, habitat suitability, transport-jump physics, and a separately fitted
reporting model. Rolling folds exclude target event dates but cannot reconstruct
historical record-availability times, so they are retrospective pseudo-forecasts.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import pathlib
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "research" / "results"
FIGURES = ROOT / "research" / "figures"
GENERATED = ROOT / "generated"
BUILDER_PATH = ROOT / "scripts" / "build-diffusion-model.py"

spec = importlib.util.spec_from_file_location("lanterntrace_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(builder)

YEARS = list(range(2014, 2027))
DEVELOPMENT_TARGETS = [2022, 2023, 2024, 2025]
FINAL_TARGET = 2026
FROZEN_TRAINING_END = 2024
FROZEN_TARGETS = [2024, 2025]
FEATURE_NAMES = [
    "local_20km", "local_45km", "regional_90km", "regional_160km",
    "distance_front", "host", "climate", "corridor", "urban",
    "elevation_barrier", "slope_barrier", "latitude", "longitude",
    "fisher_risk", "climate_risk", "transport_risk", "full_physics_risk",
    "reporting_probability",
]
MODEL_PARAMETERS = {
    "grid": "0.2 degree cell centers; metric-adjusted at each latitude; 20 km reference spacing",
    "boundary": "zero-normal-gradient outer boundary; 2025 Census state mask; predictions clipped to mask",
    "timeStepMonths": 1.0,
    "baseDiffusionPerMonth": 0.19,
    "baseLogisticGrowthPerMonth": 0.13,
    "corridorConductivityMultiplier": 0.75,
    "advectionPerMonth": {"north": 0.018, "east": 0.012},
    "nonlocalGaussianSigmaCells": 4.0,
    "nonlocalAdditionPerMonth": 0.035,
    "hazardRegularizationC": 0.08,
    "positiveWeight": "min(12, sqrt(n_negative / n_positive))",
    "neighborhoodGaussianSigmaCells": [0.8, 1.7, 3.4, 6.0],
    "cook2021Kernel": {
        "citation": "Cook et al. 2021, doi:10.3897/neobiota.70.67950",
        "alphaPerKm": 0.045,
        "transfer": "published county-centroid kernel evaluated at 0.2-degree cell centers",
    },
}


@dataclass
class DataBundle:
    history: dict[int, np.ndarray]
    annual_counts: dict[int, np.ndarray]
    cumulative_counts: dict[int, np.ndarray]
    cov: dict[str, np.ndarray]
    records: list[list]
    accounting: dict[str, int]


def parse_records(records: list[list], analysis_mask: np.ndarray) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray], dict[int, np.ndarray], dict[str, int]]:
    annual = {year: np.zeros(builder.SHAPE, dtype=float) for year in YEARS}
    first_year = np.full(builder.SHAPE, 9999, dtype=int)
    dated_in_range = in_rectangle = in_analysis_mask = 0
    unique_cell_years: set[tuple[int, int, int]] = set()
    for record in records:
        try:
            lng, lat, date = float(record[0]), float(record[1]), str(record[2])
            year = int(date[:4])
        except (TypeError, ValueError):
            continue
        if year not in annual:
            continue
        dated_in_range += 1
        x = int((lng - builder.WEST) / builder.STEP)
        y = int((lat - builder.SOUTH) / builder.STEP)
        if 0 <= x < builder.SHAPE[1] and 0 <= y < builder.SHAPE[0]:
            in_rectangle += 1
            if not analysis_mask[y, x]:
                continue
            in_analysis_mask += 1
            unique_cell_years.add((year, y, x))
            annual[year][y, x] += 1
            first_year[y, x] = min(first_year[y, x], year)
    history = {year: (first_year <= year).astype(float) for year in YEARS}
    cumulative = {}
    running = np.zeros(builder.SHAPE, dtype=float)
    for year in YEARS:
        running = running + annual[year]
        cumulative[year] = running.copy()
    accounting = {
        "rawBundleRecords": len(records),
        "dated2014Through2026": dated_in_range,
        "insideRectangle": in_rectangle,
        "insideCensusAnalysisMask": in_analysis_mask,
        "uniqueCellYears": len(unique_cell_years),
        "uniqueFirstReportCells": int((first_year < 9999).sum()),
    }
    return history, annual, cumulative, accounting


def load_data() -> DataBundle:
    records = builder.load_observations()
    cov = builder.build_covariates()
    history, annual, cumulative, accounting = parse_records(records, cov["land"] > .5)
    return DataBundle(history, annual, cumulative, cov, records, accounting)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_provenance(data: DataBundle) -> dict:
    observation_text = builder.OBSERVATIONS.read_text()
    prefix = "window.LanternTraceObservations = "
    observation_payload = json.loads(observation_text[len(prefix):].rstrip(";\n"))
    paths = {
        "occurrenceBundle": builder.OBSERVATIONS,
        "hostCache": builder.CACHE / "ailanthus-altissima-ne.json",
        "censusStateBoundary": builder.CACHE / "cb_2025_us_state_500k.zip",
        "worldclimElevation": builder.CACHE / "wc2.1_10m_elev.zip",
        "worldclimBioclim": builder.CACHE / "wc2.1_10m_bio.zip",
        "studyScript": pathlib.Path(__file__),
        "solverScript": BUILDER_PATH,
    }
    return {
        "occurrenceMetadata": observation_payload.get("metadata", {}),
        "analysisAccounting": data.accounting,
        "censusBoundary": {"vintage": 2025, "url": builder.STATE_BOUNDARY_URL},
        "sha256": {name: sha256_file(path) for name, path in paths.items() if path.exists()},
        "limitation": "Historical origins are reconstructed by event date from a 2026 snapshot; record availability timestamps and time-versioned host covariates are unavailable.",
    }


def included_occurrence_manifest(data: DataBundle) -> pd.DataFrame:
    rows = []
    mask = data.cov["land"] > .5
    for record in data.records:
        try:
            lng, lat, date = float(record[0]), float(record[1]), str(record[2])
            year = int(date[:4])
        except (TypeError, ValueError):
            continue
        if year not in YEARS:
            continue
        x = int((lng - builder.WEST) / builder.STEP)
        y = int((lat - builder.SOUTH) / builder.STEP)
        if not (0 <= x < builder.SHAPE[1] and 0 <= y < builder.SHAPE[0] and mask[y, x]):
            continue
        rows.append({
            "gbifKey": record[3] if len(record) > 3 else "",
            "eventDate": date, "longitude": lng, "latitude": lat,
            "stateProvince": record[4] if len(record) > 4 else "",
            "datasetKey": record[7] if len(record) > 7 else "",
            "license": record[8] if len(record) > 8 else "",
            "occurrenceID": record[9] if len(record) > 9 else "",
            "gridX": x, "gridY": y,
        })
    return pd.DataFrame(rows)


def detection_design(data: DataBundle, target_year: int, excluded_block: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    rows, labels = [], []
    for year in range(2016, target_year):
        occupied = data.history[year - 1] > 0
        if excluded_block is not None:
            occupied &= spatial_block_grid() != excluded_block
        if not occupied.any():
            continue
        rows.append(np.column_stack([
            np.log1p(data.cumulative_counts[year - 1][occupied]),
            data.cov["urban"][occupied], data.cov["corridor"][occupied],
            data.cov["host"][occupied], data.cov["climate"][occupied],
            np.full(int(occupied.sum()), (year - 2016) / 10),
        ]))
        labels.append((data.annual_counts[year][occupied] > 0).astype(int))
    return np.vstack(rows), np.concatenate(labels)


def reporting_surface(data: DataBundle, target_year: int, excluded_block: int | None = None) -> np.ndarray:
    x, y = detection_design(data, target_year, excluded_block)
    if np.unique(y).size < 2:
        return np.full(builder.SHAPE, np.clip(float(y.mean()), .08, .96))
    model = LogisticRegression(C=.8, class_weight="balanced", max_iter=1200, random_state=73491)
    model.fit(x, y)
    previous = target_year - 1
    design = np.column_stack([
        np.log1p(data.cumulative_counts[previous].ravel()),
        data.cov["urban"].ravel(), data.cov["corridor"].ravel(),
        data.cov["host"].ravel(), data.cov["climate"].ravel(),
        np.full(builder.SHAPE[0] * builder.SHAPE[1], (target_year - 2016) / 10),
    ])
    return np.clip(model.predict_proba(design)[:, 1].reshape(builder.SHAPE), .08, .96)


PHYSICS = {
    "fisher": {"growth": True},
    "climate": {"growth": True, "climate": True},
    "transport": {"growth": True, "corridor": True, "urban": True, "jumps": True},
    "full": {"growth": True, "host": True, "climate": True, "elevation": True,
             "slope": True, "water": True, "corridor": True, "urban": True,
             "jumps": True, "seasonal": True, "advection": True},
}


def physics_risk(data: DataBundle, origin_year: int, name: str, months: int = 12) -> np.ndarray:
    occupied = data.history[origin_year]
    start = np.maximum(occupied, gaussian_filter(occupied, .8) * .74)
    final = builder.rollout(start, PHYSICS[name], data.cov, None, months)[-1]
    # Score only incremental frontier pressure, not already occupied cells.
    return np.clip(final - occupied * final, 0, 1)


def cook_2021_kernel(source_mask: np.ndarray, alpha_per_km: float = .045) -> np.ndarray:
    """Transfer Cook et al.'s published SLF dispersal kernel to grid-cell centers.

    Cook et al. (2021) used p_ij = exp(-alpha d_ij), alpha=0.045 km^-1,
    and SpatialProx_i = 1 - product_j(1-p_ij) across previously invaded
    county centroids. Here the same equations are evaluated across previously
    reported 0.2-degree cell centers; this is a scale transfer, not a replication
    of their county-level Cox analysis or structured-survey endpoint.
    """
    sources = np.column_stack(np.where(source_mask > 0))
    output = np.zeros(builder.SHAPE, dtype=float)
    if not len(sources):
        return output
    source_lat = builder.SOUTH + (sources[:, 0] + .5) * builder.STEP
    source_lon = builder.WEST + (sources[:, 1] + .5) * builder.STEP
    target_lat = builder.LAT_GRID.ravel()
    target_lon = builder.LON_GRID.ravel()
    proximity = np.empty(target_lat.size, dtype=float)
    for start in range(0, target_lat.size, 512):
        stop = min(start + 512, target_lat.size)
        lat = target_lat[start:stop, None]
        lon = target_lon[start:stop, None]
        dy_km = (lat - source_lat[None, :]) * 111.0
        mean_lat = np.radians((lat + source_lat[None, :]) / 2)
        dx_km = (lon - source_lon[None, :]) * 111.0 * np.cos(mean_lat)
        distance_km = np.hypot(dx_km, dy_km)
        per_source = np.exp(-alpha_per_km * distance_km)
        log_no_arrival = np.log1p(-np.minimum(per_source, 1 - 1e-15)).sum(axis=1)
        proximity[start:stop] = -np.expm1(log_no_arrival)
    output[:] = proximity.reshape(builder.SHAPE)
    return output


def feature_cube(data: DataBundle, origin_year: int, target_year: int, months: int = 12,
                 reporting_excluded_block: int | None = None) -> np.ndarray:
    occupied = data.history[origin_year]
    distance = distance_transform_edt(occupied <= 0) * builder.STEP * 92
    effort = reporting_surface(data, target_year, reporting_excluded_block)
    channels = [
        gaussian_filter(occupied, .8), gaussian_filter(occupied, 1.7),
        gaussian_filter(occupied, 3.4), gaussian_filter(occupied, 6.0),
        np.exp(-distance / 95), data.cov["host"], data.cov["climate"],
        data.cov["corridor"], data.cov["urban"], data.cov["elevation_barrier"],
        data.cov["slope_barrier"],
        (builder.LAT_GRID - builder.SOUTH) / (builder.NORTH - builder.SOUTH),
        (builder.LON_GRID - builder.WEST) / (builder.EAST - builder.WEST),
        physics_risk(data, origin_year, "fisher", months),
        physics_risk(data, origin_year, "climate", months),
        physics_risk(data, origin_year, "transport", months),
        physics_risk(data, origin_year, "full", months), effort,
    ]
    return np.stack(channels, axis=-1)


def eligible_mask(data: DataBundle, origin_year: int) -> np.ndarray:
    return (data.history[origin_year] <= 0) & (data.cov["land"] > .5)


def target_new_cells(data: DataBundle, origin_year: int, target_year: int) -> np.ndarray:
    return ((data.history[target_year] > 0) & (data.history[origin_year] <= 0)).astype(int)


def feature_subset(features: np.ndarray, use_reporting: bool, use_transport: bool) -> np.ndarray:
    remove = []
    if not use_transport:
        remove.extend([7, 8, 15, 16])
    if not use_reporting:
        remove.append(17)
    return np.delete(features, sorted(set(remove)), axis=1) if remove else features


COVARIATE_HAZARD_FEATURES = [0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12]


def selected_features(features: np.ndarray, use_reporting: bool, use_transport: bool,
                      covariate_only: bool = False) -> np.ndarray:
    if covariate_only:
        return features[:, COVARIATE_HAZARD_FEATURES]
    return feature_subset(features, use_reporting, use_transport)


def spatial_block_grid() -> np.ndarray:
    block_x = ((builder.LON_GRID - builder.WEST) // 2).astype(int)
    block_y = ((builder.LAT_GRID - builder.SOUTH) // 2).astype(int)
    return block_y * 20 + block_x


def train_ogrde(data: DataBundle, target_year: int, use_reporting: bool = True, use_transport: bool = True,
                excluded_block: int | None = None, covariate_only: bool = False,
                regularization_c: float = .08, positive_weight_cap: float = 12.0,
                training_end_year: int | None = None):
    xs, ys, ws = [], [], []
    training_end = target_year if training_end_year is None else training_end_year
    if training_end > target_year:
        raise ValueError("training_end_year cannot follow the prediction target")
    for year in range(2018, training_end):
        origin = year - 1
        cube = feature_cube(data, origin, year, reporting_excluded_block=excluded_block if use_reporting else None)
        mask = eligible_mask(data, origin)
        if excluded_block is not None:
            mask &= spatial_block_grid() != excluded_block
        labels = target_new_cells(data, origin, year)[mask]
        features = cube[mask]
        features = selected_features(features, use_reporting, use_transport, covariate_only)
        # Balance classes without treating non-reports as confirmed absences or
        # allowing the rare first detections to dominate the likelihood.
        positive_scale = min(positive_weight_cap, math.sqrt(max((labels == 0).sum(), 1) / max((labels == 1).sum(), 1)))
        weights = np.where(labels > 0, positive_scale, 1.0)
        xs.append(features); ys.append(labels); ws.append(weights)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=regularization_c, max_iter=2000, random_state=73491),
    )
    model.fit(
        np.vstack(xs), np.concatenate(ys),
        logisticregression__sample_weight=np.concatenate(ws),
    )
    return model


def stable_descending_order(values: np.ndarray) -> np.ndarray:
    """Rank high-to-low with a reproducible lower-index tie break.

    Quantization prevents inconsequential BLAS/platform roundoff from changing
    the membership of an operational top-fraction allocation. Cell index is
    the declared deterministic secondary key.
    """
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=-np.inf)
    quantized = np.round(values, 12)
    return np.lexsort((np.arange(len(quantized)), -quantized))


def select_top_fraction(score: np.ndarray, fraction: float = .05) -> np.ndarray:
    count = max(1, int(math.ceil(len(score) * fraction)))
    return stable_descending_order(score)[:count]


def percentile_grid(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    output = np.zeros_like(values, dtype=float)
    order = stable_descending_order(values[mask])
    ranked = np.empty(len(order), dtype=float)
    ranked[order] = np.arange(len(order) - 1, -1, -1, dtype=float)
    output[mask] = ranked / max(len(ranked) - 1, 1)
    return output


def predict_ogrde(data: DataBundle, target_year: int, use_reporting: bool = True, use_transport: bool = True,
                  excluded_block: int | None = None, covariate_only: bool = False,
                  regularization_c: float = .08, positive_weight_cap: float = 12.0,
                  training_end_year: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    origin = target_year - 1
    months = 7 if target_year == 2026 else 12
    cube = feature_cube(data, origin, target_year, months, excluded_block if use_reporting else None)
    model = train_ogrde(data, target_year, use_reporting, use_transport, excluded_block, covariate_only,
                        regularization_c, positive_weight_cap, training_end_year)
    features = cube.reshape(-1, cube.shape[-1])
    features = selected_features(features, use_reporting, use_transport, covariate_only)
    learned = model.predict_proba(features)[:, 1].reshape(builder.SHAPE)
    mask = eligible_mask(data, target_year - 1)
    learned_rank = percentile_grid(learned, mask)
    if use_transport and not covariate_only:
        transport = physics_risk(data, target_year - 1, "transport", months)
        risk = .5 * learned_rank + .5 * percentile_grid(transport, mask)
    else:
        risk = learned_rank
    return risk, cube[..., -1]


def predict_ogrde_leave_block_out(data: DataBundle, target_year: int, use_reporting: bool = False,
                                  use_transport: bool = False) -> np.ndarray:
    """Cross-fit hazard coefficients while preserving origin-time state fields."""
    mask = eligible_mask(data, target_year - 1)
    block_grid = spatial_block_grid()
    risk = np.zeros(builder.SHAPE, dtype=float)
    for block in np.unique(block_grid[mask]):
        local = mask & (block_grid == block)
        local_risk, _ = predict_ogrde(data, target_year, use_reporting, use_transport, int(block))
        risk[local] = local_risk[local]
    return risk


def reporting_surface_leave_block_out(data: DataBundle, target_year: int) -> np.ndarray:
    mask = eligible_mask(data, target_year - 1)
    block_grid = spatial_block_grid()
    risk = np.zeros(builder.SHAPE, dtype=float)
    for block in np.unique(block_grid[mask]):
        local = mask & (block_grid == block)
        local_surface = reporting_surface(data, target_year, int(block))
        risk[local] = local_surface[local]
    return risk


def predict_covariate_hazard(data: DataBundle, target_year: int, excluded_block: int | None = None) -> np.ndarray:
    return predict_ogrde(data, target_year, False, False, excluded_block, True)[0]


def predict_frozen_learned(data: DataBundle, target_year: int, covariate_only: bool = False) -> np.ndarray:
    """Apply one pre-2024 coefficient fit to a later annual origin state."""
    return predict_ogrde(
        data, target_year, False, False, covariate_only=covariate_only,
        training_end_year=FROZEN_TRAINING_END,
    )[0]


def predict_covariate_leave_block_out(data: DataBundle, target_year: int) -> np.ndarray:
    mask = eligible_mask(data, target_year - 1)
    block_grid = spatial_block_grid()
    risk = np.zeros(builder.SHAPE, dtype=float)
    for block in np.unique(block_grid[mask]):
        local = mask & (block_grid == block)
        local_risk = predict_covariate_hazard(data, target_year, int(block))
        risk[local] = local_risk[local]
    return risk


def recall_at_fraction(y: np.ndarray, score: np.ndarray, fraction: float = .05) -> float:
    if y.sum() == 0:
        return float("nan")
    selected = select_top_fraction(score, fraction)
    return float(y[selected].sum() / y.sum())


def metric_row(year: int, model: str, y: np.ndarray, score: np.ndarray, effort: np.ndarray) -> dict:
    score = np.nan_to_num(score, nan=0, posinf=1, neginf=0)
    return {
        "year": year, "model": model, "positives": int(y.sum()), "candidates": len(y),
        "average_precision": float(average_precision_score(y, score)),
        "roc_auc": float(roc_auc_score(y, score)),
        "recall_at_5pct": recall_at_fraction(y, score, .05),
    }


def endpoint_comparison(data: DataBundle) -> pd.DataFrame:
    """Matched AP comparison showing cumulative-target persistence credit."""
    rows = []
    land = data.cov["land"] > .5
    for year in DEVELOPMENT_TARGETS:
        origin = year - 1
        start = np.maximum(data.history[origin], gaussian_filter(data.history[origin], .8) * .74)
        raw = builder.rollout(start, PHYSICS["transport"], data.cov, None, 12)[-1]
        cumulative_truth = data.history[year][land].astype(int)
        frontier_mask = eligible_mask(data, origin)
        frontier_truth = target_new_cells(data, origin, year)[frontier_mask]
        items = [
            ("Transport RD", "cumulative", cumulative_truth, raw[land]),
            ("Transport RD", "first-report frontier", frontier_truth, physics_risk(data, origin, "transport", 12)[frontier_mask]),
            ("Persistence only", "cumulative", cumulative_truth, data.history[origin][land]),
        ]
        for model, endpoint_name, labels, scores in items:
            prevalence = float(labels.mean())
            ap = float(average_precision_score(labels, scores))
            rows.append({
                "year": year, "model": model, "endpoint": endpoint_name,
                "positives": int(labels.sum()), "candidates": int(len(labels)),
                "prevalence": prevalence, "average_precision": ap,
                "normalized_ap_lift": float((ap - prevalence) / max(1 - prevalence, 1e-12)),
            })
    return pd.DataFrame(rows)


def parameter_sensitivity(data: DataBundle, year: int = 2025) -> pd.DataFrame:
    """One-at-a-time physics and compact hazard sensitivity checks."""
    origin = year - 1
    mask = eligible_mask(data, origin)
    truth = target_new_cells(data, origin, year)[mask]
    start = np.maximum(data.history[origin], gaussian_filter(data.history[origin], .8) * .74)
    rows = []
    for parameter in ("diffusion", "growth", "jump"):
        for scale in (.75, 1.0, 1.25):
            risk = builder.rollout(start, PHYSICS["transport"], data.cov, None, 12,
                                   parameter_scales={parameter: scale})[-1]
            rows.append({"family": "Transport RD", "parameter": parameter, "value": scale,
                         "year": year, "average_precision": float(average_precision_score(truth, risk[mask]))})
    for c_value in (.03, .08, .20):
        for cap in (6.0, 12.0):
            annual = []
            for target in DEVELOPMENT_TARGETS:
                local_mask = eligible_mask(data, target - 1)
                local_truth = target_new_cells(data, target - 1, target)[local_mask]
                risk = predict_ogrde(data, target, False, False, regularization_c=c_value,
                                     positive_weight_cap=cap)[0]
                annual.append(average_precision_score(local_truth, risk[local_mask]))
            rows.append({"family": "OG-RDE", "parameter": f"C={c_value:g}; cap={cap:g}", "value": c_value,
                         "year": "2022-2025 mean", "average_precision": float(np.mean(annual))})
    return pd.DataFrame(rows)


def numerical_sensitivity(data: DataBundle, year: int = 2025) -> pd.DataFrame:
    """Check monthly Euler results against half- and quarter-month steps."""
    origin = year - 1
    start = np.maximum(data.history[origin], gaussian_filter(data.history[origin], .8) * .74)
    mask = eligible_mask(data, origin)
    truth = target_new_cells(data, origin, year)[mask]
    rows = []
    for model, key in (("Transport RD", "transport"), ("Full mechanistic", "full")):
        reference = builder.rollout(start, PHYSICS[key], data.cov, None, 12, time_step_months=1.0)[-1]
        for step in (1.0, .5, .25):
            result = builder.rollout(start, PHYSICS[key], data.cov, None, int(round(12 / step)), time_step_months=step)[-1]
            rows.append({
                "year": year, "model": model, "stepMonths": step,
                "average_precision": float(average_precision_score(truth, result[mask])),
                "spearmanVsMonthly": float(spearmanr(reference[mask], result[mask]).statistic),
                "meanAbsoluteDifference": float(np.mean(np.abs(reference[mask] - result[mask]))),
            })
    return pd.DataFrame(rows)


def annual_paired_comparisons(metrics: pd.DataFrame, reference: str = "OG-RDE", seed: int = 73491) -> pd.DataFrame:
    development = metrics[metrics.year.isin(DEVELOPMENT_TARGETS)]
    wide = development.pivot(index="year", columns="model", values="average_precision")
    rng = np.random.default_rng(seed)
    # Reuse the same resampled years for every competitor. This preserves the
    # paired design and makes an existing interval invariant to adding or
    # reordering other model columns.
    sample_indices = rng.integers(0, len(wide), size=(2500, len(wide)))
    rows = []
    for competitor in wide.columns:
        if competitor == reference:
            continue
        delta = (wide[reference] - wide[competitor]).to_numpy()
        draws = delta[sample_indices].mean(axis=1)
        rows.append({
            "reference": reference, "competitor": competitor,
            "mean_delta_ap": float(delta.mean()),
            "delta_low": float(np.quantile(draws, .025)),
            "delta_high": float(np.quantile(draws, .975)),
            "completeYears": int(len(delta)),
        })
    return pd.DataFrame(rows).sort_values("mean_delta_ap", ascending=False)


def regional_activation_metrics(year: int, scores: dict[str, np.ndarray], mask: np.ndarray,
                                truth: np.ndarray) -> list[dict]:
    block_grid = spatial_block_grid()
    rows = []
    blocks = np.unique(block_grid[mask])
    for name, grid in scores.items():
        labels, risks = [], []
        for block in blocks:
            local = mask & (block_grid == block)
            labels.append(int(truth[local].sum() > 0))
            risks.append(float(np.quantile(grid[local], .95)))
        if 0 < sum(labels) < len(labels):
            rows.append({"year": year, "model": name, "blocks": len(blocks),
                         "positiveBlocks": int(sum(labels)),
                         "activation_ap": float(average_precision_score(labels, risks))})
    return rows


def evaluate_year(data: DataBundle, target_year: int) -> tuple[list[dict], dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    origin = target_year - 1
    months = 7 if target_year == 2026 else 12
    mask = eligible_mask(data, origin)
    truth_grid = target_new_cells(data, origin, target_year)
    y = truth_grid[mask]
    effort_grid = reporting_surface(data, target_year)
    distance = distance_transform_edt(data.history[origin] <= 0) * builder.STEP
    scores = {
        "Distance kernel": np.exp(-distance / 2.4),
        "Cook-2021 kernel": cook_2021_kernel(data.history[origin]),
        "Fisher-KPP": physics_risk(data, origin, "fisher", months),
        "Climate RD": physics_risk(data, origin, "climate", months),
        "Transport RD": physics_risk(data, origin, "transport", months),
        "Full mechanistic": physics_risk(data, origin, "full", months),
        "Reporting surface": effort_grid,
        "Covariate hazard": predict_covariate_hazard(data, target_year),
    }
    # The final specification omits the weak recurrence-based reporting proxy;
    # reporting and explicit transport fusion remain transparent ablations.
    scores["OG-RDE"] = predict_ogrde(data, target_year, False, False)[0]
    scores["OG-RDE + reporting"] = predict_ogrde(data, target_year, True, False)[0]
    scores["OG-RDE + transport"] = predict_ogrde(data, target_year, True, True)[0]
    rows = [metric_row(target_year, name, y, grid[mask], effort_grid[mask]) for name, grid in scores.items()]
    return rows, scores, mask, truth_grid, effort_grid


def evaluate_frozen_year(data: DataBundle, target_year: int) -> tuple[list[dict], dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Replay a target after freezing learned coefficients before 2024.

    Annual event-date state is assimilated at each origin, as it would be in an
    operational rolling forecast, but target outcomes never change coefficients,
    feature selection, regularization, or the fixed 5% survey-budget rule.
    """
    if target_year not in FROZEN_TARGETS:
        raise ValueError(f"frozen target must be one of {FROZEN_TARGETS}")
    origin = target_year - 1
    mask = eligible_mask(data, origin)
    truth_grid = target_new_cells(data, origin, target_year)
    y = truth_grid[mask]
    effort_grid = reporting_surface(data, FROZEN_TRAINING_END)
    distance = distance_transform_edt(data.history[origin] <= 0) * builder.STEP
    scores = {
        "Distance kernel": np.exp(-distance / 2.4),
        "Cook-2021 kernel": cook_2021_kernel(data.history[origin]),
        "Fisher-KPP": physics_risk(data, origin, "fisher", 12),
        "Climate RD": physics_risk(data, origin, "climate", 12),
        "Transport RD": physics_risk(data, origin, "transport", 12),
        "Full mechanistic": physics_risk(data, origin, "full", 12),
        "Covariate hazard": predict_frozen_learned(data, target_year, True),
        "OG-RDE": predict_frozen_learned(data, target_year, False),
    }
    rows = [metric_row(target_year, name, y, grid[mask], effort_grid[mask]) for name, grid in scores.items()]
    return rows, scores, mask, truth_grid


def block_metrics(data: DataBundle, year: int, scores: dict[str, np.ndarray], mask: np.ndarray, truth: np.ndarray) -> list[dict]:
    block_id = spatial_block_grid()
    rows = []
    for block in np.unique(block_id[mask]):
        local = mask & (block_id == block)
        y = truth[local]
        if y.sum() == 0 or (~y.astype(bool)).sum() == 0:
            continue
        for name, grid in scores.items():
            rows.append({
                "year": year, "block": int(block), "model": name,
                "average_precision": float(average_precision_score(y, grid[local])),
                "recall_at_5pct": recall_at_fraction(y, grid[local], .05),
                "positives": int(y.sum()), "candidates": int(local.sum()),
            })
    return rows


def bootstrap_summary(block_df: pd.DataFrame, seed: int = 73491) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    units = block_df["block"].drop_duplicates().to_numpy()
    models = list(block_df["model"].unique())
    draws = {model: [] for model in models}
    for _ in range(2500):
        sample = units[rng.integers(0, len(units), len(units))]
        keys = pd.DataFrame({"block": sample})
        merged = keys.merge(block_df, on="block", how="left")
        for model in models:
            draws[model].append(float(merged.loc[merged.model == model, "average_precision"].mean()))
    rows = []
    for model, values in draws.items():
        rows.append({
            "model": model, "block_ap_mean": float(np.mean(values)),
            "block_ap_low": float(np.quantile(values, .025)),
            "block_ap_high": float(np.quantile(values, .975)),
        })
    return pd.DataFrame(rows).sort_values("block_ap_mean", ascending=False)


def paired_block_comparisons(block_df: pd.DataFrame, reference: str = "OG-RDE", seed: int = 73491) -> pd.DataFrame:
    """Paired geographic-block bootstrap retaining repeated years."""
    rng = np.random.default_rng(seed)
    wide = block_df.pivot_table(index=["year", "block"], columns="model", values="average_precision")
    wide = wide.dropna()
    competitors = [name for name in wide.columns if name != reference]
    blocks = wide.reset_index()["block"].unique()
    sampled_blocks = blocks[rng.integers(0, len(blocks), size=(2500, len(blocks)))]
    rows = []
    for competitor in competitors:
        delta_frame = (wide[reference] - wide[competitor]).rename("delta").reset_index()
        delta = delta_frame["delta"].to_numpy()
        draws = np.empty(2500, dtype=float)
        for index, sampled in enumerate(sampled_blocks):
            draw = pd.DataFrame({"block": sampled}).merge(delta_frame, on="block", how="left")
            draws[index] = draw["delta"].mean()
        rows.append({
            "reference": reference,
            "competitor": competitor,
            "mean_delta_ap": float(delta.mean()),
            "delta_low": float(np.quantile(draws, .025)),
            "delta_high": float(np.quantile(draws, .975)),
            "probability_reference_better": float((draws > 0).mean()),
            "pairedBlockYears": int(len(delta)),
            "uniqueGeographicBlocks": int(len(blocks)),
        })
    return pd.DataFrame(rows).sort_values("mean_delta_ap", ascending=False)


def set_plot_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 10,
        "axes.labelsize": 8.5, "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 160, "savefig.dpi": 300, "savefig.bbox": "tight",
    })


def save_figure(fig: plt.Figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    fig.savefig(FIGURES / f"{name}.png")
    plt.close(fig)


def export_frozen_benchmark(frozen_metrics: pd.DataFrame, frozen_summary: pd.DataFrame,
                            frozen_comparisons: pd.DataFrame, frozen_predictions: dict) -> None:
    """Emit a compact, committed app artifact for the frozen evaluation replay."""
    model_order = [
        "Covariate hazard", "OG-RDE", "Transport RD", "Climate RD",
        "Fisher-KPP", "Full mechanistic", "Cook-2021 kernel", "Distance kernel",
    ]
    summary_by_model = frozen_summary.set_index("model")
    comparison_by_model = frozen_comparisons.set_index("competitor")
    models = []
    for model in model_order:
        annual = frozen_metrics[frozen_metrics.model == model].set_index("year")
        block = summary_by_model.loc[model]
        comparison = comparison_by_model.loc[model] if model != "OG-RDE" else None
        models.append({
            "id": model.lower().replace("-", "_").replace(" ", "_"),
            "name": model,
            "metrics": {
                str(year): {
                    "averagePrecision": round(float(annual.loc[year, "average_precision"]), 6),
                    "recallAt5Pct": round(float(annual.loc[year, "recall_at_5pct"]), 6),
                }
                for year in FROZEN_TARGETS
            },
            "blockAveragePrecision": round(float(block.block_ap_mean), 6),
            "blockInterval": [round(float(block.block_ap_low), 6), round(float(block.block_ap_high), 6)],
            "ogRdeDifference": None if comparison is None else {
                "mean": round(float(-comparison.mean_delta_ap), 6),
                "interval": [round(float(-comparison.delta_high), 6), round(float(-comparison.delta_low), 6)],
                "meaning": f"{model} minus OG-RDE within-block AP",
            },
        })
    years = {}
    for year, item in frozen_predictions.items():
        mask = item["mask"]
        years[str(year)] = {
            "eligibleIndices": np.flatnonzero(mask.ravel()).astype(int).tolist(),
            "truthIndices": np.flatnonzero((item["truth"] > 0).ravel()).astype(int).tolist(),
            "top5CellCount": int(math.ceil(mask.sum() * .05)),
            "scores": {
                model.lower().replace("-", "_").replace(" ", "_"):
                    np.round(percentile_grid(item["scores"][model], mask).ravel(), 4).tolist()
                for model in model_order
            },
        }
    payload = {
        "metadata": {
            "title": "Frozen first-report replay",
            "trainingTransitions": "2018-2023",
            "targets": FROZEN_TARGETS,
            "endpoint": "cells first reported in target year among prior-year unreported U.S. land cells",
            "status": "post-hoc frozen temporal replay; not preregistered, calibrated occupancy, or independent field validation",
            "grid": {
                "west": builder.WEST, "east": builder.EAST,
                "south": builder.SOUTH, "north": builder.NORTH,
                "stepDegrees": builder.STEP, "rows": builder.SHAPE[0], "columns": builder.SHAPE[1],
            },
            "source": "research/results/frozen_temporal_metrics.csv and prediction_grids.npz",
        },
        "models": models,
        "years": years,
    }
    GENERATED.mkdir(parents=True, exist_ok=True)
    output = "window.LanternTraceBenchmark = " + json.dumps(payload, separators=(",", ":"), allow_nan=False) + ";\n"
    (GENERATED / "frozen-benchmark.js").write_text(output)


def make_figures(data: DataBundle, metrics: pd.DataFrame, summary: pd.DataFrame, prediction_store: dict,
                 endpoint: pd.DataFrame, sensitivity: pd.DataFrame, frozen_metrics: pd.DataFrame,
                 frozen_summary: pd.DataFrame, frozen_predictions: dict,
                 frozen_blocks: pd.DataFrame) -> None:
    set_plot_style()
    green, coral, blue, gold = "#13795b", "#d95d52", "#2676a8", "#d5a021"

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.65), gridspec_kw={"width_ratios": [1.05, 1]})
    years = np.arange(2014, 2027)
    cumulative = [int(data.history[y].sum()) for y in years]
    new = [int(target_new_cells(data, y - 1, y).sum()) if y > 2014 else cumulative[0] for y in years]
    axes[0].plot(years, cumulative, color=green, marker="o", lw=2, ms=3, label="cumulative reported cells")
    axes[0].bar(years, new, color=coral, alpha=.55, label="first-reported cells")
    axes[0].axvspan(2022, 2025, color=blue, alpha=.08, label="rolling evaluation")
    axes[0].axvspan(2025.92, 2026.35, color=gold, alpha=.18, label="interim 2026 monitoring")
    axes[0].set(xlabel="year", ylabel="0.2-degree grid cells", title="Observed expansion endpoint")
    axes[0].legend(frameon=False, fontsize=6.5, ncol=2)

    target = prediction_store[2025]
    risk = target["scores"]["OG-RDE"]
    image = axes[1].imshow(risk, origin="lower", extent=[builder.WEST, builder.EAST, builder.SOUTH, builder.NORTH],
                           cmap=LinearSegmentedColormap.from_list("risk", ["#f4f1e8", "#8fd3b6", green]), aspect="auto")
    yy, xx = np.where(target["truth"] > 0)
    axes[1].scatter(builder.WEST + (xx + .5) * builder.STEP, builder.SOUTH + (yy + .5) * builder.STEP,
                    s=13, facecolors="none", edgecolors=coral, lw=.8, label="2025 first reports")
    _, state_rings = builder.load_us_state_geometry()
    for ring in state_rings:
        axes[1].plot(ring[:, 0], ring[:, 1], color="#536960", lw=.25, alpha=.65)
    axes[1].set(xlabel="longitude", ylabel="latitude", title="One-year frontier risk (2025 fold)")
    axes[1].set_xlim(builder.WEST, builder.EAST)
    axes[1].set_ylim(builder.SOUTH, builder.NORTH)
    axes[1].legend(frameon=False, fontsize=6.5, loc="lower right")
    fig.colorbar(image, ax=axes[1], fraction=.04, pad=.02, label="relative risk")
    fig.tight_layout()
    save_figure(fig, "fig1_endpoint_and_map")

    selected_models = ["Distance kernel", "Cook-2021 kernel", "Reporting surface", "Covariate hazard", "Fisher-KPP",
                       "Climate RD", "Transport RD", "Full mechanistic", "OG-RDE"]
    primary = summary[summary.model.isin(selected_models)].sort_values("block_ap_mean")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.35))
    for (model, endpoint_name), part in endpoint.groupby(["model", "endpoint"]):
        label = f"{model}: {endpoint_name}"
        style = "--" if model == "Persistence only" else "-"
        color = "#888888" if model == "Persistence only" else (green if endpoint_name == "cumulative" else coral)
        axes[0].plot(part.year, part.average_precision, marker="o", lw=1.6, ls=style, color=color, label=label)
    axes[0].set(xlabel="target year", ylabel="average precision", title="Matched endpoint audit", ylim=(0.35, 1.0))
    axes[0].set_xticks(DEVELOPMENT_TARGETS)
    axes[0].legend(frameon=False, fontsize=5.8)
    axes[0].grid(color="#e5e9e6", lw=.5)
    y_pos = np.arange(len(primary))
    axes[1].errorbar(primary.block_ap_mean, y_pos,
                     xerr=[primary.block_ap_mean - primary.block_ap_low, primary.block_ap_high - primary.block_ap_mean],
                     fmt="o", color=green, ecolor="#8a9c94", capsize=2.5, ms=5)
    axes[1].set_yticks(y_pos, primary.model)
    axes[1].set(xlabel="within-block AP (95% geographic bootstrap)", title="Geographic block robustness")
    axes[1].grid(axis="x", color="#dfe6e2", lw=.6)
    fig.tight_layout()
    save_figure(fig, "fig2_benchmark")

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.7))
    selected = ["Distance kernel", "Cook-2021 kernel", "Climate RD", "Transport RD", "OG-RDE"]
    palette = {"Distance kernel": "#888888", "Cook-2021 kernel": "#7b5aa6", "Climate RD": blue,
               "Transport RD": gold, "OG-RDE": green}
    for name in selected:
        part = metrics[metrics.model == name]
        axes[0].plot(part.year, part.average_precision, marker="o", lw=1.7, color=palette[name], label=name)
        axes[1].plot(part.year, part.recall_at_5pct, marker="o", lw=1.7, color=palette[name], label=name)
    for ax, ylabel, title in zip(axes, ["average precision", "recall in top 5%"], ["Ranking new cells", "Survey-budget capture"]):
        ax.set(xlabel="forecast target year", ylabel=ylabel, title=title)
        ax.axvline(2025.5, color="#555", ls="--", lw=.8)
        ax.grid(color="#e5e9e6", lw=.5)
    axes[0].legend(frameon=False, fontsize=6.5, ncol=2)
    fig.tight_layout()
    save_figure(fig, "fig3_temporal_performance")

    ablation = summary[summary.model.str.startswith("OG-RDE")].sort_values("block_ap_mean")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.35))
    axes[0].barh(ablation.model, ablation.block_ap_mean, color=["#aabbb3", "#6fa88e", green])
    axes[0].errorbar(ablation.block_ap_mean, np.arange(len(ablation)),
                     xerr=[ablation.block_ap_mean - ablation.block_ap_low, ablation.block_ap_high - ablation.block_ap_mean],
                     fmt="none", ecolor="#30463c", capsize=2)
    axes[0].set(xlabel="leave-block-out average precision", title="OG-RDE additions")
    axes[0].grid(axis="x", color="#e5e9e6", lw=.5)
    for model, part in sensitivity.groupby("model"):
        axes[1].plot(part.stepMonths, part.average_precision, marker="o", lw=1.6, label=model)
    axes[1].invert_xaxis()
    axes[1].set(xlabel="Euler step (months; finer to right)", ylabel="2025 average precision", title="Time-step sensitivity")
    axes[1].legend(frameon=False, fontsize=6.5)
    axes[1].grid(color="#e5e9e6", lw=.5)
    fig.tight_layout()
    save_figure(fig, "fig4_ablation")

    # Frozen temporal replay: coefficients use transitions only through 2023.
    selected_frozen = ["Cook-2021 kernel", "Covariate hazard", "Climate RD", "Transport RD", "OG-RDE"]
    palette.update({"Covariate hazard": "#3c8c9e"})
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.7), gridspec_kw={"width_ratios": [1.03, .97]})
    for name in selected_frozen:
        part = frozen_metrics[frozen_metrics.model == name]
        axes[0].plot(part.year, part.average_precision, marker="o", ms=5, lw=1.8,
                     color=palette.get(name, "#666666"), label=name)
    axes[0].set(xlabel="frozen target year", ylabel="average precision",
                title="Pre-2024 coefficient freeze")
    axes[0].set_xticks(FROZEN_TARGETS)
    axes[0].grid(color="#e5e9e6", lw=.5)
    axes[0].legend(frameon=False, fontsize=6.2, ncol=2)
    frozen_primary = frozen_summary.sort_values("block_ap_mean")
    y_pos = np.arange(len(frozen_primary))
    axes[1].errorbar(
        frozen_primary.block_ap_mean, y_pos,
        xerr=[frozen_primary.block_ap_mean - frozen_primary.block_ap_low,
              frozen_primary.block_ap_high - frozen_primary.block_ap_mean],
        fmt="o", color=green, ecolor="#8a9c94", capsize=2.5, ms=4.5,
    )
    axes[1].set_yticks(y_pos, frozen_primary.model)
    axes[1].set(xlabel="within-block AP (95% block bootstrap)",
                title="Frozen replay by geography")
    axes[1].grid(axis="x", color="#dfe6e2", lw=.6)
    fig.tight_layout()
    save_figure(fig, "fig5_frozen_validation")

    # Spatial inspection of the two untouched target years.
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.95))
    _, state_rings = builder.load_us_state_geometry()
    risk_cmap = LinearSegmentedColormap.from_list("frozen-risk", ["#f4f1e8", "#8fd3b6", green])
    for ax, year in zip(axes, FROZEN_TARGETS):
        item = frozen_predictions[year]
        risk = item["scores"]["OG-RDE"].copy()
        risk[~item["mask"]] = np.nan
        image = ax.imshow(risk, origin="lower", extent=[builder.WEST, builder.EAST, builder.SOUTH, builder.NORTH],
                          cmap=risk_cmap, vmin=0, vmax=1, aspect="auto")
        eligible_flat = np.flatnonzero(item["mask"].ravel())
        eligible_scores = item["scores"]["OG-RDE"].ravel()[eligible_flat]
        selected = select_top_fraction(eligible_scores, .05)
        top_grid = np.zeros(builder.SHAPE, dtype=bool)
        top_grid.ravel()[eligible_flat[selected]] = True
        ax.contour(builder.LON_GRID, builder.LAT_GRID, top_grid.astype(float), levels=[.5],
                   colors=[gold], linewidths=1.0)
        yy, xx = np.where(item["truth"] > 0)
        ax.scatter(builder.WEST + (xx + .5) * builder.STEP, builder.SOUTH + (yy + .5) * builder.STEP,
                   s=12, facecolors="none", edgecolors=coral, lw=.75)
        for ring in state_rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#536960", lw=.22, alpha=.65)
        recall = frozen_metrics[(frozen_metrics.year == year) & (frozen_metrics.model == "OG-RDE")].iloc[0]
        ax.set(title=f"{year}: AP {recall.average_precision:.3f}; R@5% {recall.recall_at_5pct:.3f}",
               xlabel="longitude", ylabel="latitude", xlim=(builder.WEST, builder.EAST),
               ylim=(builder.SOUTH, builder.NORTH))
    fig.colorbar(image, ax=axes, fraction=.025, pad=.02, label="relative risk rank")
    fig.suptitle("Frozen OG-RDE predictions: gold = top 5%; coral = first reports", y=1.02, fontsize=10)
    fig.subplots_adjust(wspace=.22, right=.92)
    save_figure(fig, "fig6_frozen_maps")

    # Operational yield curves answer how much of the frontier a survey budget captures.
    fractions = np.linspace(.01, .25, 25)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.65))
    for name in ["Distance kernel", "Cook-2021 kernel", "Covariate hazard", "OG-RDE"]:
        annual_curves = []
        for year in FROZEN_TARGETS:
            item = frozen_predictions[year]
            y = item["truth"][item["mask"]]
            score = item["scores"][name][item["mask"]]
            annual_curves.append([recall_at_fraction(y, score, float(fraction)) for fraction in fractions])
        axes[0].plot(fractions * 100, np.mean(annual_curves, axis=0) * 100, lw=1.8,
                     color=palette.get(name, "#777777"), label=name)
    axes[0].plot([0, 25], [0, 25], color="#aaaaaa", ls="--", lw=.8, label="random ranking")
    axes[0].set(xlabel="eligible cells inspected (%)", ylabel="first reports captured (%)",
                title="Frozen survey-yield curve", xlim=(0, 25), ylim=(0, 100))
    axes[0].grid(color="#e5e9e6", lw=.5)
    axes[0].legend(frameon=False, fontsize=6.2)
    frozen_annual = frozen_metrics.groupby("model", as_index=False).agg(
        average_precision=("average_precision", "mean"),
        positives=("positives", "sum"), candidates=("candidates", "sum"),
    )
    frozen_annual["prevalence"] = frozen_annual.positives / frozen_annual.candidates
    frozen_annual["normalized_lift"] = (
        (frozen_annual.average_precision - frozen_annual.prevalence) /
        (1 - frozen_annual.prevalence)
    )
    frozen_annual = frozen_annual.sort_values("normalized_lift")
    bar_colors = [green if name == "OG-RDE" else "#8aa99a" for name in frozen_annual.model]
    axes[1].barh(frozen_annual.model, frozen_annual.normalized_lift, color=bar_colors)
    axes[1].set(xlabel="prevalence-normalized AP lift", title="Skill beyond frozen-target prevalence")
    axes[1].grid(axis="x", color="#e5e9e6", lw=.5)
    fig.tight_layout()
    save_figure(fig, "fig7_frozen_yield")

    # Agreement diagnostics distinguish shared signal from a unique model contribution.
    diagnostic_models = ["Cook-2021 kernel", "Fisher-KPP", "Climate RD", "Transport RD",
                         "Covariate hazard", "OG-RDE"]
    pooled = {}
    for name in diagnostic_models:
        pooled[name] = np.concatenate([
            frozen_predictions[year]["scores"][name][frozen_predictions[year]["mask"]]
            for year in FROZEN_TARGETS
        ])
    correlation = pd.DataFrame(pooled).corr(method="spearman")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw={"width_ratios": [1.08, .92]})
    heat = axes[0].imshow(correlation, vmin=0, vmax=1, cmap="YlGnBu")
    axes[0].set_xticks(np.arange(len(diagnostic_models)), diagnostic_models, rotation=42, ha="right", fontsize=6.2)
    axes[0].set_yticks(np.arange(len(diagnostic_models)), diagnostic_models, fontsize=6.2)
    for row in range(len(diagnostic_models)):
        for col in range(len(diagnostic_models)):
            value = correlation.iloc[row, col]
            axes[0].text(col, row, f"{value:.2f}", ha="center", va="center",
                         color="white" if value > .68 else "#24352e", fontsize=5.7)
    axes[0].set_title("Frozen score-rank agreement")
    fig.colorbar(heat, ax=axes[0], fraction=.044, pad=.03, label="Spearman correlation")
    reference = frozen_blocks[frozen_blocks.model == "OG-RDE"][["year", "block", "average_precision"]]
    deltas, labels = [], []
    for competitor in ["Cook-2021 kernel", "Covariate hazard", "Transport RD"]:
        other = frozen_blocks[frozen_blocks.model == competitor][["year", "block", "average_precision"]]
        paired = reference.merge(other, on=["year", "block"], suffixes=("_og", "_other"))
        deltas.append((paired.average_precision_og - paired.average_precision_other).to_numpy())
        labels.append(competitor)
    axes[1].boxplot(deltas, tick_labels=labels, orientation="horizontal", showfliers=False,
                    medianprops={"color": green, "linewidth": 1.5},
                    boxprops={"color": "#536960"}, whiskerprops={"color": "#8a9c94"},
                    capprops={"color": "#8a9c94"})
    axes[1].axvline(0, color="#555555", ls="--", lw=.8)
    axes[1].set(xlabel="within-block AP: OG-RDE minus comparator",
                title="Where does OG-RDE add value?")
    axes[1].grid(axis="x", color="#e5e9e6", lw=.5)
    fig.tight_layout()
    save_figure(fig, "fig8_model_agreement")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = load_data()
    metric_rows, block_rows, activation_rows, prediction_store = [], [], [], {}
    for year in [*DEVELOPMENT_TARGETS, FINAL_TARGET]:
        print(f"Evaluating target year {year}...", flush=True)
        rows, scores, mask, truth, effort = evaluate_year(data, year)
        metric_rows.extend(rows)
        block_scores = dict(scores)
        block_scores["OG-RDE"] = predict_ogrde_leave_block_out(data, year)
        block_scores["OG-RDE + reporting"] = predict_ogrde_leave_block_out(data, year, True, False)
        block_scores["OG-RDE + transport"] = predict_ogrde_leave_block_out(data, year, True, True)
        block_scores["Covariate hazard"] = predict_covariate_leave_block_out(data, year)
        block_scores["Reporting surface"] = reporting_surface_leave_block_out(data, year)
        block_rows.extend(block_metrics(data, year, block_scores, mask, truth))
        activation_rows.extend(regional_activation_metrics(year, block_scores, mask, truth))
        prediction_store[year] = {"scores": scores, "mask": mask, "truth": truth, "effort": effort}
    frozen_rows, frozen_block_rows, frozen_predictions = [], [], {}
    for year in FROZEN_TARGETS:
        print(f"Evaluating frozen target year {year}...", flush=True)
        rows, scores, mask, truth = evaluate_frozen_year(data, year)
        frozen_rows.extend(rows)
        frozen_block_rows.extend(block_metrics(data, year, scores, mask, truth))
        frozen_predictions[year] = {"scores": scores, "mask": mask, "truth": truth}
    metrics = pd.DataFrame(metric_rows)
    blocks = pd.DataFrame(block_rows)
    activation = pd.DataFrame(activation_rows)
    frozen_metrics = pd.DataFrame(frozen_rows)
    frozen_blocks = pd.DataFrame(frozen_block_rows)
    development_blocks = blocks[blocks.year.isin(DEVELOPMENT_TARGETS)].copy()
    summary = bootstrap_summary(development_blocks)
    comparisons = paired_block_comparisons(development_blocks)
    annual_comparisons = annual_paired_comparisons(metrics)
    frozen_summary = bootstrap_summary(frozen_blocks)
    frozen_comparisons = paired_block_comparisons(frozen_blocks)
    endpoint = endpoint_comparison(data)
    sensitivity = numerical_sensitivity(data)
    parameter_checks = parameter_sensitivity(data)
    metrics.to_csv(RESULTS / "temporal_metrics.csv", index=False)
    blocks.to_csv(RESULTS / "spatial_block_metrics.csv", index=False)
    summary.to_csv(RESULTS / "bootstrap_summary.csv", index=False)
    comparisons.to_csv(RESULTS / "paired_comparisons.csv", index=False)
    annual_comparisons.to_csv(RESULTS / "annual_paired_comparisons.csv", index=False)
    endpoint.to_csv(RESULTS / "endpoint_comparison.csv", index=False)
    activation.to_csv(RESULTS / "regional_activation.csv", index=False)
    sensitivity.to_csv(RESULTS / "numerical_sensitivity.csv", index=False)
    parameter_checks.to_csv(RESULTS / "parameter_sensitivity.csv", index=False)
    frozen_metrics.to_csv(RESULTS / "frozen_temporal_metrics.csv", index=False)
    frozen_blocks.to_csv(RESULTS / "frozen_block_metrics.csv", index=False)
    frozen_summary.to_csv(RESULTS / "frozen_bootstrap_summary.csv", index=False)
    frozen_comparisons.to_csv(RESULTS / "frozen_paired_comparisons.csv", index=False)

    final_metrics = metrics[metrics.year == FINAL_TARGET].sort_values("average_precision", ascending=False)
    manifest = {
        "endpoint": "first-reported cells outside the prior-year reported range",
        "developmentTargets": DEVELOPMENT_TARGETS,
        "frozenTemporalReplay": {
            "trainingTransitions": "2018-2023",
            "trainingEndExclusive": FROZEN_TRAINING_END,
            "targets": FROZEN_TARGETS,
            "stateAssimilation": "annual event-date range updated before each target; coefficients and feature specification fixed",
            "status": "post-hoc lockbox emulation, not preregistered or independent-species validation",
        },
        "interimMonitoring": "2026 Jan-Jul retrospective slice",
        "grid": {"shape": builder.SHAPE, "stepDegrees": builder.STEP},
        "recordAccounting": data.accounting,
        "featureNames": FEATURE_NAMES,
        "modelParameters": MODEL_PARAMETERS,
        "bootstrapReplicates": 2500,
        "spatialSummaryScope": "development targets 2022-2025; every learned variant leaves each 2-degree block out; geographic-block bootstrap retains repeated years; interim 2026 is separate",
        "interimMonitoringMetrics": final_metrics.to_dict(orient="records"),
        "summary": summary.to_dict(orient="records"),
        "pairedComparisons": comparisons.to_dict(orient="records"),
        "annualPairedComparisons": annual_comparisons.to_dict(orient="records"),
        "matchedEndpointComparison": endpoint.to_dict(orient="records"),
        "numericalSensitivity": sensitivity.to_dict(orient="records"),
        "parameterSensitivity": parameter_checks.to_dict(orient="records"),
        "frozenTemporalMetrics": frozen_metrics.to_dict(orient="records"),
        "frozenBootstrapSummary": frozen_summary.to_dict(orient="records"),
        "frozenPairedComparisons": frozen_comparisons.to_dict(orient="records"),
    }
    (RESULTS / "study_summary.json").write_text(json.dumps(manifest, indent=2))
    (RESULTS / "data_provenance.json").write_text(json.dumps(data_provenance(data), indent=2))
    included_occurrence_manifest(data).to_csv(
        RESULTS / "included_occurrences.csv.gz", index=False,
        compression={"method": "gzip", "mtime": 0},
    )
    np.savez_compressed(
        RESULTS / "prediction_grids.npz",
        **{
            **{f"rolling_{year}_{name.replace(' ', '_')}": grid
               for year, item in prediction_store.items() for name, grid in item["scores"].items()},
            **{f"frozen_{year}_{name.replace(' ', '_')}": grid
               for year, item in frozen_predictions.items() for name, grid in item["scores"].items()},
        },
    )
    make_figures(data, metrics, summary, prediction_store, endpoint, sensitivity,
                 frozen_metrics, frozen_summary, frozen_predictions, frozen_blocks)
    export_frozen_benchmark(frozen_metrics, frozen_summary, frozen_comparisons, frozen_predictions)
    print("\nTemporal metrics:")
    print(metrics.pivot(index="model", columns="year", values="average_precision").round(3).to_string())
    print("\nSpatial-block bootstrap summary:")
    print(summary.round(3).to_string(index=False))
    print("\nFrozen temporal replay:")
    print(frozen_metrics.pivot(index="model", columns="year", values="average_precision").round(3).to_string())


if __name__ == "__main__":
    main()
