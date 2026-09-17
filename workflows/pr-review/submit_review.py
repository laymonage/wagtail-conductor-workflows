#!/usr/bin/env python3
"""Submit the signed-off review for the pr-review workflow.

Enforces the safe-outputs contract:
  - The verdict signed off at the gate must match the payload file the review
    agent wrote (no drift between what was approved and what is submitted).
  - Only APPROVE / REQUEST_CHANGES / COMMENT reviews are possible; there is no
    dismiss, merge, or any other write.
  - Inline comments are validated: path must be one of the PR's changed files,
    line numbers must be sane, bodies non-empty; invalid ones are dropped and
    recorded, never silently.
  - @-mentions outside code are stripped from every body.

Reads the review payload the agent wrote (verdict/overall_comment/comments)
from <payload-path>, and the agent's structured output on stdin (used to
cross-check the verdict that was signed off).

Usage:
  submit_review.py <repo> <pr-number> <data-dir> <payload-path> <output-path>

Writes a JSON result object to stdout; keeps stdout clean of logs.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

VERDICT_EVENTS = {
    "approve": "COMMENT",
    "request_changes": "COMMENT",
    "comment": "COMMENT",
}

# Reviews from this workflow are ALWAYS submitted as COMMENT reviews —
# APPROVE / REQUEST_CHANGES are formal merge-gate verdicts reserved for
# humans. The agent's verdict remains in the payload as its recommendation
# for the human sign-off, but never becomes the submitted GitHub event.

# @-mentions outside code (GitHub does not linkify mentions inside fenced or
# inline code) are stripped so the review cannot notify anyone.
SEGMENT_RE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)
MENTION_RE = re.compile(r"(^|\s)@([A-Za-z0-9][A-Za-z0-9-]{0,37})")


def strip_mentions(text: str) -> tuple[str, list[str]]:
    """Remove @-mentions outside code blocks/spans; return (text, names)."""
    parts = SEGMENT_RE.split(text)
    stripped: list[str] = []
    names: list[str] = []
    for part in parts:
        if part.startswith("`"):
            stripped.append(part)
            continue

        def _repl(m: re.Match) -> str:
            names.append(m.group(2))
            return f"{m.group(1)}{m.group(2)}"

        stripped.append(MENTION_RE.sub(_repl, part))
    return "".join(stripped), names


def gh(*args):
    return subprocess.run(["gh", *args], text=True, capture_output=True)


def main():
    if len(sys.argv) != 6:
        print(
            "usage: submit_review.py <repo> <pr-number> <data-dir> "
            "<payload-path> <output-path>",
            file=sys.stderr,
        )
        sys.exit(2)
    repo, pr_number, data_dir, payload_path, out_path = sys.argv[1:6]

    agent_output = json.load(sys.stdin)
    result = {
        "review_url": None,
        "event": None,
        "comments_submitted": 0,
        "comments_dropped": [],
        "mentions_stripped": [],
        "errors": [],
    }

    def fail(msg: str) -> None:
        result["errors"].append(msg)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"could not read review payload: {exc}")

    # --- verdict: allowlist + cross-check against the signed-off output ------
    verdict = payload.get("verdict")
    if verdict not in VERDICT_EVENTS:
        fail(f"validation failed: invalid verdict {verdict!r}")
    signed_off = agent_output.get("verdict")
    if signed_off != verdict:
        fail(
            "validation failed: payload verdict "
            f"({verdict!r}) does not match the verdict signed off at the gate "
            f"({signed_off!r})"
        )

    # --- overall body ---------------------------------------------------------
    overall = payload.get("overall_comment")
    if overall is not None and not isinstance(overall, str):
        fail("validation failed: overall_comment must be a string or null")
    overall = (overall or "").strip()

    # --- inline comments: validate against the PR's changed files -------------
    try:
        changed = set(
            json.loads((Path(data_dir) / "files.json").read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError):
        changed = None
        result["errors"].append(
            "warning: unreadable files.json; changed-file check skipped"
        )

    comments = []
    mentions: list[str] = []
    for i, c in enumerate(payload.get("comments") or []):
        drop_prefix = f"comment {i}"
        if not isinstance(c, dict):
            result["comments_dropped"].append(f"{drop_prefix}: not an object")
            continue
        path, body = c.get("path"), c.get("body")
        line, start_line = c.get("line"), c.get("start_line")
        if not isinstance(path, str) or not path.strip():
            result["comments_dropped"].append(f"{drop_prefix}: missing path")
            continue
        if changed is not None and path not in changed:
            result["comments_dropped"].append(
                f"{drop_prefix}: path {path!r} is not among the PR's changed files"
            )
            continue
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            result["comments_dropped"].append(f"{drop_prefix}: bad line {line!r}")
            continue
        if start_line is not None and (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or start_line < 1
            or start_line >= line
        ):
            result["comments_dropped"].append(
                f"{drop_prefix}: bad start_line {start_line!r} (must be < line)"
            )
            continue
        if not isinstance(body, str) or not body.strip():
            result["comments_dropped"].append(f"{drop_prefix}: empty body")
            continue
        body, names = strip_mentions(body)
        mentions.extend(names)
        comment = {"path": path, "line": line, "body": body}
        if start_line is not None:
            comment["start_line"] = start_line
            comment["start_side"] = "RIGHT"
        comments.append(comment)
    result["mentions_stripped"] = sorted(set(mentions))

    if not overall and not comments:
        fail("validation failed: nothing to submit (empty body and no comments)")

    review: dict = {"event": VERDICT_EVENTS[verdict]}
    if overall:
        review["body"] = overall
    if comments:
        review["comments"] = comments

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(review, fh)
        payload_file = fh.name

    proc = gh("api", f"repos/{repo}/pulls/{pr_number}/reviews", "--input", payload_file)
    if proc.returncode != 0:
        fail(f"gh api reviews failed: {proc.stderr.strip()}")

    try:
        response = json.loads(proc.stdout)
        result["review_url"] = response.get("html_url")
    except json.JSONDecodeError:
        result["errors"].append("warning: could not parse the review response")

    result["event"] = VERDICT_EVENTS[verdict]
    result["comments_submitted"] = len(comments)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
