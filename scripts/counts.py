#!/usr/bin/env python3
"""Update the Words column of story_plans/*.csv from the stories as the book prints them.

Usage: counts.py

A story matches a plan row when its name equals the row's Name (clean/stories/adrien.md ->
Name "adrien"). Warns when a plan is open in LibreOffice, whose next save would undo this.
"""
import csv
import io
import sys

from common.tables import write_text
from repo import STORIES, STORY_PLANS


def update_plan(plan, counts, matched):
    with plan.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    changed = 0
    for row in rows:
        name = row["Name"].strip()
        if name in counts:
            matched.add(name)
            new = str(counts[name])
            if row["Words"] != new:
                print(f"  {plan.name}: {name} {row['Words'] or '-'} -> {new}")
                row["Words"] = new
                changed += 1
    if changed:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        write_text(plan, out.getvalue())


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    counts = {p.stem: len(p.read_text(encoding="utf-8").split()) for p in sorted(STORIES.glob("*.md"))}
    matched = set()
    for plan in sorted(STORY_PLANS.glob("*.csv")):
        if plan.with_name(f".~lock.{plan.name}#").exists():
            print(f"  warning: {plan.name} is open in LibreOffice; saving there will overwrite these changes",
                  file=sys.stderr)
        update_plan(plan, counts, matched)
    for name in sorted(set(counts) - matched):
        print(f"  unmatched story: {name} ({counts[name]} words)", file=sys.stderr)


if __name__ == "__main__":
    main()
