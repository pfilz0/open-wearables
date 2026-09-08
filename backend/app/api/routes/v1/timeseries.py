from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.database import DbSession
from app.schemas.enums import ProviderName, SeriesType
from app.schemas.model_crud.activities import TimeSeriesQueryParams
from app.schemas.responses.activity import TimeSeriesSample
from app.schemas.utils import PaginatedResponse
from app.services import ApiKeyDep, timeseries_service
from app.utils.dates import DateTimeQueryParam, parse_query_datetime

router = APIRouter()


@router.get("/users/{user_id}/timeseries")
def get_timeseries(
    user_id: UUID,
    start_time: DateTimeQueryParam,
    end_time: DateTimeQueryParam,
    db: DbSession,
    _api_key: ApiKeyDep,
    types: Annotated[list[SeriesType], Query()] = [],
    resolution: Literal["raw", "1min", "5min", "15min", "1hour"] = "raw",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    provider: Annotated[
        ProviderName | None,
        Query(description="Only return samples from this provider."),
    ] = None,
    device_model: Annotated[str | None, Query(description="Only return samples from this device model.")] = None,
    source: Annotated[str | None, Query(description="Only return samples from this source name.")] = None,
    data_source_id: Annotated[UUID | None, Query(description="Only return samples from this data source.")] = None,
    filter_by_priority: Annotated[
        bool,
        Query(
            description="When true, keep only the highest-priority source's samples per series type "
            "(provider/device priority, same ranking as summaries). Defaults to false for "
            "backwards compatibility."
        ),
    ] = False,
) -> PaginatedResponse[TimeSeriesSample]:
    """Returns granular time series data (biometrics or activity)."""
    params = TimeSeriesQueryParams(
        start_datetime=parse_query_datetime(start_time),
        end_datetime=parse_query_datetime(end_time),
        provider=provider,
        device_model=device_model,
        source=source,
        data_source_id=data_source_id,
        limit=limit,
        cursor=cursor,
    )
    return timeseries_service.get_timeseries(db, user_id, types, params, filter_by_priority=filter_by_priority)
