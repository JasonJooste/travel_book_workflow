"""Send a prompt to an LLM and return its answer: the one place the doc checks call a model.

The model is any command that reads the prompt on stdin and writes the answer to stdout:
$LLM_COMMAND if set, else `git config llm.command`, else `claude -p`. For example:
  git config llm.command "claude -p"             Claude Code (the default)
  git config llm.command "llm -m gpt-4o"         simonw's llm: OpenAI, Anthropic, Gemini, Ollama… via plugins
  git config llm.command "ollama run llama3.1"   a local model

Usage: python3 scripts/git-hooks/llm.py < prompt.txt
"""
import os
import shlex
import subprocess
import sys

DEFAULT = "claude -p"


class Error(Exception):
    pass


def command():
    configured = os.environ.get("LLM_COMMAND") or subprocess.run(
        ["git", "config", "--get", "llm.command"], capture_output=True, text=True
    ).stdout.strip()
    return shlex.split(configured or DEFAULT)


def ask(prompt):
    cmd = command()
    # Git sets GIT_INDEX_FILE and friends for hooks; the model's command shouldn't inherit them.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise Error(f"{cmd[0]} not found: install it, or set llm.command (see {__file__})")
    if result.returncode:
        raise Error(f"{shlex.join(cmd)} failed ({result.returncode}): {result.stderr.strip()[-500:]}")
    return result.stdout


if __name__ == "__main__":
    try:
        print(ask(sys.stdin.read()))
    except Error as e:
        sys.exit(str(e))
