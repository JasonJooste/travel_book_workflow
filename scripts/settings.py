"""The project's settings, managed with pydantic-settings.

    from settings import settings
    settings.route.gap_km

Every setting is a typed field below, and its default value is in settings.yaml at the repo
root: that file is the one place to see and change the defaults. A key in settings.yaml that
isn't a field here is an error, as is a value of the wrong type.

Where each value comes from, highest first:
  1. an environment variable SETTINGS_<FIELD>, e.g. SETTINGS_REVIEW__PORT=8100 make review
     (nested fields join with __), for a one-off run
  2. ~/.secrets/<field>, for the SecretStr fields, so secrets stay out of the repo:
     komoot_email, komoot_password, anthropic_api_key, deepgram_api_key, openai_api_key,
     elevenlabs_api_key. Each file holds just the value.
  3. settings.yaml, the defaults

To add a setting, add the field here and its default to settings.yaml, with a comment there
saying what it's for. Don't give fields defaults here: settings.yaml holds them all (secrets
excepted: they default to None, as not every target needs every one).
"""
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from repo import BASE_DIR

SETTINGS_YAML = BASE_DIR / "settings.yaml"
SECRETS = Path.home() / ".secrets"


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Trip(Section):
    start: date
    end: date


class Mode(Section):
    router: Literal["bike", "car", "foot", "none"]
    max_kmh: float | None
    colour: str
    vehicle: bool


class Lookup(Section):
    max_hours: float
    town_radius_km: float
    towns: int
    sample_days: float


class Locate(Section):
    gps_hours: float
    pass_hours: float
    predicted_hours: float


class Stays(Section):
    ride_morning: int
    photo_evening: int
    photo_morning: int
    day_evening: int
    day_morning: int
    night_ends: int
    support_days: int
    bridge_km: float
    max_away: int
    note_km: float
    big_town_km: float
    radius_km: float
    min_nights: int


class Route(Section):
    gap_km: float
    still_km: float
    snap_km: float
    spacing_km: float
    inside_hours: float
    photo_km: float
    spike_kmh: float
    fix_min: float
    fix_kmh: float
    stay_kmh: float
    stay_hours: float
    replace_min: float
    stay_arrive: str
    stay_leave: str
    midday: str
    detour_factor: float
    detour_km: float
    bicycle_type: str
    use_roads: float


class Checks(Section):
    long_row_days: float
    long_row_legs: int
    overlap_min: float
    switch_km: float
    switch_hours: float
    vehicle_km: float
    leg_km: float
    step_kmh: float
    step_km: float
    step_join_min: float
    day_km: float
    short_flight_km: float
    straight_km: float
    spike_km: float
    spike_apart_km: float
    spike_hours: float
    spike_join_km: float
    spike_max_km: float
    detour: float
    detour_km: float
    dismiss_deg: float
    bridge_m: float
    crossing_min: float
    moving_kmh: float
    waterways: list[str]
    window_min: float
    window_gap_min: float
    walk_kmh: float
    vehicle_kmh: float
    vehicle_min: float
    lift_join_min: float


class Osm(Section):
    regions: list[str]
    bike_prefixes: list[str]
    ridden_motorways: list[str]
    max_route_km: float


class Transcribe(Section):
    provider: Literal["deepgram", "openai", "elevenlabs", "whisper"]
    pilot_providers: list[Literal["deepgram", "openai", "elevenlabs", "whisper"]]
    workers: int
    retries: int
    max_terms: int
    languages: list[str]
    whisper_model: str
    whisper_threads: int
    remote_host: str
    audio_rate: int
    audio_bitrate: str


class Events(Section):
    backend: Literal["cli", "api"]
    workers: int
    min_words: int
    retries: int
    cli_model: str
    api_model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    timeout_s: float
    max_tokens: int


class Review(Section):
    port: int


class Writing(Section):
    target_words: int
    pom_minutes: float
    poms_per_day: float
    min_edit_sessions: int
    min_notes_resolved: int
    session_gap_min: float
    session_pad_min: float
    period: Literal["day", "week", "month", "all"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=SETTINGS_YAML,
        env_prefix="SETTINGS_",
        env_nested_delimiter="__",
        secrets_dir=SECRETS if SECRETS.is_dir() else None,
        extra="forbid",
        frozen=True,
    )

    trip: Trip
    modes: dict[str, Mode]
    predicted_colour: str
    stopped_colour: str
    gpx_pause_hours: float
    track_gap_days: int
    lookup: Lookup
    locate: Locate
    places_spread_km: float
    stays: Stays
    route: Route
    checks: Checks
    osm: Osm
    transcribe: Transcribe
    events: Events
    review: Review
    writing: Writing

    komoot_email: SecretStr | None = None
    komoot_password: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None

    @property
    def classes(self):
        """The route's classes: cycled, predicted, stopped, then the other modes."""
        return ("cycled", "predicted", "stopped", *(m for m in self.modes if m != "cycled"))

    @property
    def colours(self):
        return {"predicted": self.predicted_colour, "stopped": self.stopped_colour,
                **{m: v.colour for m, v in self.modes.items()}}

    def secret(self, name):
        """A secret's value, or exit saying where to put it."""
        value = getattr(self, name)
        if value is None:
            raise SystemExit(f"missing secret {name}: put it in {SECRETS / name} (just the value, mode 600)")
        return value.get_secret_value().strip()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, env_settings, file_secret_settings, YamlConfigSettingsSource(settings_cls)


settings = Settings()
