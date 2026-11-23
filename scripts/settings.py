"""The project's settings, managed with pydantic-settings.

    from settings import settings
    settings.example_threshold
    settings.example_api_key.get_secret_value()     a secret (None if it isn't set)

Every setting is a typed field on Settings below, and its default value is in settings.yaml
at the repo root: that file is the one place to see and change the defaults. A key in
settings.yaml that isn't a field here is an error, as is a value of the wrong type.

Where each value comes from, highest first:
  1. an environment variable SETTINGS_<FIELD>, e.g. SETTINGS_EXAMPLE_THRESHOLD=0.9 make index
     (nested fields join with __: SETTINGS_SECTION__FIELD), for a one-off run
  2. secrets only: the system keyring (GNOME Keyring, KWallet...), service "secrets", the
     field name as the username. Set one with `make secret NAME=<field>`, which prompts for it.
  3. secrets only: the file ~/.secrets/<field>, for when there's no keyring (SSH, cron,
     containers). Keep it chmod 600.
  4. settings.yaml, the defaults

To add a setting, add the field here and its default to settings.yaml, with a comment there
saying what it's for. Don't give fields defaults here: settings.yaml holds them all.
Secrets are the exception: a secret is a `SecretStr | None = None` field and never goes in
settings.yaml. Not every target needs every secret, so a missing one is None rather than an
error: check for it where it's used.
"""
import types
import typing
from pathlib import Path

import keyring
from keyring.errors import KeyringError
from pydantic import SecretStr
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
    """A secret from the keyring, else from ~/.secrets/<name>, else None.
    No keyring, or a locked one, falls through to the file."""
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=SETTINGS_YAML,
        env_prefix="SETTINGS_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    example_threshold: float

    # Example secret: replace with the project's own (no entry in settings.yaml)
    example_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            SecretsSource(settings_cls),
            YamlConfigSettingsSource(settings_cls),
        )


settings = Settings()
