#!/usr/bin/env python3
"""
Paperclip GitHub — GitHub repository interaction via REST API.

Supports: repo metadata, file CRUD, clone, issues, PRs, releases, tags, code search.
Auth via Personal Access Token. Works with both public and private repos.
"""

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("[github] Installing requests...", file=sys.stderr)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "requests", "--break-system-packages", "-q"]
    )
    import requests

API = "https://api.github.com"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _check(resp, context=""):
    """Raise on 4xx/5xx with a useful message. Returns response."""
    if resp.status_code >= 400:
        detail = resp.text[:500]
        print(f"[github] {context} — HTTP {resp.status_code}: {detail}", file=sys.stderr)
        sys.exit(1)
    return resp


def api_get(token, path, params=None):
    r = requests.get(f"{API}{path}", headers=_headers(token), params=params, timeout=30)
    _check(r, f"GET {path}")
    return r.json()


def api_post(token, path, payload):
    r = requests.post(f"{API}{path}", headers=_headers(token), json=payload, timeout=30)
    _check(r, f"POST {path}")
    return r.json()


def api_put(token, path, payload):
    r = requests.put(f"{API}{path}", headers=_headers(token), json=payload, timeout=30)
    _check(r, f"PUT {path}")
    return r.json()


def api_patch(token, path, payload):
    r = requests.patch(f"{API}{path}", headers=_headers(token), json=payload, timeout=30)
    _check(r, f"PATCH {path}")
    return r.json()


# ---------------------------------------------------------------------------
# REPO commands
# ---------------------------------------------------------------------------

def cmd_repo_info(args):
    """Get repository metadata."""
    data = api_get(args.token, f"/repos/{args.repo}")
    info = {
        "name": data["full_name"],
        "description": data.get("description"),
        "private": data["private"],
        "default_branch": data["default_branch"],
        "language": data.get("language"),
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "open_issues": data["open_issues_count"],
        "created": data["created_at"],
        "updated": data["updated_at"],
        "clone_url": data["clone_url"],
        "topics": data.get("topics", []),
        "license": (data.get("license") or {}).get("spdx_id"),
    }
    print(json.dumps(info, indent=2))


def cmd_tree(args):
    """List repository file tree."""
    if args.recursive:
        branch = args.branch or api_get(args.token, f"/repos/{args.repo}")["default_branch"]
        data = api_get(args.token, f"/repos/{args.repo}/git/trees/{branch}", {"recursive": "1"})
        for item in data.get("tree", []):
            kind = "dir" if item["type"] == "tree" else "file"
            size = f"  ({item.get('size', 0):,}b)" if item["type"] == "blob" else ""
            print(f"[{kind}] {item['path']}{size}")
        print(f"\n[github] {len(data.get('tree', []))} items total", file=sys.stderr)
        return

    path = f"/repos/{args.repo}/contents/{args.path}" if args.path else f"/repos/{args.repo}/contents/"
    params = {"ref": args.branch} if args.branch else {}
    data = api_get(args.token, path, params)

    if isinstance(data, list):
        for item in sorted(data, key=lambda x: (x["type"] != "dir", x["name"])):
            kind = "dir" if item["type"] == "dir" else "file"
            size = f"  ({item.get('size', 0):,}b)" if item["type"] == "file" else ""
            print(f"[{kind}] {item['name']}{size}")
        print(f"\n[github] {len(data)} entries", file=sys.stderr)
    else:
        print(json.dumps({"name": data["name"], "type": data["type"], "size": data.get("size")}, indent=2))


def cmd_clone(args):
    """Clone a repository to a local directory."""
    url = f"https://x-access-token:{args.token}@github.com/{args.repo}.git"
    dest = args.output or args.repo.split("/")[-1]
    cmd = ["git", "clone"]
    if args.depth:
        cmd += ["--depth", str(args.depth)]
    if args.branch:
        cmd += ["--branch", args.branch]
    cmd += [url, dest]

    print(f"[github] Cloning {args.repo} → {dest}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.replace(args.token, "***")
        print(f"[github] Clone failed: {err}", file=sys.stderr)
        sys.exit(1)
    print(f"[github] Done", file=sys.stderr)
    print(dest)


def cmd_search(args):
    """Search code within a repository."""
    query = f"{args.query} repo:{args.repo}"
    if args.language:
        query += f" language:{args.language}"
    data = api_get(args.token, "/search/code", {"q": query, "per_page": min(args.limit, 100)})
    print(f"[github] {data['total_count']} result(s) found", file=sys.stderr)
    for item in data.get("items", []):
        print(f"  {item['path']}  →  {item['html_url']}")


# ---------------------------------------------------------------------------
# FILE commands
# ---------------------------------------------------------------------------

def cmd_file_read(args):
    """Read a file's contents from the repository."""
    params = {"ref": args.branch} if args.branch else {}
    data = api_get(args.token, f"/repos/{args.repo}/contents/{args.path}", params)

    if isinstance(data, list):
        print("[github] Path is a directory — use 'tree' instead.", file=sys.stderr)
        sys.exit(1)

    if data.get("encoding") == "base64":
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    else:
        content = data.get("content", "")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(content)
        print(f"[github] Saved to {args.output} ({len(content):,} chars)", file=sys.stderr)
    else:
        print(content)

    print(f"[github] SHA: {data['sha']} | Size: {data.get('size', 0):,}b", file=sys.stderr)


def cmd_file_write(args):
    """Create or update a file (auto-detects via SHA lookup)."""
    # Check if file already exists to get its SHA for update
    sha = None
    params = {"ref": args.branch} if args.branch else {}
    r = requests.get(
        f"{API}/repos/{args.repo}/contents/{args.path}",
        headers=_headers(args.token), params=params, timeout=30,
    )
    if r.status_code == 200:
        sha = r.json()["sha"]
        print(f"[github] Updating existing file (SHA: {sha[:8]})", file=sys.stderr)
    elif r.status_code == 404:
        print("[github] Creating new file", file=sys.stderr)
    else:
        _check(r, "file existence check")

    # Resolve content: --input file > --content string > stdin
    if args.input:
        raw = Path(args.input).read_bytes()
    elif args.content:
        raw = args.content.encode()
    else:
        raw = sys.stdin.buffer.read()

    payload = {
        "message": args.message or f"{'Update' if sha else 'Create'} {args.path}",
        "content": base64.b64encode(raw).decode(),
    }
    if sha:
        payload["sha"] = sha
    if args.branch:
        payload["branch"] = args.branch

    result = api_put(args.token, f"/repos/{args.repo}/contents/{args.path}", payload)
    print(json.dumps({
        "path": result["content"]["path"],
        "sha": result["content"]["sha"],
        "commit": result["commit"]["sha"],
        "message": result["commit"]["message"],
        "url": result["content"]["html_url"],
    }, indent=2))


def cmd_file_delete(args):
    """Delete a file from the repository."""
    params = {"ref": args.branch} if args.branch else {}
    existing = api_get(args.token, f"/repos/{args.repo}/contents/{args.path}", params)

    payload = {
        "message": args.message or f"Delete {args.path}",
        "sha": existing["sha"],
    }
    if args.branch:
        payload["branch"] = args.branch

    r = requests.delete(
        f"{API}/repos/{args.repo}/contents/{args.path}",
        headers=_headers(args.token), json=payload, timeout=30,
    )
    _check(r, f"DELETE {args.path}")
    print(f"[github] Deleted {args.path}", file=sys.stderr)
    print(json.dumps({"deleted": args.path, "commit": r.json()["commit"]["sha"]}))


# ---------------------------------------------------------------------------
# ISSUE commands
# ---------------------------------------------------------------------------

def cmd_issue_list(args):
    """List issues (excludes pull requests)."""
    params = {"state": args.state, "per_page": min(args.limit, 100)}
    if args.labels:
        params["labels"] = args.labels
    if args.assignee:
        params["assignee"] = args.assignee
    data = api_get(args.token, f"/repos/{args.repo}/issues", params)
    issues = [i for i in data if "pull_request" not in i]
    for issue in issues:
        labels = ", ".join(l["name"] for l in issue.get("labels", []))
        assignee = (issue.get("assignee") or {}).get("login", "—")
        print(f"#{issue['number']}  [{issue['state']}]  {issue['title']}")
        if labels or assignee != "—":
            print(f"        by {issue['user']['login']} | assigned: {assignee} | labels: {labels or '—'}")
    print(f"\n[github] {len(issues)} issue(s)", file=sys.stderr)


def cmd_issue_create(args):
    """Create a new issue."""
    payload = {"title": args.title}
    if args.body:
        payload["body"] = args.body
    if args.labels:
        payload["labels"] = [l.strip() for l in args.labels.split(",")]
    if args.assignees:
        payload["assignees"] = [a.strip() for a in args.assignees.split(",")]
    data = api_post(args.token, f"/repos/{args.repo}/issues", payload)
    print(json.dumps({
        "number": data["number"],
        "url": data["html_url"],
        "title": data["title"],
    }, indent=2))


def cmd_issue_comment(args):
    """Add a comment to an issue."""
    data = api_post(args.token, f"/repos/{args.repo}/issues/{args.number}/comments", {"body": args.body})
    print(json.dumps({"id": data["id"], "url": data["html_url"]}, indent=2))


def cmd_issue_update(args):
    """Update issue state, title, labels, or assignees."""
    payload = {}
    if args.state:
        payload["state"] = args.state
    if args.title:
        payload["title"] = args.title
    if args.labels is not None:
        payload["labels"] = [l.strip() for l in args.labels.split(",")] if args.labels else []
    if args.assignees is not None:
        payload["assignees"] = [a.strip() for a in args.assignees.split(",")] if args.assignees else []
    if not payload:
        print("[github] Nothing to update — specify at least one of --state, --title, --labels, --assignees", file=sys.stderr)
        sys.exit(1)
    data = api_patch(args.token, f"/repos/{args.repo}/issues/{args.number}", payload)
    print(json.dumps({
        "number": data["number"],
        "state": data["state"],
        "title": data["title"],
        "url": data["html_url"],
    }, indent=2))


# ---------------------------------------------------------------------------
# PULL REQUEST commands
# ---------------------------------------------------------------------------

def cmd_pr_list(args):
    """List pull requests."""
    params = {"state": args.state, "per_page": min(args.limit, 100)}
    if args.head:
        params["head"] = args.head
    if args.base:
        params["base"] = args.base
    data = api_get(args.token, f"/repos/{args.repo}/pulls", params)
    for pr in data:
        draft = " [draft]" if pr.get("draft") else ""
        print(f"#{pr['number']}  [{pr['state']}{draft}]  {pr['title']}")
        print(f"        {pr['head']['label']} → {pr['base']['label']}  by {pr['user']['login']}")
    print(f"\n[github] {len(data)} PR(s)", file=sys.stderr)


def cmd_pr_create(args):
    """Open a new pull request."""
    payload = {"title": args.title, "head": args.head, "base": args.base}
    if args.body:
        payload["body"] = args.body
    if args.draft:
        payload["draft"] = True
    data = api_post(args.token, f"/repos/{args.repo}/pulls", payload)
    print(json.dumps({
        "number": data["number"],
        "url": data["html_url"],
        "title": data["title"],
        "state": data["state"],
        "draft": data.get("draft", False),
    }, indent=2))


def cmd_pr_comment(args):
    """Comment on a pull request (uses the issues endpoint — same in GitHub API)."""
    data = api_post(args.token, f"/repos/{args.repo}/issues/{args.number}/comments", {"body": args.body})
    print(json.dumps({"id": data["id"], "url": data["html_url"]}, indent=2))


def cmd_pr_merge(args):
    """Merge a pull request."""
    payload = {}
    if args.method:
        payload["merge_method"] = args.method
    if args.message:
        payload["commit_message"] = args.message
    r = requests.put(
        f"{API}/repos/{args.repo}/pulls/{args.number}/merge",
        headers=_headers(args.token), json=payload, timeout=30,
    )
    _check(r, f"merge PR #{args.number}")
    data = r.json()
    print(json.dumps({
        "merged": data.get("merged", False),
        "sha": data.get("sha"),
        "message": data.get("message"),
    }, indent=2))


# ---------------------------------------------------------------------------
# RELEASE / TAG commands
# ---------------------------------------------------------------------------

def cmd_release_list(args):
    """List releases."""
    data = api_get(args.token, f"/repos/{args.repo}/releases", {"per_page": min(args.limit, 100)})
    for rel in data:
        flags = ""
        if rel["prerelease"]:
            flags += " [pre-release]"
        if rel["draft"]:
            flags += " [draft]"
        print(f"{rel['tag_name']}{flags}  —  {rel.get('name') or '(untitled)'}")
        print(f"        by {rel['author']['login']} | {rel.get('published_at') or 'unpublished'}")
        for asset in rel.get("assets", []):
            print(f"        📦 {asset['name']} ({asset['size']:,}b)")
    print(f"\n[github] {len(data)} release(s)", file=sys.stderr)


def cmd_release_get(args):
    """Get details for a specific release by tag or 'latest'."""
    if args.tag == "latest":
        data = api_get(args.token, f"/repos/{args.repo}/releases/latest")
    else:
        data = api_get(args.token, f"/repos/{args.repo}/releases/tags/{args.tag}")
    print(json.dumps({
        "tag": data["tag_name"],
        "name": data.get("name"),
        "body": data.get("body"),
        "prerelease": data["prerelease"],
        "draft": data["draft"],
        "published": data.get("published_at"),
        "url": data["html_url"],
        "assets": [
            {"name": a["name"], "size": a["size"], "download": a["browser_download_url"]}
            for a in data.get("assets", [])
        ],
    }, indent=2))


def cmd_tag_list(args):
    """List tags."""
    data = api_get(args.token, f"/repos/{args.repo}/tags", {"per_page": min(args.limit, 100)})
    for tag in data:
        print(f"{tag['name']}  →  {tag['commit']['sha'][:10]}")
    print(f"\n[github] {len(data)} tag(s)", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="Paperclip GitHub — interact with GitHub repos via REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--token", required=True, help="GitHub Personal Access Token (never logged)")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # -- repo-info --
    s = sub.add_parser("repo-info", help="Repository metadata")
    s.add_argument("--repo", required=True, help="owner/repo")

    # -- tree --
    s = sub.add_parser("tree", help="List files in repo")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--path", default=None, help="Subdirectory (omit for root)")
    s.add_argument("--branch", default=None, help="Branch or tag (default: repo default)")
    s.add_argument("--recursive", action="store_true", help="Full recursive listing")

    # -- clone --
    s = sub.add_parser("clone", help="Clone repo locally")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--output", default=None, help="Destination directory")
    s.add_argument("--branch", default=None)
    s.add_argument("--depth", type=int, default=None, help="Shallow clone depth")

    # -- search --
    s = sub.add_parser("search", help="Search code in repo")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--query", required=True, help="Search terms")
    s.add_argument("--language", default=None, help="Filter by language")
    s.add_argument("--limit", type=int, default=10)

    # -- file-read --
    s = sub.add_parser("file-read", help="Read a file")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--path", required=True, help="File path in repo")
    s.add_argument("--branch", default=None)
    s.add_argument("--output", default=None, help="Save to local path (else stdout)")

    # -- file-write --
    s = sub.add_parser("file-write", help="Create or update a file")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--path", required=True, help="File path in repo")
    s.add_argument("--input", default=None, help="Local file to upload")
    s.add_argument("--content", default=None, help="Inline content string")
    s.add_argument("--message", default=None, help="Commit message")
    s.add_argument("--branch", default=None)

    # -- file-delete --
    s = sub.add_parser("file-delete", help="Delete a file")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--path", required=True, help="File path in repo")
    s.add_argument("--message", default=None, help="Commit message")
    s.add_argument("--branch", default=None)

    # -- issue-list --
    s = sub.add_parser("issue-list", help="List issues")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--state", default="open", choices=["open", "closed", "all"])
    s.add_argument("--labels", default=None, help="Comma-separated label filter")
    s.add_argument("--assignee", default=None)
    s.add_argument("--limit", type=int, default=30)

    # -- issue-create --
    s = sub.add_parser("issue-create", help="Create an issue")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--title", required=True)
    s.add_argument("--body", default=None)
    s.add_argument("--labels", default=None, help="Comma-separated")
    s.add_argument("--assignees", default=None, help="Comma-separated usernames")

    # -- issue-comment --
    s = sub.add_parser("issue-comment", help="Comment on an issue")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--number", type=int, required=True)
    s.add_argument("--body", required=True)

    # -- issue-update --
    s = sub.add_parser("issue-update", help="Update an issue")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--number", type=int, required=True)
    s.add_argument("--state", default=None, choices=["open", "closed"])
    s.add_argument("--title", default=None)
    s.add_argument("--labels", default=None, help="Comma-separated (empty string clears)")
    s.add_argument("--assignees", default=None, help="Comma-separated (empty string clears)")

    # -- pr-list --
    s = sub.add_parser("pr-list", help="List pull requests")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--state", default="open", choices=["open", "closed", "all"])
    s.add_argument("--head", default=None, help="Filter by head (user:branch)")
    s.add_argument("--base", default=None, help="Filter by base branch")
    s.add_argument("--limit", type=int, default=30)

    # -- pr-create --
    s = sub.add_parser("pr-create", help="Create a pull request")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--title", required=True)
    s.add_argument("--head", required=True, help="Source branch")
    s.add_argument("--base", required=True, help="Target branch")
    s.add_argument("--body", default=None)
    s.add_argument("--draft", action="store_true")

    # -- pr-comment --
    s = sub.add_parser("pr-comment", help="Comment on a PR")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--number", type=int, required=True)
    s.add_argument("--body", required=True)

    # -- pr-merge --
    s = sub.add_parser("pr-merge", help="Merge a pull request")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--number", type=int, required=True)
    s.add_argument("--method", default=None, choices=["merge", "squash", "rebase"])
    s.add_argument("--message", default=None, help="Merge commit message")

    # -- release-list --
    s = sub.add_parser("release-list", help="List releases")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--limit", type=int, default=10)

    # -- release-get --
    s = sub.add_parser("release-get", help="Get release details")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--tag", required=True, help="Tag name or 'latest'")

    # -- tag-list --
    s = sub.add_parser("tag-list", help="List tags")
    s.add_argument("--repo", required=True, help="owner/repo")
    s.add_argument("--limit", type=int, default=30)

    return p


DISPATCH = {
    "repo-info": cmd_repo_info,
    "tree": cmd_tree,
    "clone": cmd_clone,
    "search": cmd_search,
    "file-read": cmd_file_read,
    "file-write": cmd_file_write,
    "file-delete": cmd_file_delete,
    "issue-list": cmd_issue_list,
    "issue-create": cmd_issue_create,
    "issue-comment": cmd_issue_comment,
    "issue-update": cmd_issue_update,
    "pr-list": cmd_pr_list,
    "pr-create": cmd_pr_create,
    "pr-comment": cmd_pr_comment,
    "pr-merge": cmd_pr_merge,
    "release-list": cmd_release_list,
    "release-get": cmd_release_get,
    "tag-list": cmd_tag_list,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    DISPATCH[args.command](args)


if __name__ == "__main__":
    main()
