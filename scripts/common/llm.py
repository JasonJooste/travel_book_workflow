"""Ask Claude for JSON that matches a schema, through one of two backends (settings events.backend).

  cli   `claude -p` (Claude Code headless), on the Claude subscription you're logged in with
  api   the Anthropic API, paid per token, with the key in ~/.secrets/anthropic_api_key

structured(system, text, schema, backend=None, model=None) returns the JSON as a dict. It raises
RetryableError to try again later (rate limits, server errors), LimitReached when the
subscription's usage limit is hit, and RuntimeError for anything else, including a refusal or an
answer cut off.
"""
import json
import os
import re
import subprocess

from repo import EVENTS
from settings import settings

E = settings.events


class RetryableError(Exception):
    pass


class LimitReached(Exception):
    pass


class Cli:
    name, usd_per_mtok = "cli", None

    @property
    def model(self):
        return E.cli_model

    def structured(self, system, text, schema, model):
        # Without the API's variables, so claude uses the subscription login and never bills the API.
        # The system prompt replaces Claude Code's own; no tools, settings (CLAUDE.md, hooks) or MCP
        # servers. It runs in processing/events, so it picks up nothing of the project's
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        EVENTS.mkdir(parents=True, exist_ok=True)
        try:
            done = subprocess.run(
                ["claude", "-p", "--model", model, "--effort", E.effort, "--output-format", "json",
                 "--json-schema", json.dumps(schema), "--system-prompt", system, "--tools", "",
                 "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"],
                input=text, capture_output=True, text=True, timeout=E.timeout_s, cwd=EVENTS, env=env)
        except subprocess.TimeoutExpired as e:
            raise RetryableError(f"no answer in {E.timeout_s:.0f} s") from e
        try:
            result = json.loads(done.stdout)
        except json.JSONDecodeError:
            result = {"is_error": True, "result": (done.stdout + done.stderr).strip()[:500]}
        if result.get("is_error") or result.get("structured_output") is None:
            detail = f"{result.get('subtype') or ''} {result.get('result') or ''}".strip()
            status = result.get("api_error_status")
            # UNTESTED: written without having seen what claude prints at the usage limit
            if re.search(r"usage limit|hit your limit|limit reached|limit .*resets", detail, re.I):
                raise LimitReached(detail)
            if status == 429 or (status or 0) >= 500:
                raise RetryableError(f"{status}: {detail}")
            raise RuntimeError(detail or f"claude exited {done.returncode} with no structured output")
        return result["structured_output"]


class Api:
    name, usd_per_mtok = "api", (4, 20)  # input, output: for estimates

    def __init__(self):
        self.client = None

    @property
    def model(self):
        return E.api_model

    def structured(self, system, text, schema, model):
        import anthropic
        if self.client is None:
            self.client = anthropic.Anthropic(api_key=settings.secret("anthropic_api_key"))
        try:
            # A request the model declines is run again on a fallback model within the same call
            response = self.client.beta.messages.create(
                model=model, max_tokens=E.max_tokens,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": E.effort, "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": text}])
        except anthropic.RateLimitError as e:
            raise RetryableError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise RetryableError(str(e)) from e
            raise RuntimeError(str(e)) from e
        except anthropic.APIConnectionError as e:
            raise RetryableError(str(e)) from e
        if response.stop_reason != "end_turn":
            raise RuntimeError(f"stopped with {response.stop_reason}")
        return json.loads(next(b.text for b in response.content if b.type == "text"))


BACKENDS = {b.name: b for b in (Cli(), Api())}


def structured(system, text, schema, backend=None, model=None):
    """The JSON matching schema that Claude gives for text, as a dict."""
    b = BACKENDS[backend or E.backend]
    return b.structured(system, text, schema, model or b.model)
