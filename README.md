# Conductor workflows for Wagtail

[Conductor](https://github.com/microsoft/conductor) workflows for automating
work on the [Wagtail](https://github.com/wagtail/wagtail) project — currently
issue triage and turning issues into pull requests. Everything runs on your
machine: fetching, code execution, and all GitHub writes go through the `gh`
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
  quiet unless there is something new to say. Any changes made in worktrees
  during reproduction are attached to the comment as diffs. The comment never
  @-mentions anyone: the drafting prompt forbids it, and the apply step strips
  any remaining mentions (outside code blocks) as a backstop.

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

### `issue-to-pr`

Implements a fix or enhancement for a (usually triaged) Wagtail issue and opens
a **draft pull request** from your fork:

- **Reuses prior triage work**: if `issue-triage` has a run for the issue in
  its `.runs/`, the useful artifacts are copied across (triage findings,
  notes, reproduction diffs) and the heavyweight ones are **symlinked, not
  duplicated** — the git worktree of the Wagtail checkout and the reproduction
  venv. If the issue was triaged by a human instead, the full comment history
  is mined for their findings.
- Runs in the reused worktree (or a fresh one created in the run's scratch
dir), on a `fix/issue-<n>` / `feature/issue-<n>` / `docs/issue-<n>` branch
  based on the default branch, commits the change plus regression tests, runs
  them via the shared `run-tests` skill, and pushes the branch to your fork.
- A drafting phase then writes the PR title and body following the repo's
  **PR template** (every section filled, `Fixes #<n>` linking the issue, honest
  AI-usage disclosure, no @-mentions).
- Before anything is written to GitHub, a **review gate** shows the exact
  title and body that will be submitted: open the draft PR, send it back to
  the drafting agent with feedback, or abandon without opening anything.
- PR creation is deterministic and always `--draft`: a Python step validates
  the body against the template snapshot (all section headers present) and the
  issue link, strips mentions, applies `component:*` / `type:*` labels chosen
  by the drafting agent (from the same label snapshot issue-triage uses, plus
  `status:Needs Review` unconditionally), and creates the PR via `gh`. The
  agent can never open a non-draft PR or skip the template.

Like `issue-triage`, implementation runs on a time budget (~45 minutes with a
hard timeout): when it runs out, a human gate offers keep-going / open a draft
from the partial work / abandon. A second gate sits between drafting and
submission, so no PR is ever created without a human seeing exactly what will
be posted.

The implementation agent decides the code but the PR itself is applied by a
deterministic script that enforces the draft flag and the template contract —
same decide/apply split as `issue-triage`.

## Layout

```
index.yaml                          # registry index
README.md
workflows/
├── issue-triage/                   # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── prefetch.sh                 # prefetch: issue, labels snapshot,
                                    #   similar issues, comment history
    ├── reproduce.md                # phase 1: investigation prompt
    ├── finalize.md                 # phase 2: outcome-drafting prompt
    ├── apply_triage_outputs.py     # deterministic safe-outputs applier
    ├── skills/run-tests/SKILL.md   # Wagtail test-suite conventions (loaded
                                    #   by the triage agent on demand; shared
                                    #   with issue-to-pr)
    └── labels.json                 # label snapshot (component labels are
                                    #   filtered from this, not fetched)
└── issue-to-pr/                    # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── prefetch.sh                 # prefetch: issue state, PR template,
                                    #   open-PR guard, triage-run reuse
    ├── implement.md                # phase 1: implementation prompt
    ├── prepare_pr.md               # phase 2: PR-drafting prompt
    └── create_pr.py                # deterministic draft-PR applier
```

Per-run artifacts are kept (not cleaned up) for review, git-ignored:

```
workflows/<workflow>/.runs/<issue>/
├── data/       # prefetched issue, comments, similar issues / PR template
└── scratch/    # work environment: git worktree of the Wagtail checkout, venv,
                #   notes, diffs, and the step's decision output
```

When `issue-to-pr` reuses an `issue-triage` run, the worktree and venv are
symlinked into its own `.runs/<issue>/scratch/` (`wt` and `venv`), so the
environments are shared rather than duplicated — don't delete the originals.

The issue-to-pr workflow reuses issue-triage's `skills/run-tests` skill by
relative path (`../issue-triage/skills`), so it stays in sync automatically.

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
conductor run issue-to-pr@wagtail --input issue_number=1234
```

Optional inputs for `issue-triage`: `repository` (default `wagtail/wagtail`),
`wagtail_dir` (default `../../../wagtail` — a local checkout used for
reproduction and source inspection) and `bakerydemo_dir` (default
`../../../bakerydemo` — a local bakerydemo checkout used via a git worktree
for bakerydemo reproductions).

Optional inputs for `issue-to-pr`: `repository` (default `wagtail/wagtail`),
`wagtail_dir` (default `../../../wagtail` — the checkout the PR branch is cut
from), `base_branch` (default `main`) and `triage_runs_dir` (default
`../issue-triage/.runs` — scanned for prior work on the issue to reuse).

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
- `issue-to-pr` pushes commits to **your fork** and opens a PR — always as a
  **draft**, always from your own account, never closing or editing issues.
  The PR body is validated against the repo's PR template and stripped of
  @-mentions before creation.
