# Contributing

> **This is the standard workflow.** It comes from the project template (`my-cookiecutter`) and is
> the same in every project made from it. Don't change it here: change it in the template. Rules
> that only apply to this project go under [Project-specific rules](#project-specific-rules) at the end.

This guide covers how the requirements (SRS) and design (SDD) documents and the branches fit
together.

- [Documents](#documents)
- [Branches](#branches)
- [Phase documents](#phase-documents)
- [Feature branches](#feature-branches)
- [Keeping documents aligned](#keeping-documents-aligned)
- [IDs and open questions](#ids-and-open-questions)
- [Commits](#commits)
- [Automatic checks](#automatic-checks)
- [Project-specific rules](#project-specific-rules)

## Documents

Plans nest **two levels deep**: the vision, and one plan per phase. Nothing below a phase has
documents of its own.

```
docs/
├── README.md                  what each document is for, template credits
├── vision_requirements.md     the vision SRS: what the project must do, every phase
├── vision_design.md           the vision SDD: how it will be built, with the design decisions (D-nnn)
├── des_req_templates/         jam01's SRS and SDD templates, vendored
└── branches/                  one requirements + design pair per phase branch
    ├── <phase>_requirements.md
    └── <phase>_design.md
```

The **vision documents** describe the whole long-term plan. They live on `main` and are expected to
change as we learn. Every requirement is tagged with the phase it belongs to (`MVP`, `P2`, …, `Vision`)
in the SRS's apportioning section (§2.6).

## Branches

Branches nest in three levels, but only the top two have documents:

```
main                      vision_requirements.md, vision_design.md
└── mvp                   branches/mvp_requirements.md, branches/mvp_design.md
    └── mvp-dashboard     no documents: implements part of the mvp documents
```

- A **phase branch** (`mvp`, `p2`, …) starts from `main` and merges back into it when the phase is
  done.
- A **feature branch** starts from its phase branch and merges back into it. It's named
  `<phase>-<feature>`, not `<phase>/<feature>`: git can't have a branch `mvp` and a branch `mvp/…`
  at the same time.
- Don't nest deeper than this.

## Phase documents

Every **phase branch** gets its own requirements and design document, made from the guided templates
in [`docs/des_req_templates/`](docs/des_req_templates/) (`srs-template.md`, `sdd-template.md`), as
`docs/branches/<phase>_requirements.md` and `<phase>_design.md`. They're written on the phase branch
when it starts.

The phase documents **fill in the gaps** that the vision leaves open for that phase:

- **Requirements:** which vision requirements the phase covers (the ones tagged with it in §2.6),
  cited by ID (`R-FUNC-IMP-007`), with the details the vision leaves out, such as acceptance
  criteria, exact limits and edge cases.
- **Design:** what the vision marks as illustrative or left to a phase, such as exact field names,
  module layout and error messages, plus the decisions taken while building it.

A phase document doesn't repeat the vision. It cites the vision by ID and adds detail.

Write the phase documents before the implementation and keep them up to date while you work. They
are also the phase's plan, so there is no separate one:

- **Progress:** a status line at the top of each document says where the phase stands (draft, in
  progress with which features are done and which remain, merged). When the phase is merged, its
  documents stay, with the status line saying so.
- **Decided against:** options weighed and rejected are recorded in the design document's decisions,
  with the reason.
- **Verification:** how each requirement is checked goes in the requirements document's verification
  section (§4).

## Feature branches

A feature branch is implementation only. Its scope is the requirements in the phase documents it
implements, named in its first commit or pull request by ID. Whatever the work settles that the phase
documents leave open (a field name, an error message, a decision) goes into the phase documents in
the same branch, along with the status line's progress.

## Keeping documents aligned

The vision, the phase documents and the code must never contradict each other. If they disagree,
update one of them until they agree, in the branch where the disagreement came up, before it is
merged:

- If the **phase is right** (the work showed the vision was wrong or incomplete), change the vision
  documents. Record the change as a design decision (a new or revised D-nnn in the vision SDD) and
  add a row to their revision history.
- If the **vision is right**, change the phase documents and the implementation.

Detail that only matters to one phase stays in the phase documents. Anything that changes what the
project does, or how it fits together, goes into the vision.

## IDs and open questions

- **Requirement IDs** (`R-AREA-NNN`, functional `R-FUNC-<GROUP>-NNN`) and **decision IDs** (`D-nnn`)
  are unique and never reused. Design views and decisions cite the requirement IDs they implement. A
  requirement that is dropped or replaced keeps a struck-through row that points to what replaced it.
- **Open questions** are marked `❓ OPEN-nnn` where they arise and listed in the document's appendix.
  Close them by recording the answer (and a decision, if options were weighed) and removing the
  marker.

## Commits

A commit is the unit of ID stability. Between commits a draft can be rewritten freely, including
renumbering. Before committing, compare the documents with the last commit: every ID that existed
there and has gone or changed needs its struck-through row or an old → new mapping.

Use an imperative subject line and a body that explains why.

## Automatic checks

Git hooks in `scripts/git-hooks/` have an LLM check the documents. `make hooks` turns them on; it
runs when the project is made, and needs running again in every new clone.

- **On commit:** a requirements or design document is checked the first time it's committed
  finished, that is with no template guidance (`➥` lines) left in it. It's checked against its
  partner, if that's finished too, and a phase's documents against the vision: contradictions, and
  IDs cited that don't exist. Later edits aren't checked on commit: the merge check covers them.
- **On merge:** a merge into a phase branch or `main` is checked against the vision and that phase's
  documents: whether the change violates a requirement or contradicts the design, and whether the
  documents contradict each other. Merges that only bring a branch up to date (`main` into a phase,
  a phase into a feature) aren't checked. `make hooks` turns off fast-forward merges, which would
  skip the check.

A problem stops the commit or merge, and so does a model that can't be reached. Fix the problem, or
skip the check with `--no-verify` if you're sure. The phase is read from the branch name, so phase
names have no `-` in them. Merges made outside git on this machine, such as on GitHub, aren't
checked.

The model is any command that reads a prompt on stdin and prints the answer: `claude -p` by
default. To use another one, set `git config llm.command "<command>"` (or `$LLM_COMMAND`); the
docstring of `scripts/git-hooks/llm.py` has examples.

## Project-specific rules

None yet.
