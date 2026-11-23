"""The project's settings, managed with pydantic-settings.

    from settings import settings
    settings.route.gap_km

Every setting is a typed field below, and its default value is in settings.yaml at the repo
root: that file is the one place to see and change the defaults. A key in settings.yaml that
isn't a field here is an error, as is a value of the wrong type.

Where each value comes from, highest first:
  1. an environment variable SETTINGS_<FIELD>, e.g. SETTINGS_REVIEW__PORT=8100 make review
     (nested fields join with __), for a one-off run
  2. secrets only: the system keyring (GNOME Keyring, KWallet...), service "secrets", the
     field name as the username. Set one with `make secret NAME=<field>`, which prompts for it.
  3. secrets only: the file ~/.secrets/<field>, for when there's no keyring (SSH, cron,
     containers). Keep it chmod 600.
  4. settings.yaml, the defaults

The secrets: komoot_email, komoot_password (make fetch-komoot), anthropic_api_key (make events
with the api backend), deepgram_api_key, openai_api_key, elevenlabs_api_key (make transcripts
with those providers).

To add a setting, add the field here and its default to settings.yaml, with a comment there
saying what it's for. Don't give fields defaults here: settings.yaml holds them all. Secrets
are the exception: a secret is a `SecretStr | None = None` field and never goes in
settings.yaml. Not every target needs every secret, so a missing one is None rather than an
error, until settings.secret() is asked for it.
"""
import types
import typing
from datetime import date
from pathlib import Path
from typing import Literal

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # not installed yet (make venv): secrets come from the files only
    keyring = None

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from repo import BASE_DIR

SETTINGS_YAML = BASE_DIR / "settings.yaml"
SECRETS = Path.home() / ".secrets"
KEYRING_SERVICE = "secrets"


def is_secret(annotation):
    """Whether a field's type is SecretStr, or SecretStr | None."""
    if annotation is SecretStr:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return SecretStr in typing.get_args(annotation)
    return False


def read_secret(name):
    """A secret from the keyring, else from the secrets file of that name, else None.
    No keyring, or a locked one, falls through to the file."""
    value = None
    if keyring is not None:
        try:
            value = keyring.get_password(KEYRING_SERVICE, name)
        except KeyringError:
            value = None
    if value is None and (SECRETS / name).is_file():
        value = (SECRETS / name).read_text(encoding="utf-8").strip()
    return value


class SecretsSource(PydanticBaseSettingsSource):
    """Secret fields, from read_secret()."""

    def get_field_value(self, field, field_name):
        value = read_secret(field_name) if is_secret(field.annotation) else None
        return value, field_name, False

    def __call__(self):
        values = {}
        for name, field in self.settings_cls.model_fields.items():
            value, _, _ = self.get_field_value(field, name)
            if value is not None:
                values[name] = value
        return values


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
    pom_minutes: int
    poms_per_day: int
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
        """A secret's value, or exit saying how to set it."""
        value = getattr(self, name)
        if value is None:
            raise SystemExit(f"missing secret {name}: run make secret NAME={name}, which stores it in the "
                             f"system keyring (or put it in {SECRETS / name}, mode 600)")
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
        return init_settings, env_settings, SecretsSource(settings_cls), YamlConfigSettingsSource(settings_cls)


settings = Settings()
