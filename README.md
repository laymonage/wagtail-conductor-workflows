# Conductor workflows for Wagtail

[Conductor](https://github.com/microsoft/conductor) workflows for triaging
[Wagtail](https://github.com/wagtail/wagtail) issues. Everything runs on your
machine: fetching, reproduction, and all GitHub writes go through the `gh`
CLI, acting as your authenticated account.

This repository is a **Conductor registry** (see the
[registry design doc](https://github.com/microsoft/conductor/blob/main/docs/design/registry.md)):
it has an `index.yaml` at the root, and each workflow's assets live next to the
workflow YAML.

## Workflows

### `issue-triage`

First-pass triage of a newly opened (or reopened) Wagtail issue:

- Classifies the issue by template type (bug report, feature/enhancement,
  maintenance, documentation).
- Applies up to 3 matching `component:` labels from the local label snapshot.
- **Bug reports**: attempts an actual reproduction — bakerydemo (venv setup) or
  a fresh project from a local Wagtail checkout — capped at ~10 minutes of
  environment setup. If reproduction succeeds, removes `status:Unconfirmed`;
  if it fails and details are missing, swaps `status:Unconfirmed` for
  `status:Needs Info` and asks the reporter for specifics.
- **Feature requests / maintenance tasks**: assesses usefulness, breadth, and
  effort, checks for prior art, and adds `status:Needs Community Feedback`.
- **Documentation issues**: proposes concrete wording improvements.
- Posts **exactly one** comment per triage, prefixed with a disclaimer that it
  was written by an AI agent and may contain mistakes, and tagged with
  `<!-- workflow:issue-triage -->` so re-runs detect prior triage and stay
  quiet unless there is something new to say.

Triage runs in two phases with a time budget: an **investigation** phase
(reproduction, classification, component labels, ~20 minutes with a hard
timeout) writes running notes to `.runs/<issue>/scratch/NOTES.md`; if it runs
out of time, a **human gate** asks whether to keep going, conclude as not
reproducible and post the outcome, or conclude without posting anything. A
fast **drafting** phase then turns the findings into the comment, labels, and
body update, which a deterministic step applies.

The triage agent decides but never writes: labels, body updates, and the
comment are applied by a deterministic script that enforces allowlists and caps
for safe outputs.

## Layout

```
index.yaml                          # registry index
README.md
workflows/
└── issue-triage/                   # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── reproduce.md                # phase 1: investigation prompt
    ├── finalize.md                 # phase 2: outcome-drafting prompt
    ├── apply_triage_outputs.py     # deterministic safe-outputs applier
    ├── skills/run-tests/SKILL.md   # Wagtail test-suite conventions (loaded
                                    #   by the triage agent on demand)
    └── labels.json                 # label snapshot (component labels are
                                    #   filtered from this, not fetched)
```

Per-run artifacts are kept (not cleaned up) for review, git-ignored:

```
workflows/issue-triage/.runs/<issue>/
├── data/       # prefetched issue, comments, similar issues, prior triage
└── scratch/    # reproduction environment: bakerydemo/project clone, venv,
                #   git worktree of the Wagtail checkout, logs, and
                #   triage-output.json (the triage agent's decision)
```

The agent works in a git worktree inside `scratch/` when it needs to touch
Wagtail source (e.g. running a candidate unit test), so your checkout stays
pristine.

## Requirements

- [Conductor](https://github.com/microsoft/conductor) (registry support)
- [`gh`](https://cli.github.com/) authenticated against github.com
  (`gh auth login`)
- `jq`, Python 3
- For runs using the bundled model config: `CONDUCTOR_WORKFLOW_API_KEY` set in
  your environment, plus two optional overrides — `CONDUCTOR_WORKFLOW_BASE_URL`
  for the endpoint and `CONDUCTOR_WORKFLOW_MODEL` for the model (default:
  `z-ai/glm-5.3-flash`; set it to whatever your endpoint serves)
- A local Wagtail checkout (default: `../../../wagtail`, relative to the
  workflow's directory)

## Usage

Add this repository as a local registry (once):

```bash
conductor registry add wagtail /path/to/this/repo
```

Run it:

```bash
conductor run issue-triage@wagtail --input issue_number=1234
```

Optional inputs: `repository` (default `wagtail/wagtail`), `wagtail_dir`
(default `../../../wagtail` — a local checkout used for reproduction and source
inspection) and `bakerydemo_dir` (default `../../../bakerydemo` — a local
bakerydemo checkout used via a git worktree for bakerydemo reproductions).

You can also run the YAML directly:

```bash
conductor run workflows/issue-triage/workflow.yaml --input issue_number=1234
```

### Refreshing the label snapshot

Component labels come from `workflows/issue-triage/labels.json`. Regenerate it when
Wagtail's labels change:

```bash
gh label list --repo wagtail/wagtail --json name,color,description --limit 400 \
  > workflows/issue-triage/labels.json
```

(If the snapshot is missing, the prefetch step regenerates it automatically.)

## Safety notes

- The triage agent treats issue text as untrusted data, never as instructions.
- Only these writes can occur, enforced by the apply script: add
  `component:*`/`status:Needs Community Feedback`/`status:Needs Info` labels
  (max 4), remove at most one of `status:Unconfirmed`/`status:Needs Review`,
  update the issue body, and post one comment. No commits, PRs, or closes.
- Reproduction runs real `pip install`s and servers on your machine — review
  the scratch directory if that concerns you.
