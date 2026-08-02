"""Tests for the typed SDK workout route/samples payload models (inbound contract)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.providers.mobile_sdk import WorkoutRoutePoint, WorkoutSample
from app.schemas.providers.mobile_sdk.sync_request import Workout

_WORKOUT_BASE = {
    "id": "wrk-001",
    "type": "running",
    "startDate": "2026-07-29T06:00:00Z",
    "endDate": "2026-07-29T06:45:00Z",
}


def test_route_points_parse_as_typed_models() -> None:
    workout = Workout(
        **_WORKOUT_BASE,
        route=[
            {
                "timestamp": "2026-07-29T06:00:01Z",
                "latitude": 52.229676,
                "longitude": 21.012229,
                "altitudeM": 142.0,
                "horizontalAccuracyM": 3.5,
                "verticalAccuracyM": None,
            },
            # altitude and accuracy are optional
            {"timestamp": "2026-07-29T06:00:02Z", "latitude": 52.229702, "longitude": 21.012301},
        ],
    )
    assert workout.route is not None
    assert isinstance(workout.route[0], WorkoutRoutePoint)
    assert workout.route[0].latitude == 52.229676
    assert workout.route[1].altitudeM is None


def test_samples_parse_as_typed_models() -> None:
    workout = Workout(
        **_WORKOUT_BASE,
        samples=[{"timestamp": "2026-07-29T06:00:01Z", "type": "heartRate", "value": 110.0, "unit": "bpm"}],
    )
    assert workout.samples is not None
    assert isinstance(workout.samples[0], WorkoutSample)
    assert workout.samples[0].type == "heartRate"
    assert workout.samples[0].value == Decimal("110.0")


def test_route_point_missing_latitude_fails_validation() -> None:
    with pytest.raises(ValidationError):
        Workout(
            **_WORKOUT_BASE,
            route=[{"timestamp": "2026-07-29T06:00:01Z", "longitude": 21.012229}],
        )


def test_workout_without_route_or_samples_still_valid() -> None:
    workout = Workout(**_WORKOUT_BASE)
    assert workout.route is None
    assert workout.samples is None
