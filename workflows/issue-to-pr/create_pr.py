#!/usr/bin/env python3
"""Create the draft pull request for the issue-to-pr workflow.

Enforces the safe-outputs contract:
  - The PR is ALWAYS created with --draft (the agent cannot influence this).
  - The body must follow the repo's PR template: every section header from
    the template snapshot must be present, and it must link the issue via
    "Fixes #<issue>".
  - @-mentions outside code are stripped so the PR never notifies anyone.
  - Exactly one PR is created per invocation; nothing else is written.

Reads the drafting agent's structured JSON on stdin:
  { "title": str, "body": str, "head_branch": str, "base_branch": str }

Usage:
  create_pr.py <repo> <issue-number> <base-default> <data-dir> <output-path> [worktree]

Writes a JSON result object to stdout; keeps stdout clean of logs.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")
HEADER_RE = re.compile(r"^#{1,6}\s+\S")

# Changelog entries are written by maintainers when they merge the PR, never
# in the PR branch itself (a draft entry would only cause merge conflicts).
# In Wagtail these are the per-version release notes under docs/releases/ and
# the root CHANGELOG.txt (see docs/contributing/committing.md). Enforced
# deterministically against the actual diff, not just by prompt.
CHANGELOG_PREFIXES = ("docs/releases/",)
CHANGELOG_FILES = ("changelog.txt",)

# @-mentions outside code (GitHub does not linkify mentions inside fenced or
# inline code) are stripped so the PR body cannot notify anyone.
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


def gh(*args, stdin_text=None):
    return subprocess.run(
        ["gh", *args], text=True, capture_output=True, input=stdin_text
    )


def git(worktree: str, *args):
    return subprocess.run(
        ["git", "-C", worktree, *args], text=True, capture_output=True
    )


def fork_owner_from_remote(worktree: str, repo: str) -> str | None:
    """Derive the fork owner from the worktree's origin remote, or None if
    origin points at the base repository itself (or cannot be parsed)."""
    if not worktree:
        return None
    proc = git(worktree, "remote", "get-url", "origin")
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    owner, name = m.group(1), m.group(2)
    if f"{owner}/{name}".lower() == repo.lower():
        return None
    return owner


def changed_files(worktree: str, base_branch: str) -> set[str] | None:
    """Files changed on the PR branch relative to the base branch, or None if
    the worktree/diff cannot be inspected."""
    if not worktree:
        return None
    for base in (base_branch, f"origin/{base_branch}"):
        proc = git(worktree, "diff", "--name-only", f"{base}...HEAD")
        if proc.returncode == 0 and proc.stdout.strip():
            return {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return None


def main():
    if len(sys.argv) not in (6, 7):
        print(
            "usage: create_pr.py <repo> <issue-number> <base-default> "
            "<data-dir> <output-path> [worktree]",
            file=sys.stderr,
        )
        sys.exit(2)
    repo, issue_number, base_default, data_dir, out_path = sys.argv[1:6]
    worktree = sys.argv[6] if len(sys.argv) > 6 else ""

    data = json.load(sys.stdin)
    result = {
        "pr_url": None,
        "pr_number": None,
        "draft": True,
        "mentions_stripped": [],
        "errors": [],
    }

    def fail(msg: str) -> None:
        result["errors"].append(msg)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        sys.exit(1)

    title = data.get("title", "").strip() if isinstance(data.get("title"), str) else ""
    body = data.get("body", "").strip() if isinstance(data.get("body"), str) else ""
    head_branch = data.get("head_branch", "").strip()
    base_branch = data.get("base_branch", "").strip() or base_default

    if not title:
        fail("validation failed: empty PR title")
    if not BRANCH_RE.match(head_branch):
        fail(f"validation failed: suspicious head branch name {head_branch!r}")
    if not BRANCH_RE.match(base_branch):
        fail(f"validation failed: suspicious base branch name {base_branch!r}")

    # The body must link the issue per the template ("Fixes #<n>").
    if not re.search(rf"Fixes\s+#{re.escape(issue_number)}\b", body, re.IGNORECASE):
        fail(f"validation failed: body does not contain 'Fixes #{issue_number}'")

    # The body must carry every section header of the repo's PR template.
    template_path = Path(data_dir) / "pr_template.md"
    if template_path.exists() and template_path.stat().st_size > 0:
        headers = [
            line.strip()
            for line in template_path.read_text(encoding="utf-8").splitlines()
            if HEADER_RE.match(line)
        ]
        missing = [h for h in headers if h not in body]
        if missing:
            fail(
                "validation failed: PR body is missing required template "
                f"section(s): {missing}"
            )
    else:
        result["errors"].append("warning: no PR template snapshot; header check skipped")

    # Changelog backstop: no changelog/release-notes file may be modified on
    # the PR branch — maintainers write those entries at merge time.
    files = changed_files(worktree, base_branch)
    if files is not None:
        touched = [
            f for f in files
            if f.lower() in CHANGELOG_FILES
            or any(f.lower().startswith(p) for p in CHANGELOG_PREFIXES)
        ]
        if touched:
            fail(
                "validation failed: PR branch modifies changelog file(s) "
                f"{touched} — release-notes and CHANGELOG.txt entries are "
                "written by maintainers when merging; remove the change and "
                "cover it in the PR description instead"
            )
    elif files is None and worktree:
        result["errors"].append(
            "warning: could not diff the worktree against the base; "
            "changelog check skipped"
        )

    # Never mention users: strip @-mentions outside code so the PR cannot
    # notify anyone.
    body, mention_names = strip_mentions(body)
    if mention_names:
        result["mentions_stripped"] = mention_names

    # Resolve the fork owner: trust the implementation agent's push target if
    # it provided one, otherwise derive it from the worktree's origin remote,
    # falling back to the authenticated gh account.
    fork_owner = (data.get("fork_owner") or "").strip() or None
    if not fork_owner:
        fork_owner = fork_owner_from_remote(worktree, repo)
    if not fork_owner:
        proc = gh("api", "user", "--jq", ".login")
        if proc.returncode == 0:
            fork_owner = proc.stdout.strip()
    if not fork_owner:
        fail("could not determine the fork owner to open the PR from")

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(body)
        body_file = fh.name

    proc = gh(
        "pr", "create",
        "--repo", repo,
        "--draft",  # PRs from this workflow are always opened as drafts
        "--head", f"{fork_owner}:{head_branch}",
        "--base", base_branch,
        "--title", title,
        "--body-file", body_file,
    )
    if proc.returncode != 0:
        fail(f"gh pr create failed: {proc.stderr.strip()}")

    url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    m = re.search(r"/pull/(\d+)", url)
    result["pr_url"] = url or None
    result["pr_number"] = int(m.group(1)) if m else None

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
