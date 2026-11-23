# Travel book documentation

## Documents

| Document | Purpose |
|----------|---------|
| [vision_requirements.md](vision_requirements.md) | **What** Travel book must do, across its whole long-term vision (SRS). |
| [vision_design.md](vision_design.md) | **How** Travel book will be built, at the vision level (SDD). |
| [branches/](branches/) | One requirements and design pair per phase (`<phase>_requirements.md`, `<phase>_design.md`). |

The vision documents describe the grand plan. They are expected to change as we learn. How they and
the phase documents are used is the standard workflow in [CONTRIBUTING.md](../CONTRIBUTING.md).

Other documents here describe how to use the files edited by hand: input formats, review tools.

## Templates and acknowledgements

The templates in [`des_req_templates/`](des_req_templates/) are by **Jose Montoya ([jam01](https://github.com/jam01))**. They are dedicated to the public domain under CC0 1.0 (see each folder's `LICENSE`).

| Template | Upstream | Commit vendored |
|----------|----------|-----------------|
| Markdown Software Requirements Specification (MSRS) | <https://github.com/jam01/SRS-Template> | `3965e95` (2025-11-02) |
| Markdown Software Design Description (MSDD) | <https://github.com/jam01/SDD-Template> | `5dca2e5` (2025-12-29) |

The vision documents were made from the guided templates (`srs-template.md`, `sdd-template.md`), and every phase's documents are made from them too. The copies here are plain files, not git checkouts. To update them, copy the files from upstream again (in the project template, so every new project gets them) and update the commits above.
