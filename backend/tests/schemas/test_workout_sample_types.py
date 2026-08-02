"""Silent-drop guard: every contract sample type must map to a SeriesType."""

import pytest

from app.constants.series_types.sdk import get_series_type_from_workout_sample_type
from app.schemas.enums import SeriesType

SAMPLE_TYPE_MAP = [
    ("heartRate", SeriesType.heart_rate),
    ("speed", SeriesType.speed),
    ("cadence", SeriesType.cadence),
    ("power", SeriesType.power),
]


@pytest.mark.parametrize(("sample_type", "series_type"), SAMPLE_TYPE_MAP)
def test_workout_sample_type_maps_to_series_type(sample_type: str, series_type: SeriesType) -> None:
    # Unmapped sample types are silently dropped by the importer, so these
    # mappings must exist or the pushed data vanishes.
    assert get_series_type_from_workout_sample_type(sample_type) is series_type


def test_unknown_sample_type_returns_none() -> None:
    assert get_series_type_from_workout_sample_type("swolfScore") is None
