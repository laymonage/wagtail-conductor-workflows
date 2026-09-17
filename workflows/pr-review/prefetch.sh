#!/usr/bin/env bash
# Prefetch for the pr-review workflow: fetch the PR metadata, changed files,
# and existing reviews; check the PR out into a git worktree of the local
# Wagtail checkout; and record the base SHA so the reviewer can diff against
# the right point.
#
# Usage: prefetch.sh <pr-number> <repo> <wagtail-dir> <workflow-dir>
# Relative <wagtail-dir> resolves against <workflow-dir>.
# Emits a JSON object on stdout (auto-merged into the step's output).
set -euo pipefail

PR_NUMBER="$1"
REPO="$2"
WAGTAIL_DIR="$3"
WF_DIR="$4"

case "$WAGTAIL_DIR" in
  /*) ;;
  *) WAGTAIL_DIR="$WF_DIR/$WAGTAIL_DIR" ;;
esac

RUN_DIR="$WF_DIR/.runs/$PR_NUMBER"
DATA_DIR="$RUN_DIR/data"
SCRATCH="$RUN_DIR/scratch"
mkdir -p "$DATA_DIR" "$SCRATCH"

# --- PR metadata, changed files, prior reviews -------------------------------
gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json number,title,body,state,isDraft,author,baseRefName,headRefName,headRepositoryOwner,headRefOid,files \
  > "$DATA_DIR/pr.json"

PR_STATE="$(jq -r .state "$DATA_DIR/pr.json")"

if [ "$PR_STATE" != "OPEN" ]; then
  # Closed or merged: nothing to review. Emit the state and skip the rest so
  # the workflow can terminate cleanly.
  jq -n --arg state "$PR_STATE" \
    '{pr_state: $state, worktree: null, base_sha: null, head_sha: null,
      base_ref: null, head_ref: null, n_changed_files: 0, prior_reviews: 0}'
  exit 0
fi

jq '[.files[].path]' "$DATA_DIR/pr.json" > "$DATA_DIR/files.json"

gh api "repos/$REPO/pulls/$PR_NUMBER/reviews" > "$DATA_DIR/reviews.json"
gh api "repos/$REPO/pulls/$PR_NUMBER/comments" > "$DATA_DIR/review_comments.json"
PRIOR_REVIEWS="$(jq 'length' "$DATA_DIR/reviews.json")"

# --- Worktree with the PR checked out ----------------------------------------
WT="$SCRATCH/wt"
if [ ! -d "$WT" ]; then
  (cd "$WAGTAIL_DIR" && gh pr checkout "$PR_NUMBER" --repo "$REPO" \
    --worktree "$WT" > /dev/null 2>&1)
fi

# Base branch snapshot for diffing: fetch it from the base repo and record its
# SHA before gh pr checkout's own fetches clobber FETCH_HEAD.
BASE_REF="$(jq -r .baseRefName "$DATA_DIR/pr.json")"
git -C "$WT" fetch --quiet "https://github.com/$REPO" "$BASE_REF"
BASE_SHA="$(git -C "$WT" rev-parse FETCH_HEAD)"

# HEAD should now be the PR head; refresh it via the normal checkout path.
(cd "$WT" && gh pr checkout "$PR_NUMBER" --repo "$REPO" --force > /dev/null 2>&1)
HEAD_SHA="$(git -C "$WT" rev-parse HEAD)"
HEAD_REF="$(jq -r .headRefName "$DATA_DIR/pr.json")"

jq -n \
  --arg pr_state "$PR_STATE" \
  --arg pr_title "$(jq -r .title "$DATA_DIR/pr.json")" \
  --arg pr_author "$(jq -r .author.login "$DATA_DIR/pr.json")" \
  --arg worktree "$WT" \
  --arg base_sha "$BASE_SHA" \
  --arg head_sha "$HEAD_SHA" \
  --arg base_ref "$BASE_REF" \
  --arg head_ref "$HEAD_REF" \
  --argjson n_changed_files "$(jq 'length' "$DATA_DIR/files.json")" \
  --argjson prior_reviews "$PRIOR_REVIEWS" \
  '{pr_state: $pr_state, pr_title: $pr_title, pr_author: $pr_author,
    worktree: $worktree, base_sha: $base_sha,
    head_sha: $head_sha, base_ref: $base_ref, head_ref: $head_ref,
    n_changed_files: $n_changed_files, prior_reviews: $prior_reviews}'
