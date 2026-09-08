"""Tests for the /timeseries source filters, page-size cap, and priority filtering.

- provider / device_model / source / data_source_id filters (previously declared on
  TimeSeriesQueryParams but unreachable through the route; data_source_id was also
  never applied in the repository).
- The page-size cap raised from 100 to 1000.
- filter_by_priority: one winning source per series type, never a blend of two.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DataPointSeries, DataSource, SeriesTypeDefinition
from app.repositories.device_type_priority_repository import DeviceTypePriorityRepository
from app.repositories.provider_priority_repository import ProviderPriorityRepository
from app.schemas.enums import ProviderName, SeriesType, get_series_type_id
from tests.factories import ApiKeyFactory, DataPointSeriesFactory, DataSourceFactory, UserFactory
from tests.utils import api_key_headers

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
WINDOW = {
    "start_time": (NOW - timedelta(hours=1)).isoformat(),
    "end_time": (NOW + timedelta(hours=1)).isoformat(),
}


def _series_def(db: Session, series_type: SeriesType) -> SeriesTypeDefinition:
    """The seeded definition row for a series type."""
    return db.query(SeriesTypeDefinition).filter(SeriesTypeDefinition.id == get_series_type_id(series_type)).one()


def _rank(db: Session, *providers: tuple[ProviderName, int]) -> None:
    """Give providers explicit priorities (lower wins).

    Tests set these explicitly: DataSourceFactory writes DataSource rows directly, so
    it never triggers ensure_provider_exists and the priority table starts empty.
    """
    repo = ProviderPriorityRepository()
    for provider, priority in providers:
        repo.upsert(db, provider, priority)
    db.commit()


def _sample(
    db: Session,
    data_source: DataSource,
    series_type: SeriesType,
    value: float,
    minute: int = 0,
) -> DataPointSeries:
    return DataPointSeriesFactory(
        data_source=data_source,
        series_type=_series_def(db, series_type),
        value=value,
        recorded_at=NOW + timedelta(minutes=minute),
    )


class TestSourceFilters:
    def test_provider_filter_narrows_to_one_provider(self, client: TestClient, db: Session) -> None:
        user = UserFactory()
        garmin = DataSourceFactory(user=user, provider=ProviderName.GARMIN, source="garmin_connect")
        apple = DataSourceFactory(user=user, provider=ProviderName.APPLE, source="apple_health_sdk")
        _sample(db, garmin, SeriesType.heart_rate, 140)
        _sample(db, apple, SeriesType.heart_rate, 99)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "types": ["heart_rate"], "provider": "garmin"},
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert [s["value"] for s in data] == [140.0]
        assert data[0]["source"]["provider"] == "garmin"

    def test_data_source_id_filter_applies(self, client: TestClient, db: Session) -> None:
        """Regression: data_source_id was declared on the params but never applied."""
        user = UserFactory()
        wanted = DataSourceFactory(user=user, provider=ProviderName.GARMIN, device_model="Forerunner")
        other = DataSourceFactory(user=user, provider=ProviderName.GARMIN, device_model="Fenix")
        _sample(db, wanted, SeriesType.heart_rate, 150)
        _sample(db, other, SeriesType.heart_rate, 120)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "types": ["heart_rate"], "data_source_id": str(wanted.id)},
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        assert [s["value"] for s in response.json()["data"]] == [150.0]


class TestPageSizeCap:
    def test_limit_1000_is_accepted(self, client: TestClient, db: Session) -> None:
        user = UserFactory()
        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "limit": 1000},
            headers=api_key_headers(ApiKeyFactory().id),
        )
        assert response.status_code == 200

    def test_limit_above_1000_is_rejected(self, client: TestClient, db: Session) -> None:
        user = UserFactory()
        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "limit": 1001},
            headers=api_key_headers(ApiKeyFactory().id),
        )
        # The fork maps validation errors to 400 globally, not FastAPI's default 422.
        assert response.status_code == 400


class TestFilterByPriority:
    def test_defaults_to_off_and_returns_every_source(self, client: TestClient, db: Session) -> None:
        """Backwards compatibility: existing callers keep seeing all sources."""
        user = UserFactory()
        _rank(db, (ProviderName.APPLE, 2), (ProviderName.GARMIN, 3))
        apple = DataSourceFactory(user=user, provider=ProviderName.APPLE)
        garmin = DataSourceFactory(user=user, provider=ProviderName.GARMIN)
        _sample(db, apple, SeriesType.heart_rate, 100, minute=0)
        _sample(db, garmin, SeriesType.heart_rate, 140, minute=1)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "types": ["heart_rate"]},
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        assert sorted(s["value"] for s in response.json()["data"]) == [100.0, 140.0]

    def test_keeps_only_the_winning_source(self, client: TestClient, db: Session) -> None:
        """Two watches on one run must not blend into a single series."""
        user = UserFactory()
        _rank(db, (ProviderName.APPLE, 2), (ProviderName.GARMIN, 3))
        apple = DataSourceFactory(user=user, provider=ProviderName.APPLE)
        garmin = DataSourceFactory(user=user, provider=ProviderName.GARMIN)
        _sample(db, apple, SeriesType.heart_rate, 100, minute=0)
        _sample(db, apple, SeriesType.heart_rate, 101, minute=1)
        _sample(db, garmin, SeriesType.heart_rate, 140, minute=2)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "types": ["heart_rate"], "filter_by_priority": True},
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert sorted(s["value"] for s in data) == [100.0, 101.0]
        assert {s["source"]["provider"] for s in data} == {"apple"}

    def test_selection_is_per_series_type(self, client: TestClient, db: Session) -> None:
        """A watch with HR but no GPS loses only the GPS series, not the whole run."""
        user = UserFactory()
        _rank(db, (ProviderName.GARMIN, 3), (ProviderName.POLAR, 4))
        garmin = DataSourceFactory(user=user, provider=ProviderName.GARMIN)
        polar = DataSourceFactory(user=user, provider=ProviderName.POLAR)
        # Garmin outranks Polar and has HR, but only Polar recorded a route.
        _sample(db, garmin, SeriesType.heart_rate, 150)
        _sample(db, polar, SeriesType.heart_rate, 120)
        _sample(db, polar, SeriesType.latitude, 52.229676)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={
                **WINDOW,
                "types": ["heart_rate", "latitude"],
                "filter_by_priority": True,
            },
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        by_type = {s["type"]: s for s in response.json()["data"]}
        assert by_type["heart_rate"]["source"]["provider"] == "garmin"
        assert by_type["latitude"]["source"]["provider"] == "polar"


class TestDeviceTypeTiebreaker:
    """Device type decides between two devices from the same provider."""

    def test_watch_beats_phone_within_one_provider(self, client: TestClient, db: Session) -> None:
        """The device_model tiebreaker is set against the watch, so only a working
        device-type comparison can make it win.

        data_source.device_type stores the enum value ("watch") while
        device_type_priority.device_type is a Postgres enum storing member names
        ("WATCH"). Compared raw they never match and the tiebreaker does nothing.
        """
        user = UserFactory()
        DeviceTypePriorityRepository().initialize_defaults(db)
        _rank(db, (ProviderName.GARMIN, 3))
        watch = DataSourceFactory(
            user=user, provider=ProviderName.GARMIN, device_type="watch", device_model="ZZZ"
        )
        phone = DataSourceFactory(
            user=user, provider=ProviderName.GARMIN, device_type="phone", device_model="AAA"
        )
        _sample(db, watch, SeriesType.heart_rate, 150)
        _sample(db, phone, SeriesType.heart_rate, 99, minute=1)

        response = client.get(
            f"/api/v1/users/{user.id}/timeseries",
            params={**WINDOW, "types": ["heart_rate"], "filter_by_priority": True},
            headers=api_key_headers(ApiKeyFactory().id),
        )

        assert response.status_code == 200
        assert [s["value"] for s in response.json()["data"]] == [150.0]
