#!/usr/bin/env python3
"""Build LanternTrace's diffusion-model ensemble and lightweight display frames.

The model is intentionally transparent: every candidate contains spatial diffusion.
More elaborate candidates add logistic growth, habitat resistance, anisotropy,
transport jumps, and a small learned residual. Public occurrence records are used
for retrospective ranking, not treated as abundance or confirmed absence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import math
import pathlib
import random
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
from contourpy import contour_generator
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / ".model-cache"
GENERATED = ROOT / "generated"
OBSERVATIONS = GENERATED / "observations.js"
OUTPUT = GENERATED / "model-results.js"

WEST, EAST, SOUTH, NORTH, STEP = -82.0, -68.0, 37.0, 47.0, 0.2
LONS = np.arange(WEST + STEP / 2, EAST, STEP)
LATS = np.arange(SOUTH + STEP / 2, NORTH, STEP)
LON_GRID, LAT_GRID = np.meshgrid(LONS, LATS)
SHAPE = LON_GRID.shape
YEARS = list(range(2014, 2026))
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RNG = np.random.default_rng(73491)
STATE_BOUNDARY_URL = "https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_500k.zip"


def download(url: str, target: pathlib.Path) -> pathlib.Path:
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "curl", "-sS", "--fail", "--retry", "5", "--retry-all-errors", "--max-time", "180",
        "-H", "User-Agent: LanternTrace research prototype", "-o", str(target), url,
    ], check=True)
    return target


def load_observations() -> list[list]:
    text = OBSERVATIONS.read_text()
    prefix = "window.LanternTraceObservations = "
    if not text.startswith(prefix):
        raise RuntimeError(f"Unexpected observation bundle format: {OBSERVATIONS}")
    return json.loads(text[len(prefix):].rstrip(";\n"))["observations"]


def load_worldclim() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    elev_zip = download(
        "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_elev.zip",
        CACHE / "wc2.1_10m_elev.zip",
    )
    bio_zip = download(
        "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_bio.zip",
        CACHE / "wc2.1_10m_bio.zip",
    )

    def sample_tif(archive_path: pathlib.Path, member: str) -> np.ndarray:
        with zipfile.ZipFile(archive_path) as archive:
            image = Image.open(io.BytesIO(archive.read(member)))
            raster = np.asarray(image, dtype=float)
        height, width = raster.shape
        xs = np.clip(((LON_GRID + 180) / 360 * width).astype(int), 0, width - 1)
        ys = np.clip(((90 - LAT_GRID) / 180 * height).astype(int), 0, height - 1)
        return raster[ys, xs]

    elevation = sample_tif(elev_zip, "wc2.1_10m_elev.tif")
    climate = {name: sample_tif(bio_zip, f"wc2.1_10m_{name}.tif") for name in ("bio_1", "bio_3", "bio_9", "bio_19")}
    return elevation, climate


def fetch_host_records() -> list[list[float]]:
    target = CACHE / "ailanthus-altissima-ne.json"
    if target.exists():
        return json.loads(target.read_text())
    def fetch_page(offset: int) -> dict:
        params = urllib.parse.urlencode({
            "taxon_key": "3190653", "has_coordinate": "true", "has_geospatial_issue": "false",
            "geometry": f"POLYGON(({WEST} {SOUTH},{EAST} {SOUTH},{EAST} {NORTH},{WEST} {NORTH},{WEST} {SOUTH}))",
            "limit": "300", "offset": str(offset),
        })
        response = subprocess.run([
            "curl", "-sS", "--fail", "--retry", "2", "--retry-all-errors", "--max-time", "45",
            "-H", "User-Agent: LanternTrace research prototype",
            f"https://api.gbif.org/v1/occurrence/search?{params}",
        ], check=True, capture_output=True)
        return json.loads(response.stdout)

    first_page = fetch_page(0)
    # GBIF's polygon query is expensive. A deterministic 3,600-record sample is
    # sufficient at this 0.2-degree display/model resolution and keeps rebuilds polite.
    maximum = min(int(first_page.get("count", 0)), 3600)
    offsets = list(range(300, maximum, 300))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        pages = [first_page, *executor.map(fetch_page, offsets)]
    records: list[list[float]] = []
    for page in pages:
        for record in page.get("results", []):
            lng, lat = record.get("decimalLongitude"), record.get("decimalLatitude")
            if isinstance(lng, (int, float)) and isinstance(lat, (int, float)):
                records.append([float(lng), float(lat)])
    target.write_text(json.dumps(records))
    return records


def grid_points(points: list[list[float]]) -> np.ndarray:
    grid = np.zeros(SHAPE, dtype=float)
    for lng, lat, *_ in points:
        x, y = int((lng - WEST) / STEP), int((lat - SOUTH) / STEP)
        if 0 <= x < SHAPE[1] and 0 <= y < SHAPE[0]:
            grid[y, x] += 1
    return grid


def distance_to_segments(lines: list[list[list[float]]]) -> np.ndarray:
    output = np.full(SHAPE, 99.0)
    for line in lines:
        for start, end in zip(line, line[1:]):
            ax, ay = start
            bx, by = end
            dx, dy = bx - ax, by - ay
            denom = dx * dx + dy * dy or 1
            t = np.clip(((LON_GRID - ax) * dx + (LAT_GRID - ay) * dy) / denom, 0, 1)
            px, py = ax + t * dx, ay + t * dy
            km = np.hypot((LON_GRID - px) * 85, (LAT_GRID - py) * 111)
            output = np.minimum(output, km)
    return output


def points_in_ring(ring: np.ndarray) -> np.ndarray:
    """Vectorized even-odd point-in-polygon test at model cell centers."""
    inside = np.zeros(SHAPE, dtype=bool)
    x, y = LON_GRID, LAT_GRID
    for first, second in zip(ring, np.roll(ring, -1, axis=0)):
        x1, y1 = first[:2]
        x2, y2 = second[:2]
        crossing = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1)
        inside ^= crossing
    return inside


def load_us_state_geometry() -> tuple[np.ndarray, list[np.ndarray]]:
    """Return the 2025 Census state mask and NE boundary rings."""
    archive_path = download(STATE_BOUNDARY_URL, CACHE / "cb_2025_us_state_500k.zip")
    with zipfile.ZipFile(archive_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".kml"))
        root = ET.fromstring(archive.read(member))
    namespace = {"k": "http://www.opengis.net/kml/2.2"}
    mask = np.zeros(SHAPE, dtype=bool)
    boundaries: list[np.ndarray] = []
    for polygon in root.findall(".//k:Polygon", namespace):
        outer_node = polygon.find("k:outerBoundaryIs/k:LinearRing/k:coordinates", namespace)
        if outer_node is None or not outer_node.text:
            continue
        outer = np.asarray([[float(value) for value in token.split(",")[:2]] for token in outer_node.text.split()])
        if outer[:, 0].max() < WEST or outer[:, 0].min() > EAST or outer[:, 1].max() < SOUTH or outer[:, 1].min() > NORTH:
            continue
        local = points_in_ring(outer)
        for inner_node in polygon.findall("k:innerBoundaryIs/k:LinearRing/k:coordinates", namespace):
            if inner_node.text:
                inner = np.asarray([[float(value) for value in token.split(",")[:2]] for token in inner_node.text.split()])
                local &= ~points_in_ring(inner)
        mask |= local
        boundaries.append(outer)
    return mask, boundaries


def build_covariates() -> dict[str, np.ndarray]:
    elevation, climate_raw = load_worldclim()
    census_mask, _ = load_us_state_geometry()
    land = (elevation > -1000) & census_mask
    elevation = np.where(land, np.maximum(elevation, 0), 0)
    slope = np.hypot(*np.gradient(elevation)) / 220

    host_counts = grid_points(fetch_host_records())
    host = np.log1p(gaussian_filter(host_counts, 2.2))
    host = host / max(float(host.max()), 1)

    cities = [
        (-75.16, 39.95, 1.0), (-74.01, 40.71, 1.0), (-77.04, 38.90, .9),
        (-71.06, 42.36, .75), (-80.0, 40.44, .6), (-78.88, 42.89, .5),
        (-76.61, 39.29, .55), (-71.61, 42.99, .35), (-73.76, 42.65, .35),
    ]
    urban = np.zeros(SHAPE)
    for lng, lat, weight in cities:
        distance2 = ((LON_GRID - lng) * np.cos(np.radians(lat))) ** 2 + (LAT_GRID - lat) ** 2
        urban += weight * np.exp(-distance2 / (2 * .7 ** 2))
    urban /= urban.max()

    corridors = [
        [[-75.16, 39.95], [-74.64, 40.22], [-74.01, 40.71], [-73.76, 42.65]],
        [[-77.04, 38.9], [-76.31, 40.04], [-75.47, 40.34], [-74.01, 40.71], [-71.06, 42.36]],
        [[-80.0, 40.44], [-78.9, 40.44], [-76.89, 40.27], [-75.16, 39.95]],
        [[-75.16, 39.95], [-77.04, 38.9], [-80.19, 32.08]],
        [[-76.49, 42.44], [-75.76, 43.15], [-73.76, 42.65], [-71.54, 43.21]],
    ]
    corridor = np.exp(-distance_to_segments(corridors) / 28)

    bio1 = climate_raw["bio_1"]
    bio9 = climate_raw["bio_9"]
    if np.nanmedian(np.abs(bio1[land])) > 50:
        bio1, bio9 = bio1 / 10, bio9 / 10
    dry_temp = np.exp(-((bio9 - 0.0) / 8.0) ** 2)
    annual_temp = np.exp(-((bio1 - 11.0) / 8.0) ** 2)
    isotherm = np.exp(-((climate_raw["bio_3"] - 31) / 14) ** 2)
    precipitation = climate_raw["bio_19"]
    precipitation = np.clip(precipitation / max(np.percentile(precipitation[land], 90), 1), 0, 1)
    climate = np.clip(.42 * dry_temp + .30 * annual_temp + .16 * isotherm + .12 * precipitation, 0, 1)
    elevation_barrier = np.exp(-np.maximum(elevation - 500, 0) / 900)
    slope_barrier = np.exp(-np.maximum(slope - .25, 0) * 2.4)
    return {
        "land": land.astype(float), "elevation": np.clip(elevation / 1800, 0, 1),
        "slope": np.clip(slope, 0, 1), "host": host, "climate": climate,
        "corridor": corridor, "urban": urban, "elevation_barrier": elevation_barrier,
        "slope_barrier": slope_barrier,
    }


def observation_history(records: list[list]) -> dict[int, np.ndarray]:
    first_year = np.full(SHAPE, 9999, dtype=int)
    counts = np.zeros(SHAPE)
    for record in records:
        try:
            lng, lat, date = float(record[0]), float(record[1]), str(record[2])
            year = int(date[:4])
        except (ValueError, TypeError):
            continue
        if not 2014 <= year <= 2026:
            continue
        x, y = int((lng - WEST) / STEP), int((lat - SOUTH) / STEP)
        if 0 <= x < SHAPE[1] and 0 <= y < SHAPE[0]:
            first_year[y, x] = min(first_year[y, x], year)
            counts[y, x] += 1
    return {year: (first_year <= year).astype(float) for year in YEARS}, counts


def monthly_observation_history(records: list[list]) -> dict[tuple[int, int], np.ndarray]:
    """Cumulative true-report cells for evidence-assimilating backcast playback."""
    first_period = np.full(SHAPE, 999999, dtype=int)
    for record in records:
        try:
            lng, lat, date = float(record[0]), float(record[1]), str(record[2])
            year = int(date[:4])
            month = int(date[5:7]) if len(date) >= 7 and date[4] == "-" else 1
        except (ValueError, TypeError):
            continue
        if not 2014 <= year <= 2025 or not 1 <= month <= 12:
            continue
        x, y = int((lng - WEST) / STEP), int((lat - SOUTH) / STEP)
        if 0 <= x < SHAPE[1] and 0 <= y < SHAPE[0]:
            first_period[y, x] = min(first_period[y, x], year * 12 + month - 1)
    return {
        (year, month): (first_period <= year * 12 + month).astype(float)
        for year in range(2018, 2026)
        for month in range(12)
    }


def no_flux_neighbors(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return cardinal neighbors with zero-normal-gradient domain edges."""
    padded = np.pad(grid, 1, mode="edge")
    return (
        padded[:-2, 1:-1], padded[2:, 1:-1],
        padded[1:-1, :-2], padded[1:-1, 2:],
    )


def neighborhood(grid: np.ndarray) -> np.ndarray:
    return sum(no_flux_neighbors(grid)) / 4


def laplacian(grid: np.ndarray) -> np.ndarray:
    return neighborhood(grid) - grid


def diffusion_divergence(grid: np.ndarray, conductivity: np.ndarray) -> np.ndarray:
    """Finite-volume div(k grad u), metric-adjusted with no-flux edges."""
    neighbors = no_flux_neighbors(grid)
    conductivities = no_flux_neighbors(conductivity)
    # Harmonic face conductivity makes an impermeable zero-conductivity mask
    # exactly no-flux instead of leaking mass into a cell that is later clipped.
    fluxes = [2 * conductivity * local_k / (conductivity + local_k + 1e-15) * (local_u - grid)
              for local_u, local_k in zip(neighbors, conductivities)]
    if grid.shape == SHAPE:
        dy_km = STEP * 111.0
        dx_km = STEP * 111.0 * np.cos(np.radians(LAT_GRID))
        reference_km = 20.0
        weights = [
            np.full(SHAPE, (reference_km / dy_km) ** 2),
            np.full(SHAPE, (reference_km / dy_km) ** 2),
            (reference_km / dx_km) ** 2,
            (reference_km / dx_km) ** 2,
        ]
        fluxes = [flux * weight for flux, weight in zip(fluxes, weights)]
    return sum(fluxes) / 4


class TinyResidualNet:
    """One-hidden-layer neural residual, trained with deterministic weighted Adam."""

    def __init__(self, inputs: int, hidden: int = 10):
        self.w1 = RNG.normal(0, .18, (inputs, hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = RNG.normal(0, .18, (hidden, 1))
        self.b2 = np.zeros(1)

    def predict(self, x: np.ndarray) -> np.ndarray:
        h = np.tanh(x @ self.w1 + self.b1)
        logits = np.clip(h @ self.w2 + self.b2, -12, 12)
        return 1 / (1 + np.exp(-logits[:, 0]))

    def fit(self, x: np.ndarray, y: np.ndarray, epochs: int = 280) -> list[float]:
        moments = [np.zeros_like(p) for p in (self.w1, self.b1, self.w2, self.b2)]
        velocities = [np.zeros_like(p) for p in (self.w1, self.b1, self.w2, self.b2)]
        losses = []
        # Moderate weighting preserves calibration; unbounded class balancing made
        # the residual light up nearly every pseudo-absence in early experiments.
        positive_weight = min(2.0, max(1.0, math.sqrt((len(y) - y.sum()) / max(y.sum(), 1))))
        for epoch in range(1, epochs + 1):
            h = np.tanh(x @ self.w1 + self.b1)
            logits = np.clip(h @ self.w2 + self.b2, -12, 12)
            p = 1 / (1 + np.exp(-logits))
            weights = np.where(y[:, None] > .5, positive_weight, 1.0)
            dz = (p - y[:, None]) * weights / weights.sum()
            gradients = [x.T @ ((dz @ self.w2.T) * (1 - h * h)), ((dz @ self.w2.T) * (1 - h * h)).sum(0), h.T @ dz, dz.sum(0)]
            for index, (parameter, gradient) in enumerate(zip((self.w1, self.b1, self.w2, self.b2), gradients)):
                moments[index] = .9 * moments[index] + .1 * gradient
                velocities[index] = .999 * velocities[index] + .001 * gradient * gradient
                parameter -= .025 * (moments[index] / (1 - .9 ** epoch)) / (np.sqrt(velocities[index] / (1 - .999 ** epoch)) + 1e-8)
            if epoch % 40 == 0:
                losses.append(float(-(weights * (y[:, None] * np.log(p + 1e-8) + (1 - y[:, None]) * np.log(1 - p + 1e-8))).sum() / weights.sum()))
        return losses


FEATURE_NAMES = ["density", "neighbor density", "diffusion residual", "host", "climate", "corridor", "urban", "elevation", "slope", "latitude", "longitude"]


def feature_matrix(u: np.ndarray, cov: dict[str, np.ndarray]) -> np.ndarray:
    channels = [
        u, neighborhood(u), laplacian(u), cov["host"], cov["climate"], cov["corridor"], cov["urban"],
        cov["elevation"], cov["slope"], (LAT_GRID - SOUTH) / (NORTH - SOUTH), (LON_GRID - WEST) / (EAST - WEST),
    ]
    return np.column_stack([channel.ravel() for channel in channels])


def train_network(history: dict[int, np.ndarray], cov: dict[str, np.ndarray]) -> tuple[TinyResidualNet, list[float]]:
    xs, ys = [], []
    for year in range(2014, 2022):
        x = feature_matrix(gaussian_filter(history[year], .8), cov)
        y = history[year + 1].ravel()
        positives = np.flatnonzero(y > .5)
        negatives = np.flatnonzero(y <= .5)
        keep_negatives = RNG.choice(negatives, min(len(negatives), max(600, len(positives) * 3)), replace=False)
        keep = np.concatenate([positives, keep_negatives])
        xs.append(x[keep]); ys.append(y[keep])
    network = TinyResidualNet(len(FEATURE_NAMES))
    losses = network.fit(np.vstack(xs), np.concatenate(ys))
    return network, losses


VARIANTS = [
    ("D01", "Isotropic diffusion", {}),
    ("D02", "Fisher–KPP growth", {"growth": True}),
    ("D03", "Anisotropic northeast drift", {"growth": True, "advection": True}),
    ("D04", "Host-weighted growth", {"growth": True, "host": True}),
    ("D05", "Climate-weighted growth", {"growth": True, "climate": True}),
    ("D06", "Elevation resistance", {"growth": True, "elevation": True}),
    ("D07", "Slope resistance", {"growth": True, "slope": True}),
    ("D08", "Land/water barrier", {"growth": True, "water": True}),
    ("D09", "Corridor anisotropy", {"growth": True, "corridor": True}),
    ("D10", "Human-footprint growth", {"growth": True, "urban": True}),
    ("D11", "Stratified jump diffusion", {"growth": True, "jumps": True}),
    ("D12", "Seasonal diffusion", {"growth": True, "seasonal": True}),
    ("D13", "Host + climate", {"growth": True, "host": True, "climate": True}),
    ("D14", "Habitat-resistance diffusion", {"growth": True, "host": True, "climate": True, "elevation": True, "slope": True, "water": True}),
    ("D15", "Transport-coupled diffusion", {"growth": True, "corridor": True, "urban": True, "jumps": True}),
    ("D16", "Full mechanistic physics", {"growth": True, "host": True, "climate": True, "elevation": True, "slope": True, "water": True, "corridor": True, "urban": True, "jumps": True, "seasonal": True, "advection": True}),
    ("D17", "Learned physics residual", {"growth": True, "learned": True}),
    ("D18", "Learned habitat physics", {"growth": True, "host": True, "climate": True, "elevation": True, "slope": True, "water": True, "learned": True}),
    ("D19", "Learned transport physics", {"growth": True, "corridor": True, "urban": True, "jumps": True, "learned": True}),
    ("D20", "Full physics-informed hybrid", {"growth": True, "host": True, "climate": True, "elevation": True, "slope": True, "water": True, "corridor": True, "urban": True, "jumps": True, "seasonal": True, "advection": True, "learned": True}),
]


def advance(u: np.ndarray, flags: dict, cov: dict[str, np.ndarray], network: TinyResidualNet, month: int,
            time_step_months: float = 1.0, parameter_scales: dict[str, float] | None = None) -> np.ndarray:
    scales = {"diffusion": 1.0, "growth": 1.0, "jump": 1.0, "advection": 1.0, **(parameter_scales or {})}
    season = .22 + .78 * max(0, math.sin((month - 2) / 12 * math.pi)) ** 1.4 if flags.get("seasonal") else 1.0
    resistance = np.ones(SHAPE)
    if flags.get("elevation"): resistance *= cov["elevation_barrier"]
    if flags.get("slope"): resistance *= cov["slope_barrier"]
    # Even non-barrier ablations cannot create risk over open water. The water
    # variant makes the coastline strictly impermeable; other variants retain a
    # small coastal conductance to avoid encoding a hard boundary by default.
    resistance *= cov["land"] if flags.get("water") else (.05 + .95 * cov["land"])
    conductivity = resistance * (1 + (.75 * cov["corridor"] if flags.get("corridor") else 0))
    flow = scales["diffusion"] * .19 * season * diffusion_divergence(u, conductivity)
    if flags.get("advection"):
        south, _, west, _ = no_flux_neighbors(u)
        flow += scales["advection"] * (.018 * (south - u) + .012 * (west - u))
    growth_suitability = np.ones(SHAPE)
    if flags.get("host"): growth_suitability *= .28 + .72 * cov["host"]
    if flags.get("climate"): growth_suitability *= .30 + .70 * cov["climate"]
    if flags.get("urban"): growth_suitability *= .78 + .35 * cov["urban"]
    growth = (scales["growth"] * .13 * season * growth_suitability * u * (1 - u)) if flags.get("growth") else 0
    result = u + time_step_months * (flow + growth)
    if flags.get("jumps"):
        source = gaussian_filter(u * (.25 + .75 * cov["corridor"]) * (.35 + .65 * cov["urban"]), 4.0)
        result += time_step_months * scales["jump"] * .035 * source * (.2 + .8 * cov["corridor"]) * (.25 + .75 * cov["host"])
    if flags.get("learned"):
        learned = network.predict(feature_matrix(np.clip(result, 0, 1), cov)).reshape(SHAPE)
        # Physics-informed residual: the network may correct an existing front,
        # but cannot create unconstrained occupancy in distant empty cells.
        frontier_gate = np.clip(gaussian_filter(result, 1.15) * 2.2, 0, 1)
        # The target is one year ahead while integration is monthly, so the
        # learned correction is injected at roughly one twelfth strength.
        result += time_step_months * .0075 * (learned - result) * frontier_gate
    result *= cov["land"]
    return np.clip(result, 0, 1)


def rollout(start: np.ndarray, flags: dict, cov: dict[str, np.ndarray], network: TinyResidualNet, steps: int,
            start_month: int = 0, time_step_months: float = 1.0,
            parameter_scales: dict[str, float] | None = None) -> list[np.ndarray]:
    states = []
    u = start.copy()
    for step_index in range(steps):
        month = int(start_month + step_index * time_step_months) % 12
        u = advance(u, flags, cov, network, month, time_step_months, parameter_scales)
        states.append(u.copy())
    return states


def metrics(
    prediction: np.ndarray,
    truth: np.ndarray,
    threshold: float = .32,
    reporting_effort: np.ndarray | None = None,
) -> dict[str, float]:
    pred = prediction >= threshold
    actual = truth > .5
    effort = np.ones_like(prediction) if reporting_effort is None else np.clip(reporting_effort, .15, 1)
    # A missing report is only a pseudo-absence. Penalize a predicted presence
    # less where our coarse observation-effort proxy is weak.
    tp = float(np.logical_and(pred, actual).sum())
    fp = float(effort[np.logical_and(pred, ~actual)].sum())
    fn = float(np.logical_and(~pred, actual).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    score_weights = np.where(actual, 1, effort)
    brier = float(np.average((prediction - truth) ** 2, weights=score_weights))
    return {"precision": precision, "recall": recall, "f1": f1, "brier": brier}


def evaluate_variants(history: dict[int, np.ndarray], cov: dict[str, np.ndarray], network: TinyResidualNet) -> list[dict]:
    results = []
    reporting_effort = .25 + .75 * cov["urban"]
    for variant_id, name, flags in VARIANTS:
        predictions = []
        for year in range(2021, 2025):
            start = np.maximum(history[year], gaussian_filter(history[year], .75) * .72)
            prediction = rollout(start, flags, cov, network, 12)[-1]
            predictions.append((prediction, history[year + 1]))
        candidates = []
        for threshold in np.arange(.20, .701, .02):
            yearly_metrics = [metrics(prediction, truth, float(threshold), reporting_effort) for prediction, truth in predictions]
            mean = {key: float(np.mean([item[key] for item in yearly_metrics])) for key in yearly_metrics[0]}
            score = 100 * (.48 * mean["recall"] + .27 * mean["f1"] + .15 * mean["precision"] + .10 * (1 - mean["brier"]))
            candidates.append((score, float(threshold), mean))
        score, threshold, mean = max(candidates, key=lambda item: item[0])
        # Presence-only backtesting rewards recovery of future reports; pseudo-absence
        # penalties are reduced where the observation-effort proxy is weak.
        results.append({
            "id": variant_id, "name": name, "features": [key for key, value in flags.items() if value],
            "score": round(score, 1), "recall": round(mean["recall"], 3), "precision": round(mean["precision"], 3),
            "f1": round(mean["f1"], 3), "brier": round(mean["brier"], 4), "threshold": round(threshold, 2), "rank": 0,
        })
    results.sort(key=lambda item: (-item["score"], item["id"]))
    for rank, result in enumerate(results, 1): result["rank"] = rank
    return results


def grid_geometry(values: np.ndarray, threshold: float) -> dict:
    # The PDE stays on its native 0.2° grid. Only the display boundary is
    # interpolated from a lightly smoothed scalar field, avoiding blocky cell
    # hulls without pretending the underlying simulation has finer resolution.
    surface = gaussian_filter(values, 1.15)
    if float(surface.max()) < threshold:
        return {"type": "MultiPolygon", "coordinates": []}
    padded = np.pad(surface, 1, mode="constant", constant_values=0)
    xs = WEST - STEP / 2 + np.arange(SHAPE[1] + 2) * STEP
    ys = SOUTH - STEP / 2 + np.arange(SHAPE[0] + 2) * STEP
    contour = contour_generator(x=xs, y=ys, z=padded)
    candidates = []
    for line in contour.lines(threshold):
        if len(line) < 4:
            continue
        if not np.allclose(line[0], line[-1]):
            line = np.vstack([line, line[0]])
        area = .5 * abs(float(np.dot(line[:-1, 0], line[1:, 1]) - np.dot(line[1:, 0], line[:-1, 1])))
        ring = [[round(float(x), 3), round(float(y), 3)] for x, y in line]
        candidates.append((area, ring))
    largest_area = max((area for area, _ in candidates), default=0)
    minimum_area = max(.12, largest_area * .012)
    polygons = [[ring] for area, ring in candidates if area >= minimum_area]
    return {"type": "MultiPolygon", "coordinates": polygons}


def frame_payload(state: np.ndarray, threshold: float, period: str, include_range: bool) -> dict:
    uncertainty_threshold = max(.08, threshold * .4)
    occupied = int((state >= threshold).sum())
    uncertain = int((state >= uncertainty_threshold).sum())
    return {
        "period": period,
        "frontGeometry": grid_geometry(state, threshold),
        "uncertaintyGeometry": grid_geometry(state, uncertainty_threshold) if include_range else {"type": "MultiPolygon", "coordinates": []},
        "occupiedCells": occupied,
        "uncertainCells": uncertain,
        "meanDensity": round(float(state.mean()), 4),
    }


def build_backcast_frames(
    flags: dict,
    monthly_history: dict[tuple[int, int], np.ndarray],
    cov: dict[str, np.ndarray],
    network: TinyResidualNet,
    threshold: float,
) -> list[dict]:
    observed = monthly_history[(2018, 11)]
    state = np.maximum(observed, gaussian_filter(observed, .82) * .72)
    frames = []
    for year in range(2019, 2026):
        for month in range(12):
            state = advance(state, flags, cov, network, month)
            observed = monthly_history[(year, month)]
            # Sequential data assimilation: true reports anchor the field while
            # the candidate's physics controls growth between and around them.
            state = np.maximum(state, observed * .96)
            state = np.maximum(state, gaussian_filter(observed, .72) * .68)
            frames.append(frame_payload(state, threshold, f"{year} {MONTHS[month]}", False))
    return frames


def build_forecast_frames(flags: dict, history: dict[int, np.ndarray], cov: dict[str, np.ndarray], network: TinyResidualNet, threshold: float) -> list[dict]:
    start = np.maximum(history[2025], gaussian_filter(history[2025], .8) * .74)
    states = rollout(start, flags, cov, network, 60)
    return [frame_payload(state, threshold, f"{2026 + index // 12} {MONTHS[index % 12]}", True) for index, state in enumerate(states)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not OBSERVATIONS.exists():
        raise SystemExit("Run `npm run data:gbif` before building the model ensemble.")
    records = load_observations()
    cov = build_covariates()
    history, counts = observation_history(records)
    monthly_history = monthly_observation_history(records)
    network, losses = train_network(history, cov)
    variants = evaluate_variants(history, cov, network)
    top_ids = [item["id"] for item in variants[:5]]
    flags_by_id = {variant_id: flags for variant_id, _, flags in VARIANTS}
    ranking_by_id = {item["id"]: item for item in variants}
    models = {
        variant_id: {
            "backcastFrames": build_backcast_frames(flags_by_id[variant_id], monthly_history, cov, network, ranking_by_id[variant_id]["threshold"]),
            "forecastFrames": build_forecast_frames(flags_by_id[variant_id], history, cov, network, ranking_by_id[variant_id]["threshold"]),
        }
        for variant_id in top_ids
    }
    payload = {
        "metadata": {
            "generatedAt": "2026-08-09", "grid": {"west": WEST, "east": EAST, "south": SOUTH, "north": NORTH, "stepDegrees": STEP},
            "equation": "∂u/∂t = ∇·(D(x,t)∇u) − v·∇u + r(x,t)u(1−u) + J(u,x) + εθ(u,x)",
            "trainingWindow": "2014–2021", "backtestWindow": "2021–2025", "projectionWindow": "2026–2030",
            "playbackWindow": "2019–2025 monthly evidence-assimilating backcasts",
            "observationWarning": "Presence-only public reports; unreported cells are pseudo-absences, not confirmed absences. Urban-node proximity is used only as a coarse reporting-effort proxy.",
            "selectionMetric": "0.48 recall + 0.27 F1 + 0.15 effort-adjusted pseudo-absence precision + 0.10 (1 − effort-adjusted Brier)",
            "network": {"inputs": FEATURE_NAMES, "hiddenUnits": 10, "trainingLoss": [round(value, 4) for value in losses]},
            "covariates": ["GBIF Ailanthus occurrences", "WorldClim 2.1 elevation", "WorldClim 2.1 bioclimatic variables 1/3/9/19", "major transport corridor proximity", "urban-node proximity", "urban-node reporting-effort proxy", "land/water mask"],
            "recordsUsed": int(counts.sum()), "hostRecordsUsed": int(len(fetch_host_records())), "candidateCount": len(VARIANTS),
        },
        "variants": variants, "topFive": top_ids, "defaultModel": top_ids[0], "models": models,
    }
    if args.verify:
        assert len(variants) == 20 and len(top_ids) == 5
        assert all(len(models[model_id]["backcastFrames"]) == 84 for model_id in top_ids)
        assert all(len(models[model_id]["forecastFrames"]) == 60 for model_id in top_ids)
        assert all(item["score"] >= variants[-1]["score"] for item in variants[:5])
        if OUTPUT.exists():
            existing = OUTPUT.read_text()
            assert existing.startswith("window.LanternTraceModels = ")
        print(f"Verified 20 candidates, 5 ranked models, 420 backcast + 300 forecast frames; leader {top_ids[0]}.")
        return
    GENERATED.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("window.LanternTraceModels = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.1f} KiB)")
    for item in variants[:5]:
        print(f"#{item['rank']} {item['id']} {item['name']}: {item['score']:.1f} (recall {item['recall']:.3f}, F1 {item['f1']:.3f})")


if __name__ == "__main__":
    main()
