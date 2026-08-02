from app.schemas.enums import SeriesType

# workouts[].samples[].type → SeriesType. Provider-agnostic camelCase vocabulary
# (cross-plan contract with the mobile apps; matches the SyncRequest
# json_schema_extra example). Values are stored as sent: bpm, m/s, spm/rpm, W,
# matching the SERIES_TYPE_DEFINITIONS units for these types.
WORKOUT_SAMPLE_TYPE_TO_SERIES_TYPE: dict[str, SeriesType] = {
    "heartRate": SeriesType.heart_rate,
    "speed": SeriesType.speed,
    "cadence": SeriesType.cadence,
    "power": SeriesType.power,
}


def get_series_type_from_workout_sample_type(sample_type: str) -> SeriesType | None:
    """
    Map a workouts[].samples[].type identifier to the unified SeriesType enum.
    Returns None when the sample type is not supported (the importer skips it).
    """
    return WORKOUT_SAMPLE_TYPE_TO_SERIES_TYPE.get(sample_type)
