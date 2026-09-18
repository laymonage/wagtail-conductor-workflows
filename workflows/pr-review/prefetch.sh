#!/usr/bin/env bash
# Prefetch for the pr-review workflow: fetch the PR metadata, changed files,
# and existing reviews; check the PR out into a git worktree of the local
# Wagtail checkout; and record the base SHA so the reviewer can diff against
# the right point.
#
# Usage: prefetch.sh <pr-number> <repo> <wagtail-dir> <workflow-dir>
# Relative <wagtail-dir> resolves against <workflow-dir>.
#
# ALWAYS emits a JSON object on stdout with the same keys (auto-merged into
# the step's output, which route conditions reference) and always exits 0 —
# failures are reported as pr_state="ERROR" plus an error message, never as
# a missing/invalid stdout, so routing can't hit undefined variables.
set -uo pipefail

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
ERR_LOG="$RUN_DIR/prefetch-error.log"

emit() {  # emit <pr_state> <title> <author> <worktree> <base_sha> <head_sha> <base_ref> <head_ref> <n_files> <n_reviews> <error>
  jq -n \
    --arg pr_state "$1" \
    --arg pr_title "$2" \
    --arg pr_author "$3" \
    --arg worktree "$4" \
    --arg base_sha "$5" \
    --arg head_sha "$6" \
    --arg base_ref "$7" \
    --arg head_ref "$8" \
    --argjson n_changed_files "$9" \
    --argjson prior_reviews "${10}" \
    --arg error "${11}" \
    '{pr_state: $pr_state, pr_title: $pr_title, pr_author: $pr_author,
      worktree: (if $worktree == "" then null else $worktree end),
      base_sha: (if $base_sha == "" then null else $base_sha end),
      head_sha: (if $head_sha == "" then null else $head_sha end),
      base_ref: (if $base_ref == "" then null else $base_ref end),
      head_ref: (if $head_ref == "" then null else $head_ref end),
      n_changed_files: $n_changed_files, prior_reviews: $prior_reviews,
      error: $error}'
}

emit_error() {  # emit_error <message>
  echo "pr-review prefetch failed: $1" >&2
  emit "ERROR" "" "" "" "" "" "" "" 0 0 "$1"
  exit 0
}

mkdir -p "$DATA_DIR" "$SCRATCH" || emit_error "could not create run directories"

# --- PR metadata, changed files, prior reviews -------------------------------
if ! gh pr view "$PR_NUMBER" --repo "$REPO" \
    --json number,title,body,state,isDraft,author,baseRefName,headRefName,headRepositoryOwner,headRefOid,files \
    > "$DATA_DIR/pr.json" 2> "$ERR_LOG"; then
  emit_error "gh pr view failed: $(tail -1 "$ERR_LOG")"
fi

PR_TITLE="$(jq -r .title "$DATA_DIR/pr.json")"
PR_AUTHOR="$(jq -r .author.login "$DATA_DIR/pr.json")"
PR_STATE="$(jq -r .state "$DATA_DIR/pr.json")"

if [ "$PR_STATE" != "OPEN" ]; then
  # Closed or merged: nothing to review. Same JSON shape, worktree skipped.
  emit "$PR_STATE" "$PR_TITLE" "$PR_AUTHOR" "" "" "" "" "" 0 0 ""
  exit 0
fi

jq '[.files[].path]' "$DATA_DIR/pr.json" > "$DATA_DIR/files.json"

gh api "repos/$REPO/pulls/$PR_NUMBER/reviews" > "$DATA_DIR/reviews.json" 2>> "$ERR_LOG" \
  || emit_error "fetching reviews failed: $(tail -1 "$ERR_LOG")"
gh api "repos/$REPO/pulls/$PR_NUMBER/comments" > "$DATA_DIR/review_comments.json" 2>> "$ERR_LOG" \
  || emit_error "fetching review comments failed: $(tail -1 "$ERR_LOG")"
PRIOR_REVIEWS="$(jq 'length' "$DATA_DIR/reviews.json")"

# --- Worktree with the PR checked out ----------------------------------------
# Deliberately NOT `gh pr checkout`: it names the local branch after the PR's
# head branch, which collides with worktrees from other workflows (e.g. an
# issue-to-pr run holding the same `fix/issue-<n>` branch — git refuses to
# check out one branch in two worktrees). Instead, fetch GitHub's
# refs/pull/<n>/head (works for PRs from any fork) and check it out detached:
# the reviewer never commits, so no branch is needed.
WT="$SCRATCH/wt"
git -C "$WAGTAIL_DIR" worktree prune >> "$ERR_LOG" 2>&1
if [ ! -d "$WT" ]; then
  git -C "$WAGTAIL_DIR" worktree add --detach "$WT" >> "$ERR_LOG" 2>&1 \
    || emit_error "creating worktree failed: $(tail -1 "$ERR_LOG")"
fi

# Base branch snapshot for diffing: fetch it from the base repo and record its
# SHA before the PR-head fetch below clobbers FETCH_HEAD.
BASE_REF="$(jq -r .baseRefName "$DATA_DIR/pr.json")"
git -C "$WT" fetch --quiet "https://github.com/$REPO" "$BASE_REF" >> "$ERR_LOG" 2>&1 \
  || emit_error "fetching base branch $BASE_REF failed: $(tail -1 "$ERR_LOG")"
BASE_SHA="$(git -C "$WT" rev-parse FETCH_HEAD)"

# PR head, then detach onto it (idempotent on re-runs: just re-fetch + detach).
git -C "$WT" fetch --quiet "https://github.com/$REPO" "pull/$PR_NUMBER/head" >> "$ERR_LOG" 2>&1 \
  || emit_error "fetching PR head failed: $(tail -1 "$ERR_LOG")"
git -C "$WT" checkout --detach --quiet FETCH_HEAD >> "$ERR_LOG" 2>&1 \
  || emit_error "checking out PR head failed: $(tail -1 "$ERR_LOG")"
HEAD_SHA="$(git -C "$WT" rev-parse HEAD)" || emit_error "could not resolve HEAD"
HEAD_REF="$(jq -r .headRefName "$DATA_DIR/pr.json")"

rm -f "$ERR_LOG"

emit "OPEN" "$PR_TITLE" "$PR_AUTHOR" "$WT" "$BASE_SHA" "$HEAD_SHA" "$BASE_REF" "$HEAD_REF" \
  "$(jq 'length' "$DATA_DIR/files.json")" "$PRIOR_REVIEWS" ""
