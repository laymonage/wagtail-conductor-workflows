# Wagtail Issue → Pull Request — Phase 2: Prepare the PR

You are preparing a **draft pull request** for issue #{{ workflow.input.issue }} in `{{ workflow.input.repository }}`: a title proposal, branch verification, and labels. **You do not write the PR description** — that is written by the human at the sign-off gate (Wagtail's contributing guidelines ask that PR descriptions be human-written), so don't draft one, not even as a suggestion.

A deterministic step will create the PR from your output plus the human's description — you write no GitHub content yourself.

## Inputs

- `{{ prefetch_context.output.run_dir }}/data/issue.json` — the issue being addressed.
- The implementation agent's summary, tests, and branch (in your context).
- The actual work: in the worktree at {{ implement_fix.output.worktree_used }}, run
  `git log --oneline <default-branch>..HEAD` and `git diff <default-branch>...HEAD`
  (fetch the base remote first if needed) so your title proposal and labels match the code, not just the summary.

## Requirements

1. **Title** — a concise, imperative summary of the change (e.g. "Fix redirects signal handler firing twice on page move"). No issue-number prefix, no tags, no @-mentions. This is a proposal — the human may edit it at the gate.
2. `head_branch` must be exactly the branch the implementation agent pushed; `base_branch` defaults to `{{ workflow.input.base_branch }}` — only change it if the diff clearly targets another base.
3. **Labels** — choose what the PR should be labelled with, returned in `labels_to_add`:
   - Up to **3 `component:*` labels** (most specific first), chosen with the same care as issue triage: start from the issue's existing component labels, but verify against what the change actually touches and adjust if needed. Only propose labels that exist in the snapshot at `{{ prefetch_context.output.run_dir }}/data/labels.json`.
   - Exactly **one `type:*` label** (`type:Bug`, `type:Enhancement`, or `type:Cleanup/Optimisation`) — normally the issue's own type label, since the PR implements that issue.
   - Do **not** include `status:*` labels: the apply step adds `status:Needs Review` automatically when creating the PR.
   - Fewer labels is better than wrong labels — return an empty list rather than guess.

## Output contract

- `action` — `create` to open the draft PR, `noop` if there is nothing to open (e.g. the implementation produced no commits).
- `noop_reason` — short reason when `action` is `noop`, else `null`.
- `title` — the proposed PR title.
- `head_branch` — the branch to open the PR from.
- `base_branch` — the branch to merge into.
- `labels_to_add` — array of `component:*` (max 3) and exactly one `type:*` label to apply to the PR; empty if none apply with confidence.
