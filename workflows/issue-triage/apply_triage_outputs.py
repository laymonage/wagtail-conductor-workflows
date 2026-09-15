#!/usr/bin/env python3
"""Apply triage outputs to a GitHub issue.

Enforces the safe-outputs contract of the original workflow:
  add-labels:    allowed "component:*", "status:Needs Community Feedback" and
                 "status:Needs Info", max 4
  remove-labels: allowed "status:Unconfirmed" and "status:Needs Review", max 1
  update-issue:  body only, max 1
  add-comment:   max 1

Reads the triage agent's structured JSON output on stdin:
  { "comment": str|null, "labels_to_add": [..], "labels_to_remove": [..],
    "issue_body": str|null }

Usage: apply_triage_outputs.py <repo> <issue-number> [output-path]
Writes a JSON result object to stdout; keeps stdout clean of logs.
When <output-path> is given, the triage agent's raw JSON decision is also
written there (for review alongside the reproduction artifacts in scratch/).
"""
import json
import subprocess
import sys
from pathlib import Path

ALLOWED_ADD_PREFIXES = ("component:",)
ALLOWED_ADD_EXACT = ("status:Needs Community Feedback", "status:Needs Info")
ALLOWED_REMOVE = ("status:Unconfirmed", "status:Needs Review")
MAX_ADD = 4
MAX_REMOVE = 1

# Prepended to every posted comment so readers know a machine wrote it.
DISCLAIMER = (
    "> [!NOTE]\n"
    "> This comment was posted by an automated AI triage agent and may contain\n"
    "> mistakes. Please verify its findings before relying on them.\n"
)


def gh(*args, stdin_text=None):
    return subprocess.run(
        ["gh", *args], text=True, capture_output=True, input=stdin_text
    )


def main():
    if len(sys.argv) not in (3, 4):
        print(
            "usage: apply_triage_outputs.py <repo> <issue-number> [output-path]",
            file=sys.stderr,
        )
        sys.exit(2)
    repo, issue_number = sys.argv[1], sys.argv[2]

    data = json.load(sys.stdin)
    result = {
        "labels_added": [],
        "labels_removed": [],
        "body_updated": False,
        "comment_posted": False,
        "errors": [],
    }

    # Preserve the triage agent's decision in the scratch dir for review.
    if len(sys.argv) > 3:
        out_path = Path(sys.argv[3])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result["output_saved_to"] = str(out_path)

    # --- add-labels (allowlist + cap) ---
    adds = []
    for label in data.get("labels_to_add") or []:
        if not isinstance(label, str):
            continue
        if label.startswith(ALLOWED_ADD_PREFIXES) or label in ALLOWED_ADD_EXACT:
            adds.append(label)
    adds = list(dict.fromkeys(adds))[:MAX_ADD]
    if adds:
        args = ["issue", "edit", issue_number, "--repo", repo]
        for label in adds:
            args += ["--add-label", label]
        proc = gh(*args)
        if proc.returncode == 0:
            result["labels_added"] = adds
        else:
            result["errors"].append(f"add-labels failed: {proc.stderr.strip()}")

    # --- remove-labels (allowlist + cap) ---
    removes = [
        label
        for label in (data.get("labels_to_remove") or [])
        if isinstance(label, str) and label in ALLOWED_REMOVE
    ]
    removes = list(dict.fromkeys(removes))[:MAX_REMOVE]
    if removes:
        args = ["issue", "edit", issue_number, "--repo", repo]
        for label in removes:
            args += ["--remove-label", label]
        proc = gh(*args)
        if proc.returncode == 0:
            result["labels_removed"] = removes
        else:
            result["errors"].append(f"remove-labels failed: {proc.stderr.strip()}")

    # --- update-issue (body only) ---
    body = data.get("issue_body")
    if isinstance(body, str) and body.strip():
        proc = gh(
            "issue", "edit", issue_number, "--repo", repo,
            "--body-file", "-", stdin_text=body,
        )
        if proc.returncode == 0:
            result["body_updated"] = True
        else:
            result["errors"].append(f"update-issue failed: {proc.stderr.strip()}")

    # --- add-comment (exactly one) ---
    comment = data.get("comment")
    if isinstance(comment, str) and comment.strip():
        # Tag the comment so future runs can detect prior triage (re-triage logic
        # matches on this marker instead of bot accounts, since locally the
        # comment is posted from the user's own gh account).
        MARKER = "<!-- workflow:issue-triage -->"
        if MARKER not in comment:
            comment = comment.rstrip() + f"\n\n{MARKER}\n"
        # AI disclaimer at the top, deduped in case the agent already included it.
        if "automated AI triage agent" not in comment[:300]:
            comment = DISCLAIMER + "\n" + comment.lstrip()
        proc = gh(
            "issue", "comment", issue_number, "--repo", repo,
            "--body-file", "-", stdin_text=comment,
        )
        if proc.returncode == 0:
            result["comment_posted"] = True
        else:
            result["errors"].append(f"add-comment failed: {proc.stderr.strip()}")

    print(json.dumps(result))


if __name__ == "__main__":
    main()
