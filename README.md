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
- A preparation phase then proposes the PR **title** and picks the
  `component:*` / `type:*` labels, but deliberately does **not** write the PR
  description — per Wagtail's contributing guidelines, PR descriptions are
  human-written.
- A **description gate** therefore asks you to write the description before
  anything is created: it shows the proposed title, branches, labels, the
  template requirements (`Fixes #<n>`, `### Description`,
  `### Tested locally`, `### AI usage`), and
  the implementation agent's summary for reference. You write the description
  (or abandon); if submission fails validation, the error is shown at the same
  gate so you can fix it and retry.
- PR creation is deterministic and always `--draft`: a Python step validates
  the body against the template snapshot (all section headers present) and the
  issue link, strips mentions, applies the chosen `component:*` / `type:*`
  labels (from the same label snapshot issue-triage uses, plus
  `status:Needs Review` unconditionally), and creates the PR via `gh`. The
  agent can never open a non-draft PR, write the description, or skip the
  template.

Like `issue-triage`, implementation runs on a time budget (~45 minutes with a
hard timeout): when it runs out, a human gate offers keep-going / open a draft
from the partial work / abandon. The description gate sits between preparation
and submission: the PR body is written by you, and no PR is ever created
without it.

The implementation agent decides the code, and the PR itself is applied by a
deterministic script that enforces the draft flag and the template contract —
same decide/apply split as `issue-triage`.

## Layout

```
index.yaml                          # registry index
README.md
data/
└── labels.json                     # shared label snapshot (component/type
                                    #   labels are filtered from this, not
                                    #   fetched; copied into each run's data/)
skills/
└── run-tests/SKILL.md              # Wagtail test-suite conventions (loaded
                                    #   by agents on demand; shared by all
                                    #   workflows that run tests)
workflows/
├── issue-triage/                   # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── prefetch.sh                 # prefetch: issue, labels snapshot,
                                    #   similar issues, comment history
    ├── reproduce.md                # phase 1: investigation prompt
    ├── finalize.md                 # phase 2: outcome-drafting prompt
    └── apply_triage_outputs.py     # deterministic safe-outputs applier
└── issue-to-pr/                    # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── prefetch.sh                 # prefetch: issue state, PR template,
                                    #   open-PR guard, triage-run reuse
    ├── implement.md                # phase 1: implementation prompt
    ├── prepare_pr.md               # phase 2: title/labels prep (description
                                    #   is written by the human at the gate)
    └── create_pr.py                # deterministic draft-PR applier
└── pr-review/                      # one directory per workflow, assets flat
    ├── workflow.yaml               # workflow definition
    ├── prefetch.sh                 # prefetch: PR state, files, prior reviews,
                                    #   PR worktree checkout
    ├── review.md                   # review prompt
    └── submit_review.py            # deterministic review applier
```

Per-run artifacts are kept (not cleaned up) for review, git-ignored:

```
workflows/<workflow>/.runs/<issue>/
├── data/       # prefetched issue, comments, similar issues / PR template,
                #   and a copy of the shared label snapshot (labels.json)
└── scratch/    # work environment: git worktree of the Wagtail checkout, venv,
                #   notes, diffs, and the step's decision output
```

When `issue-to-pr` reuses an `issue-triage` run, the worktree and venv are
symlinked into its own `.runs/<issue>/scratch/` (`wt` and `venv`), so the
environments are shared rather than duplicated — don't delete the originals.

Both workflows share the repo-root `skills/` and `data/labels.json` via
relative paths, so shared knowledge and snapshots stay in one place.

### `pr-review`

Reviews a Wagtail pull request:

- **Prefetch** fetches the PR metadata, changed files, and any existing
  reviews, then checks the PR out (detached, at `refs/pull/<n>/head`) into a
  git worktree of your local checkout and records the base SHA so the reviewer
  can `git diff <base>...HEAD`. The detached checkout avoids branch-name
  collisions with worktrees from other workflows (e.g. an issue-to-pr run
  holding the same `fix/issue-<n>` branch).
- The **reviewer agent** assesses the diff for correctness, runs the tests
  covering the changed code (shared `run-tests` skill), and verifies
  user-facing behaviour when tests don't cover it. Changelog/release-note
  entries are explicitly **not** a review gap — maintainers add them at merge
  time.
- It produces a verdict **recommendation** (`approve` / `request_changes` /
  `comment`), an overall comment, and inline line comments validated against
  the PR's changed files.
- A **sign-off gate** shows the verdict, summary, and every inline comment
  before anything is submitted: submit / revise with feedback / abandon. If
  the review ran out of time, the gate shows the partial findings marked as
  such.
- Submission is deterministic: the payload verdict must match what was signed
  off, mentions are stripped, and the review is **always submitted as a
  COMMENT review** — APPROVE / REQUEST_CHANGES are formal merge-gate verdicts
  reserved for humans.

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
conductor run issue-triage@wagtail --input issue=1234
conductor run issue-to-pr@wagtail --input issue=1234
conductor run pr-review@wagtail --input pr=5678
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

Optional inputs for `pr-review`: `repository` (default `wagtail/wagtail`) and
`wagtail_dir` (default `../../../wagtail` — the checkout the PR worktree is
created from).

You can also run the YAML directly:

```bash
conductor run workflows/issue-triage/workflow.yaml --input issue=1234
```

### Refreshing the label snapshot

Component labels come from the shared snapshot `data/labels.json`. Regenerate it when
Wagtail's labels change:

```bash
gh label list --repo wagtail/wagtail --json name,color,description --limit 400 \
  > data/labels.json
```

(If the snapshot is missing, the prefetch steps fetch a fresh one into the
run's data directory automatically.)

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
  The PR description is written by you at the gate (never by the agent), then
  validated against the repo's PR template and stripped of @-mentions before
  creation.
- `pr-review` never approves or requests changes: its reviews are always
  submitted as **COMMENT** reviews, only after the sign-off gate, from your
  own account, with @-mentions stripped.
