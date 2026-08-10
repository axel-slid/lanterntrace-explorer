#!/usr/bin/env python3
"""Regression tests for the research benchmark's critical safeguards."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


builder = load_module("lanterntrace_builder_test", ROOT / "scripts" / "build-diffusion-model.py")
study = load_module("lanterntrace_study_test", ROOT / "research" / "run_sota_study.py")


class NumericalBoundaryTests(unittest.TestCase):
    def test_uniform_field_has_zero_no_flux_laplacian(self):
        field = np.ones((7, 9))
        self.assertTrue(np.allclose(builder.laplacian(field), 0))

    def test_opposite_edges_do_not_wrap(self):
        field = np.zeros((7, 9))
        field[3, 0] = 1
        self.assertEqual(builder.neighborhood(field)[3, -1], 0)

    def test_constant_conductivity_matches_no_flux_laplacian(self):
        rng = np.random.default_rng(73491)
        field = rng.random((7, 9))
        self.assertTrue(np.allclose(builder.diffusion_divergence(field, np.ones_like(field)), builder.laplacian(field)))

    def test_internal_zero_conductivity_boundary_is_no_flux(self):
        field = np.zeros((7, 9))
        field[3, 3] = 1
        conductivity = np.ones_like(field)
        conductivity[:, 4] = 0
        divergence = builder.diffusion_divergence(field, conductivity)
        self.assertTrue(np.allclose(divergence[:, 4], 0))
        self.assertAlmostEqual(float(divergence.sum()), 0.0, places=12)


class EndpointTests(unittest.TestCase):
    def test_top_fraction_ties_use_lower_cell_index(self):
        labels = np.array([1, 0, 0, 0])
        tied_scores = np.array([1.0, 1.0, 0.0, 0.0])
        self.assertEqual(study.select_top_fraction(tied_scores, .25).tolist(), [0])
        self.assertEqual(study.recall_at_fraction(labels, tied_scores, .25), 1.0)

        mask = np.ones((2, 2), dtype=bool)
        ranked = study.percentile_grid(tied_scores.reshape(2, 2), mask).ravel()
        self.assertGreater(ranked[0], ranked[1])

    def test_frozen_replay_reuses_identical_learned_coefficients(self):
        data = study.load_data()
        first = study.train_ogrde(
            data, 2024, False, False, training_end_year=study.FROZEN_TRAINING_END
        )
        second = study.train_ogrde(
            data, 2025, False, False, training_end_year=study.FROZEN_TRAINING_END
        )
        self.assertTrue(np.array_equal(first[0].mean_, second[0].mean_))
        self.assertTrue(np.array_equal(first[-1].coef_, second[-1].coef_))

    def test_annual_bootstrap_is_invariant_to_added_competitor(self):
        rows = []
        for year, reference, first, second in zip(
            study.DEVELOPMENT_TARGETS, (.5, .6, .4, .7), (.4, .55, .45, .6), (.2, .3, .25, .35)
        ):
            rows.extend([
                {"year": year, "model": "OG-RDE", "average_precision": reference},
                {"year": year, "model": "first", "average_precision": first},
                {"year": year, "model": "second", "average_precision": second},
            ])
        metrics = study.pd.DataFrame(rows)
        full = study.annual_paired_comparisons(metrics)
        reduced = study.annual_paired_comparisons(metrics[metrics.model != "second"])
        full_first = full[full.competitor == "first"].iloc[0]
        reduced_first = reduced[reduced.competitor == "first"].iloc[0]
        self.assertEqual(full_first.delta_low, reduced_first.delta_low)
        self.assertEqual(full_first.delta_high, reduced_first.delta_high)

    def test_cook_2021_single_source_matches_published_kernel(self):
        source = np.zeros(builder.SHAPE)
        source[20, 20] = 1
        risk = study.cook_2021_kernel(source)
        dy_km = builder.STEP * 111.0
        self.assertAlmostEqual(float(risk[21, 20]), float(np.exp(-.045 * dy_km)), places=10)

    def test_first_report_excludes_origin_cells(self):
        data = study.load_data()
        for year in (2022, 2023, 2024, 2025, 2026):
            target = study.target_new_cells(data, year - 1, year)
            self.assertFalse(np.any((target > 0) & (data.history[year - 1] > 0)))

    def test_eligible_cells_are_unreported_land(self):
        data = study.load_data()
        mask = study.eligible_mask(data, 2024)
        self.assertFalse(np.any(mask & (data.history[2024] > 0)))
        self.assertFalse(np.any(mask & (data.cov["land"] <= .5)))

    def test_provenance_manifest_is_populated(self):
        data = study.load_data()
        provenance = study.data_provenance(data)
        self.assertEqual(provenance["analysisAccounting"]["insideCensusAnalysisMask"], 57999)
        self.assertEqual(set(provenance["sha256"]), {
            "occurrenceBundle", "hostCache", "censusStateBoundary", "worldclimElevation",
            "worldclimBioclim", "studyScript", "solverScript",
        })
        self.assertEqual(len(provenance["sha256"]["occurrenceBundle"]), 64)


if __name__ == "__main__":
    unittest.main()
