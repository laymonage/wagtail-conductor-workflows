#!/usr/bin/env bash
# Prefetch for the issue-to-pr workflow: fetch the issue + comment history,
# snapshot the repo's PR template, check for open PRs already referencing the
# issue, and reuse prior issue-triage run artifacts when available (copying
# the useful ones, symlinking the heavyweight worktree/venv).
#
# Usage: prefetch.sh <issue-number> <repo> <triage-runs-dir> <workflow-dir>
# Relative <triage-runs-dir> resolves against <workflow-dir>.
# Emits a JSON object on stdout (auto-merged into the step's output).
set -euo pipefail

ISSUE_NUMBER="$1"
REPO="$2"
TRIAGE_RUNS="$3"
WF_DIR="$4"

case "$TRIAGE_RUNS" in
  /*) ;;
  *) TRIAGE_RUNS="$WF_DIR/$TRIAGE_RUNS" ;;
esac

RUN_DIR="$WF_DIR/.runs/$ISSUE_NUMBER"
DATA_DIR="$RUN_DIR/data"
SCRATCH="$RUN_DIR/scratch"
mkdir -p "$DATA_DIR" "$SCRATCH"

# --- Fresh issue state and full comment history -----------------------------
gh api "repos/$REPO/issues/$ISSUE_NUMBER" \
  --jq '{number, title, body, state, author: .user.login, author_association, labels: [.labels[].name]}' \
  > "$DATA_DIR/issue.json"

gh api "repos/$REPO/issues/$ISSUE_NUMBER/comments" --paginate \
  > "$DATA_DIR/comments.json"

# --- Open PRs already referencing this issue (duplicate-PR guard) -----------
TITLE="$(jq -r .title "$DATA_DIR/issue.json")"
gh pr list --repo "$REPO" --state open --limit 30 \
  --search "$TITLE" \
  --json number,title,headRefName,author,url \
  > "$DATA_DIR/open_prs.json" || echo '[]' > "$DATA_DIR/open_prs.json"

# --- PR template snapshot ----------------------------------------------------
# The PR-drafting agent must fill this template; create_pr.py extracts the
# required section headers from the same file to validate the body.
pr_template_found=false
for p in ".github/PULL_REQUEST_TEMPLATE.md" \
         "PULL_REQUEST_TEMPLATE.md" \
         ".github/PULL_REQUEST_TEMPLATE/pull_request_template.md" \
         "docs/PULL_REQUEST_TEMPLATE.md"; do
  if gh api "repos/$REPO/contents/$p" --jq '.content' 2>/dev/null \
      | base64 -d > "$DATA_DIR/pr_template.md" 2>/dev/null \
      && [ -s "$DATA_DIR/pr_template.md" ]; then
    pr_template_found=true
    break
  fi
done
if [ "$pr_template_found" = false ]; then
  echo "" > "$DATA_DIR/pr_template.md"
fi

# --- Label snapshot ----------------------------------------------------------
# The PR gets component:*/type:* labels chosen from the same snapshot the
# issue-triage workflow uses — the shared one at the repo root — copied into
# the run's data dir, or fetched fresh if the snapshot is missing.
if [ ! -s "$DATA_DIR/labels.json" ]; then
  if [ -s "$WF_DIR/../../data/labels.json" ]; then
    cp "$WF_DIR/../../data/labels.json" "$DATA_DIR/labels.json"
  else
    gh label list --repo "$REPO" --json name,color,description --limit 400 \
      > "$DATA_DIR/labels.json"
  fi
fi

# --- Reuse prior issue-triage run artifacts ---------------------------------
prior_run=false
reused_worktree=""
reused_venv=""
PRIOR="$TRIAGE_RUNS/$ISSUE_NUMBER"
if [ -d "$PRIOR" ] && [ "$PRIOR" != "$RUN_DIR" ]; then
  prior_run=true
  mkdir -p "$SCRATCH/prior-triage"
  for f in NOTES.md triage-output.json; do
    [ -f "$PRIOR/scratch/$f" ] && cp "$PRIOR/scratch/$f" "$SCRATCH/prior-triage/$f"
  done
  [ -f "$PRIOR/scratch/new_body.md" ] \
    && cp "$PRIOR/scratch/new_body.md" "$SCRATCH/prior-triage/new_body.md"
  if [ -d "$PRIOR/scratch/diffs" ]; then
    cp -R "$PRIOR/scratch/diffs" "$SCRATCH/prior-triage/diffs"
  fi

  # Detect a Wagtail git worktree (dir with a .git *file*) and a venv (dir
  # with pyvenv.cfg) in the prior run's scratch, and symlink rather than copy
  # so the heavy environments are shared, not duplicated.
  for d in "$PRIOR/scratch"/*/; do
    [ -d "$d" ] || continue
    if [ -f "$d/.git" ] && [ ! -f "$d/pyvenv.cfg" ]; then
      reused_worktree="$(cd "$d" && pwd)"
    fi
    if [ -f "$d/pyvenv.cfg" ]; then
      reused_venv="$(cd "$d" && pwd)"
    fi
  done
  [ -n "$reused_worktree" ] && ln -sfn "$reused_worktree" "$SCRATCH/wt"
  [ -n "$reused_venv" ] && ln -sfn "$reused_venv" "$SCRATCH/venv"
fi

jq -n \
  --argjson prior_run "$prior_run" \
  --arg reused_worktree "$reused_worktree" \
  --arg reused_venv "$reused_venv" \
  --argjson pr_template_found "$pr_template_found" \
  --arg run_dir "$RUN_DIR" \
  '{prior_run: $prior_run,
    reused_worktree: (if $reused_worktree == "" then null else $reused_worktree end),
    reused_venv: (if $reused_venv == "" then null else $reused_venv end),
    pr_template_found: $pr_template_found,
    run_dir: $run_dir}'
