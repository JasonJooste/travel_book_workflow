"""Check the requirements (SRS) and design (SDD) documents with an LLM. Run by the git hooks here;
see "Automatic checks" in CONTRIBUTING.md.

commit: a document is checked the first time it's committed with no template guidance (➥) left in
        it: against its partner (SRS or SDD) if that's finished too, and a phase's against the vision.
merge:  a merge into a phase branch or main is checked against the vision and the phase's
        documents: whether the change violates them, and whether they contradict each other.
        Merges that only bring a branch up to date (main into a phase, a phase into a feature) are
        skipped.

Exits 1, stopping the commit or merge, when the model reports a problem or can't be asked.
The user can skip the checks with --no-verify. The model is set in llm.py.

Usage: python3 scripts/git-hooks/check_docs.py commit|merge
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

GUIDANCE = "➥"
VISION = ["docs/vision_requirements.md", "docs/vision_design.md"]
PHASE_DOC = re.compile(r"docs/branches/[^/]+_(requirements|design)\.md")
MAX_DIFF = 300_000  # characters of diff sent to the model

COMMIT_TASK = """\
You are checking a project's requirements (SRS) and design (SDD) documents for consistency. The
workflow they follow is in CONTRIBUTING.md, below. These documents are being committed finished for
the first time: {new}. The others are included for reference.

Check that:
- the SRS and SDD don't contradict each other, and every requirement ID and decision ID cited exists
- design views and decisions cite the requirement IDs they implement
- a phase's documents don't contradict the vision, cite vision requirements by ID, and add detail
  rather than repeat the vision
- no document contradicts itself

Report each problem with the document, the section and the IDs involved. Only a contradiction or a
missing or wrong ID is a problem; mention anything else briefly as a note. End with a line that is
exactly VERDICT: PASS if there are no problems, or VERDICT: FAIL if there are.
"""

MERGE_TASK = """\
You are checking a merge against a project's requirements (SRS) and design (SDD) documents. The
workflow they follow is in CONTRIBUTING.md, below. Branch {source} is being merged into {target}.
Below are the documents as they will be after the merge, then the merge's diff.

Check:
- whether anything in the diff violates a requirement or contradicts the design
- whether the documents contradict each other after the merge
- details the change settles that the documents leave open but don't record (CONTRIBUTING.md says
  they belong in the phase documents, in the same branch)

Report each problem with the file, the document section and the IDs involved. A violated
requirement or a contradiction is a problem; anything else is a note. End with a line that is
exactly VERDICT: PASS if there are no problems, or VERDICT: FAIL if there are.
"""


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def show(rev_path):
    """A file's content at a revision (":path" is the index), or None if it isn't there."""
    result = subprocess.run(["git", "show", rev_path], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def finished(text):
    return text is not None and GUIDANCE not in text


def partner(path):
    return path.replace("_requirements.md", "_design.md") if path.endswith("_requirements.md") \
        else path.replace("_design.md", "_requirements.md")


def documents(paths):
    return "".join(f"\n===== {p} =====\n{show(':' + p)}" for p in paths)


def commit_check():
    changed = git("diff", "--cached", "--name-only", "--diff-filter=AM").splitlines()
    docs = [p for p in changed if p in VISION or PHASE_DOC.fullmatch(p)]
    new = [p for p in docs if finished(show(":" + p)) and not finished(show("HEAD:" + p))]
    if not new:
        return None
    include = list(new)
    for p in new:
        extra = [partner(p)] + (VISION if PHASE_DOC.fullmatch(p) else [])
        include += [q for q in extra if q not in include and finished(show(":" + q))]
    return COMMIT_TASK.format(new=", ".join(new)) + documents(["CONTRIBUTING.md"] + include)


def branch_name(text):
    """'mvp', from "mvp", "branch 'mvp'", "remote-tracking branch 'origin/mvp'" or "branch 'mvp' of <url>"."""
    match = re.search(r"branch '([^']+)'", text)
    name = match.group(1) if match else text.strip()
    for remote in git("remote").split():
        name = name.removeprefix(remote + "/")
    return name


def merge_source():
    for key, value in os.environ.items():  # set by git merge for pre-merge-commit
        if key.startswith("GITHEAD_"):
            return branch_name(value)
    msg = Path(git("rev-parse", "--git-path", "MERGE_MSG").strip())  # a merge committed after conflicts
    return branch_name(msg.read_text().splitlines()[0]) if msg.is_file() else None


def merge_check():
    target = git("symbolic-ref", "--short", "-q", "HEAD").strip()
    source = merge_source()
    if source and (source in ("main", target) or target.startswith(source + "-")):
        return None  # only bringing the branch up to date
    phase = (target if target != "main" else source or "").split("-")[0]
    paths = VISION + [f"docs/branches/{phase}_{kind}.md" for kind in ("requirements", "design")]
    paths = [p for p in paths if show(":" + p) is not None]
    if not paths:
        return None
    diff = git("diff", "--cached", "HEAD", "--", ".", ":(exclude)docs/des_req_templates")
    if not diff.strip():
        return None
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n[diff truncated: only check what's shown]\n"
    task = MERGE_TASK.format(source=source or "(unknown)", target=target or "(detached HEAD)")
    return task + documents(["CONTRIBUTING.md"] + paths) + "\n===== merge diff =====\n" + diff


def main(mode):
    prompt = {"commit": commit_check, "merge": merge_check}[mode]()
    if prompt is None:
        return 0
    print(f"Checking the SRS and SDD ({mode}) with `{' '.join(llm.command())}`…", file=sys.stderr)
    try:
        answer = llm.ask(prompt)
    except llm.Error as e:
        print(f"Doc check couldn't run: {e}\nTo skip it: --no-verify", file=sys.stderr)
        return 1
    print(answer, file=sys.stderr)
    verdicts = re.findall(r"^\W*VERDICT:\s*(PASS|FAIL)\b", answer, re.MULTILINE)
    if verdicts[-1:] == ["PASS"]:
        return 0
    reason = "found problems" if verdicts else "gave no verdict"
    print(f"Doc check {reason}: fix them, or skip the check with --no-verify.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
