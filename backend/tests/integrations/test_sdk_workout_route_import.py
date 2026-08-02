"""Integration tests for SDK workout route + per-sample ingestion (inbound)."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import DataPointSeries
from app.schemas.enums import SeriesType
from app.schemas.enums.series_types import get_series_type_id
from app.schemas.model_crud.activities import TimeSeriesQueryParams
from app.schemas.providers.mobile_sdk import SyncRequest as SDKSyncRequest
from app.services.apple.healthkit.import_service import ImportService
from app.services.timeseries_service import timeseries_service
from tests.factories import UserFactory

_WATCH_SOURCE: dict[str, Any] = {
    "name": "Apple Watch",
    "bundleIdentifier": "com.apple.health",
    "deviceManufacturer": "Apple Inc.",
    "deviceModel": "Watch",
    "productType": "Watch7,5",
    "deviceSoftwareVersion": "10.3.1",
    "operatingSystemVersion": {"majorVersion": 10, "minorVersion": 3, "patchVersion": 1},
}

_ROUTE = [
    {
        "timestamp": "2026-07-29T06:00:01Z",
        "latitude": 52.229676,
        "longitude": 21.012229,
        "altitudeM": 142.0,
        "horizontalAccuracyM": 3.5,
    },
    # second point has no altitude → no elevation row
    {"timestamp": "2026-07-29T06:00:02Z", "latitude": 52.229702, "longitude": 21.012301},
]

_SAMPLES = [
    {"timestamp": "2026-07-29T06:00:01Z", "type": "heartRate", "value": 110.0, "unit": "bpm"},
    {"timestamp": "2026-07-29T06:00:02Z", "type": "heartRate", "value": 112.0, "unit": "bpm"},
    {"timestamp": "2026-07-29T06:00:01Z", "type": "speed", "value": 1.8, "unit": "m/s"},
    # unknown type → silently skipped
    {"timestamp": "2026-07-29T06:00:01Z", "type": "swolfScore", "value": 33.0, "unit": "score"},
]


def _payload(provider: str = "apple", *, route: bool = True, samples: bool = True) -> dict[str, Any]:
    workout: dict[str, Any] = {
        "id": "801B68D7-F4AA-4A23-BD26-A3BA1BA6B08D",
        "type": "running",
        "startDate": "2026-07-29T06:00:00Z",
        "endDate": "2026-07-29T06:45:00Z",
        "zoneOffset": "+02:00",
        "source": _WATCH_SOURCE,
        "values": [{"type": "duration", "unit": "s", "value": 2700}],
    }
    if route:
        workout["route"] = _ROUTE
    if samples:
        workout["samples"] = _SAMPLES
    return {
        "provider": provider,
        "sdkVersion": "1.0.0",
        "syncTimestamp": "2026-07-29T12:00:00Z",
        "data": {"workouts": [workout]},
    }


def _series_rows(db: Session, series_type: SeriesType) -> list[DataPointSeries]:
    return (
        db.query(DataPointSeries)
        .filter(DataPointSeries.series_type_definition_id == get_series_type_id(series_type))
        .order_by(DataPointSeries.recorded_at)
        .all()
    )


class TestRouteIngestion:
    def test_route_samples_built_per_point(self) -> None:
        """Unit level: route points map to lat/lon(/elevation) samples, full precision."""
        service = ImportService(log=logging.getLogger("test"))
        request = SDKSyncRequest(**_payload(samples=False))
        bundles = list(service._build_workout_bundles(request, "00000000-0000-0000-0000-000000000123"))

        assert len(bundles) == 1
        _, _, ts_samples = bundles[0]
        by_type: dict[SeriesType, list[Decimal]] = {}
        for s in ts_samples:
            by_type.setdefault(s.series_type, []).append(Decimal(str(s.value)))

        assert by_type[SeriesType.latitude] == [Decimal("52.229676"), Decimal("52.229702")]
        assert by_type[SeriesType.longitude] == [Decimal("21.012229"), Decimal("21.012301")]
        assert by_type[SeriesType.elevation] == [Decimal("142.0")]  # only point 1 has altitudeM
        assert all(s.zone_offset == "+02:00" for s in ts_samples)
        assert all(s.provider == "apple" for s in ts_samples)

    def test_route_persists_as_data_point_series(self, db: Session) -> None:
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))

        result = service.load_data(db, _payload(samples=False), str(user.id))

        assert result["workouts_saved"] == 1
        assert result["records_saved"] == 5  # 2 lat + 2 lon + 1 elevation
        lat_rows = _series_rows(db, SeriesType.latitude)
        assert len(lat_rows) == 2
        # DataPointSeries.value is Numeric(10,3): lat/lon are quantized on write
        # (~55 m worst case), which is what the value column's precision allows.
        assert lat_rows[0].value == Decimal("52.230")
        assert len(_series_rows(db, SeriesType.longitude)) == 2
        assert len(_series_rows(db, SeriesType.elevation)) == 1

    def test_workout_without_route_unchanged(self, db: Session) -> None:
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))

        result = service.load_data(db, _payload(route=False, samples=False), str(user.id))

        assert result["workouts_saved"] == 1
        assert result["records_saved"] == 0
        assert _series_rows(db, SeriesType.latitude) == []


class TestWorkoutSampleIngestion:
    def test_heart_rate_and_speed_samples_built(self) -> None:
        service = ImportService(log=logging.getLogger("test"))
        request = SDKSyncRequest(**_payload(route=False))
        bundles = list(service._build_workout_bundles(request, "00000000-0000-0000-0000-000000000123"))

        _, _, ts_samples = bundles[0]
        hr = [s for s in ts_samples if s.series_type == SeriesType.heart_rate]
        speed = [s for s in ts_samples if s.series_type == SeriesType.speed]

        assert [s.value for s in hr] == [Decimal("110.0"), Decimal("112.0")]
        assert [s.value for s in speed] == [Decimal("1.8")]
        # unknown sample type ("swolfScore") is silently skipped
        assert len(ts_samples) == 3

    def test_samples_persist_as_data_point_series(self, db: Session) -> None:
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))

        result = service.load_data(db, _payload(route=False), str(user.id))

        assert result["records_saved"] == 3  # 2 HR + 1 speed; swolfScore dropped
        hr_rows = _series_rows(db, SeriesType.heart_rate)
        assert [row.value for row in hr_rows] == [Decimal("110.000"), Decimal("112.000")]
        assert len(_series_rows(db, SeriesType.speed)) == 1


class TestEndToEnd:
    def test_samsung_provider_ingests_identically(self, db: Session) -> None:
        """The route/samples path is provider-agnostic, with no apple branching."""
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))

        result = service.load_data(db, _payload(provider="samsung"), str(user.id))

        assert result["workouts_saved"] == 1
        assert result["records_saved"] == 8  # 5 route + 3 samples

    def test_repush_is_idempotent(self, db: Session) -> None:
        """Re-sending the same workout upserts in place, with no duplicate rows."""
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))

        service.load_data(db, _payload(), str(user.id))
        service.load_data(db, _payload(), str(user.id))

        assert len(_series_rows(db, SeriesType.latitude)) == 2
        assert len(_series_rows(db, SeriesType.heart_rate)) == 2

    def test_backend_read_path_returns_ingested_series(self, db: Session) -> None:
        """The exact series names PilotAppBackend queries come back from get_timeseries."""
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))
        service.load_data(db, _payload(), str(user.id))

        params = TimeSeriesQueryParams(
            start_datetime=datetime(2026, 7, 29, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 7, 30, tzinfo=timezone.utc),
            limit=100,
            cursor=None,
        )
        result = timeseries_service.get_timeseries(
            db,
            user.id,
            [SeriesType.heart_rate, SeriesType.latitude, SeriesType.longitude, SeriesType.speed],
            params,
        )

        types_returned = {sample.type for sample in result.data}
        assert types_returned == {
            SeriesType.heart_rate,
            SeriesType.latitude,
            SeriesType.longitude,
            SeriesType.speed,
        }
        assert len(result.data) == 7  # 2 HR + 2 lat + 2 lon + 1 speed

    def test_workout_with_bad_route_point_is_dropped_whole(self, db: Session) -> None:
        """Drop-&-log (NOT fail-the-batch): a workout with one invalid route point is
        dropped whole (its workout record AND all its route/HR samples), logged, and
        reported in result["dropped"] (collection == "workouts"), while the rest of
        the batch persists and the import reports partial success.
        Cross-plan (iOS plan, ii-#6): the sync route 202s before this runs in the
        Celery worker, so 202 does not mean ingested.
        """
        user = UserFactory()
        service = ImportService(log=logging.getLogger("test"))
        payload = _payload()
        bad_workout = {
            **payload["data"]["workouts"][0],
            "id": "BAD-ROUTE-WORKOUT",
            # missing latitude → WorkoutRoutePoint (Task 1) validation fails
            "route": [{"timestamp": "2026-07-29T06:00:01Z", "longitude": 21.012229}],
        }
        payload["data"]["workouts"].append(bad_workout)

        result = service.load_data(db, payload, str(user.id))

        assert result["workouts_saved"] == 1  # only the valid workout
        assert result["records_saved"] == 8  # the valid workout's 5 route + 3 sample rows
        # the dropped workout contributed NO series rows (its valid HR samples went with it)
        assert len(_series_rows(db, SeriesType.latitude)) == 2
        assert len(result["dropped"]) == 1
        drop = result["dropped"][0]
        assert drop["collection"] == "workouts"
        assert drop["index"] == 1
        assert "latitude" in drop["loc"]
