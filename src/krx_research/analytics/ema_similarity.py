"""EMA-array similarity metrics ported from the V140 workstation."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from pandas import DataFrame

from .technical_indicators import EMA_WINDOWS

EMA_PROFILE_COLUMNS = ("close", *(f"ema_{window}" for window in EMA_WINDOWS))
EMA_PROFILE_LABELS = ("종가", *(f"EMA{window}" for window in EMA_WINDOWS))
EMA_DEFAULT_MIN_SIMILARITY = 85.0
EMA_GAP_TOLERANCE_OPTIONS = (1.0, 2.0, 3.0, 4.0)
EMA_DEFAULT_GAP_TOLERANCE = 2.0

_PROFILE_PAIRS = tuple(combinations(range(len(EMA_PROFILE_COLUMNS)), 2))
_EMA_PAIRS = tuple(combinations(range(len(EMA_WINDOWS)), 2))


def validate_ema_similarity_options(
    min_similarity: float,
    gap_tolerance: float,
) -> tuple[float, float]:
    """Validate V140-compatible order and pairwise-gap thresholds."""

    similarity = float(min_similarity)
    tolerance = float(gap_tolerance)
    if not 0.0 <= similarity <= 100.0:
        raise ValueError("ema_min_similarity must be between 0 and 100")
    if tolerance not in EMA_GAP_TOLERANCE_OPTIONS:
        choices = ", ".join(f"{value:g}" for value in EMA_GAP_TOLERANCE_OPTIONS)
        raise ValueError(f"ema_gap_tolerance must be one of: {choices}")
    return similarity, tolerance


def calculate_ema_similarity_metrics(
    profiles: DataFrame,
    *,
    reference_index: object,
) -> DataFrame:
    """Compare close plus eight EMAs using the exact V140 metric definitions.

    The returned frame contains the 36-pair ordering match, the RMS distance
    of eight EMA/close gaps, and the mean/max difference between all 28
    short-EMA/long-EMA gaps. Rows must already be same-date valid profiles.
    """

    if missing := set(EMA_PROFILE_COLUMNS).difference(profiles.columns):
        raise ValueError(f"EMA profile columns are missing: {sorted(missing)}")
    if reference_index not in profiles.index:
        raise ValueError("reference_index is not present in EMA profiles")
    if profiles.empty:
        return DataFrame(index=profiles.index)

    values = profiles.loc[:, EMA_PROFILE_COLUMNS].to_numpy(dtype="float64")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("EMA profiles must contain finite positive prices")
    reference_position = profiles.index.get_loc(reference_index)
    if not isinstance(reference_position, (int, np.integer)):
        raise TypeError("reference_index must identify exactly one row")
    reference_values = values[int(reference_position)]

    # Stable sorting preserves V140's label-order tie break when values match.
    array_orders = np.argsort(-values, axis=1, kind="stable")
    reference_order = array_orders[int(reference_position)]
    exact_array_match = np.all(array_orders == reference_order, axis=1)
    array_signature = [
        " > ".join(EMA_PROFILE_LABELS[index] for index in order) for order in array_orders
    ]

    profile_signs = np.column_stack(
        [np.sign(values[:, first] - values[:, second]) for first, second in _PROFILE_PAIRS]
    )
    reference_signs = np.sign(
        np.asarray(
            [
                reference_values[first] - reference_values[second]
                for first, second in _PROFILE_PAIRS
            ],
            dtype="float64",
        )
    )
    order_similarity = np.mean(profile_signs == reference_signs, axis=1) * 100.0

    normalized_gaps = (values[:, 1:] / values[:, [0]] - 1.0) * 100.0
    reference_normalized_gaps = normalized_gaps[int(reference_position)]
    shape_distance = np.sqrt(
        np.mean(np.square(normalized_gaps - reference_normalized_gaps), axis=1)
    )

    ema_values = values[:, 1:]
    pairwise_gaps = np.column_stack(
        [
            (ema_values[:, first] / ema_values[:, second] - 1.0) * 100.0
            for first, second in _EMA_PAIRS
        ]
    )
    reference_pairwise_gaps = pairwise_gaps[int(reference_position)]
    pairwise_differences = np.abs(pairwise_gaps - reference_pairwise_gaps)

    return pd.DataFrame(
        {
            "ema_array_signature": array_signature,
            "ema_exact_array_match": exact_array_match.astype("int64"),
            "ema_order_similarity_pct": order_similarity,
            "ema_shape_distance_pct": shape_distance,
            "ema_mean_gap_difference_pct": pairwise_differences.mean(axis=1),
            "ema_max_gap_difference_pct": pairwise_differences.max(axis=1),
        },
        index=profiles.index,
    )
