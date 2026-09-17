#!/usr/bin/env bash
# Prefetch for the issue-triage workflow: fetch the issue, the full comment
# history, similar issues, and (only if missing) regenerate the local label
# snapshot. Prior triage comments are derived from the comment history
# locally, so nothing else is fetched.
#
# Usage: prefetch.sh <issue-number> <repo> <workflow-dir>
# Emits a short status line on stdout; routing is exit-code based.
set -euo pipefail

ISSUE_NUMBER="$1"
REPO="$2"
WF_DIR="$3"

DATA_DIR="$WF_DIR/.runs/$ISSUE_NUMBER/data"
mkdir -p "$DATA_DIR"
# Repo root holds shared assets: data/labels.json (label snapshot) and the
# run-tests skill.
REPO_ROOT="$WF_DIR/../.."

gh api "repos/$REPO/issues/$ISSUE_NUMBER" \
  --jq '{number, title, body, author: .user.login, author_association, labels: [.labels[].name]}' \
  > "$DATA_DIR/issue.json"

# Component labels are filtered by the agent from the label snapshot; the
# shared snapshot lives at the repo root (data/labels.json) — copy it into the
# run's data dir, or fetch a fresh one if the snapshot is missing.
LABELS_FILE="$DATA_DIR/labels.json"
if [ ! -s "$LABELS_FILE" ]; then
  if [ -s "$REPO_ROOT/data/labels.json" ]; then
    cp "$REPO_ROOT/data/labels.json" "$LABELS_FILE"
  else
    echo "data/labels.json not found — fetching labels from GitHub"
    gh label list --repo "$REPO" --json name,color,description --limit 400 \
      > "$LABELS_FILE"
  fi
fi

gh issue list --repo "$REPO" --state all --limit 30 \
  --search "$(jq -r .title "$DATA_DIR/issue.json")" \
  --json number,title,state,labels \
  > "$DATA_DIR/similar_issues.json" || echo '[]' > "$DATA_DIR/similar_issues.json"

# Full comment history — prior triage runs are derived from it locally.
gh api "repos/$REPO/issues/$ISSUE_NUMBER/comments" --paginate \
  > "$DATA_DIR/comments.json"

jq '[.[] | select(.body | contains("<!-- workflow:issue-triage -->")) | {author: .user.login, created_at, body}]' \
  "$DATA_DIR/comments.json" > "$DATA_DIR/prior_triage.json"

echo "prefetched to $DATA_DIR"
