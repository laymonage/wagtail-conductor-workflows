# Wagtail Issue → Pull Request — Phase 2: Draft the PR

You are drafting the title and description for a **draft pull request** implementing issue #{{ workflow.input.issue }} in `{{ workflow.input.repository }}`. A deterministic step will create the PR from your output — you write no GitHub content yourself.

{% if review_gate is defined %}
**This is a revision pass.** A reviewer saw the previously drafted PR title and body and asked for changes before it was opened. Their feedback:

> {{ review_gate.output.additional_input.feedback }}

Apply the feedback to your previous draft (it is in your context as your earlier output) — keep everything that already satisfied the template and the requirements below, and change only what the feedback calls for. If the feedback reveals a problem in the code itself, do not fix code here: describe it in `noop_reason` and return `action: noop` so a human can address it.
{% endif %}

## Inputs

- `{{ prefetch_context.output.run_dir }}/data/pr_template.md` — the repository's PR template. **Your body must follow it exactly**: every section header present, in order, with the HTML guidance comments replaced by real content (do not keep the `<!-- ... -->` comments themselves).
- `{{ prefetch_context.output.run_dir }}/data/issue.json` — the issue being addressed.
- The implementation agent's summary, tests, and branch (in your context).
- The actual work: in the worktree at {{ implement_fix.output.worktree_used }}, run
  `git log --oneline <default-branch>..HEAD` and `git diff <default-branch>...HEAD`
  (fetch the base remote first if needed) so the description matches the code, not just the summary.

## Requirements

1. **Title** — a concise, imperative summary of the change (e.g. "Fix redirects signal handler firing twice on page move"). No issue-number prefix, no tags.
2. **`Fixes #{{ workflow.input.issue }}`** — must appear in the body where the template asks for the fixed issue number.
3. **Description section** — describe the problem the issue reports and how this change solves it, grounded in the actual diff. Mention anything the reviewer should look at closely, and anything deliberately left out.
4. **AI usage section** — the template requires an honest disclosure. Use wording along the lines of:
   > The code and this description were authored by an automated AI agent running the `issue-to-pr` Conductor workflow on behalf of the PR author; human review before marking it ready is strongly encouraged.
   Summarise what the agent did (implementation, tests) rather than leaving it at "None".
5. **No @-mentions** of anyone, anywhere in the title or body.
6. `head_branch` must be exactly the branch the implementation agent pushed; `base_branch` defaults to `{{ workflow.input.base_branch }}` — only change it if the diff clearly targets another base.
7. **Labels** — choose what the PR should be labelled with, returned in `labels_to_add`:
   - Up to **3 `component:*` labels** (most specific first), chosen with the same care as issue triage: start from the issue's existing component labels, but verify against what the change actually touches and adjust if needed. Only propose labels that exist in the snapshot at `{{ prefetch_context.output.run_dir }}/data/labels.json`.
   - Exactly **one `type:*` label** (`type:Bug`, `type:Enhancement`, or `type:Cleanup/Optimisation`) — normally the issue's own type label, since the PR implements that issue.
   - Do **not** include `status:*` labels: the apply step adds `status:Needs Review` automatically when creating the PR.
   - Fewer labels is better than wrong labels — return an empty list rather than guess.

## Output contract

- `action` — `create` to open the draft PR, `noop` if there is nothing to open (e.g. the implementation produced no commits).
- `noop_reason` — short reason when `action` is `noop`, else `null`.
- `title` — the PR title.
- `body` — the complete PR body following the template.
- `head_branch` — the branch to open the PR from.
- `base_branch` — the branch to merge into.
- `labels_to_add` — array of `component:*` (max 3) and exactly one `type:*` label to apply to the PR; empty if none apply with confidence.
