---
name: paperclip-github
description: >
  Paperclip GitHub — interact with GitHub repositories (public and private) via REST API.
  Use any time a user or agent needs to read, write, or manage GitHub repo content.
  Covers: cloning repos, browsing file trees, reading/writing/deleting files, creating
  and managing issues, opening and merging pull requests, listing releases and tags, and
  searching code. Works with public and private repos via Personal Access Token (PAT).
  Triggers on: "clone this repo", "read the README", "list the files", "create an issue",
  "open a PR", "push this file", "check the releases", "search the codebase", "commit
  this to GitHub", "what's in this repo", or any request implying GitHub interaction.
  Also triggers when a workflow produces a file to commit, when the user references a
  GitHub URL (github.com/owner/repo), or mentions repo names in owner/repo format.
  NOT for GitHub Actions/CI, GitHub Pages, or GitHub Apps OAuth. Requires a GitHub PAT.
---

# Paperclip GitHub — Repository Interaction Skill

A self-contained CLI tool for GitHub repository operations via the REST API. Designed for
direct user requests and agent workflows where repos need to be read, written to, or managed.

Follows the same "write-script-to-tmp, call via CLI" pattern as paperclip-imagegen.

## Prerequisites

- **GitHub Personal Access Token (PAT)**: The user must supply a token in their message or
  earlier in the conversation. Classic tokens need `repo` scope for private repos; fine-grained
  tokens need appropriate repository permissions. The token is never logged or echoed to stdout.
- **Python 3.8+**: Available in the container by default.
- **`requests` library**: Auto-installed on first run if missing.
- **`git` CLI**: Required only for the `clone` command. Pre-installed in most environments.

## Setup — Deploy the Script

Before your first GitHub operation in a session, copy the bundled script to `/tmp/`. You only
need to do this once per session — check if the file exists first.

```bash
[ -f /tmp/paperclip_github.py ] || cp /mnt/skills/user/paperclip-github/scripts/paperclip_github.py /tmp/paperclip_github.py
```

All subsequent calls use `/tmp/paperclip_github.py` as the entry point.

## Quick Start

Every command follows the same pattern:

```bash
python3 /tmp/paperclip_github.py --token "<PAT>" <command> --repo owner/repo [options]
```

### Browse a repo

```bash
# Metadata
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" repo-info --repo torvalds/linux

# File tree (root)
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" tree --repo owner/repo

# Recursive full tree
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" tree --repo owner/repo --recursive

# Specific subdirectory on a branch
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" tree --repo owner/repo --path src/lib --branch develop
```

### Read and write files

```bash
# Read to stdout
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-read --repo owner/repo --path README.md

# Read and save locally
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-read --repo owner/repo --path config.json --output /tmp/config.json

# Create or update a file (auto-detects new vs existing via SHA)
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-write --repo owner/repo \
  --path docs/guide.md --input /tmp/guide.md --message "Add user guide"

# Inline content (useful for small files)
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-write --repo owner/repo \
  --path .env.example --content "API_KEY=xxx" --message "Add env template"

# Delete a file
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-delete --repo owner/repo \
  --path old-file.txt --message "Remove deprecated file"
```

### Clone a repository

```bash
# Full clone
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" clone --repo owner/repo --output /tmp/myrepo

# Shallow clone (faster for large repos)
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" clone --repo owner/repo --depth 1
```

### Issues

```bash
# List open issues
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" issue-list --repo owner/repo

# Filtered listing
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" issue-list --repo owner/repo \
  --state closed --labels "bug,critical" --limit 10

# Create an issue
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" issue-create --repo owner/repo \
  --title "Fix login timeout" --body "Users report 30s+ login times" --labels "bug"

# Comment on issue #42
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" issue-comment --repo owner/repo \
  --number 42 --body "Confirmed — reproduced on v2.1"

# Close an issue
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" issue-update --repo owner/repo \
  --number 42 --state closed
```

### Pull Requests

```bash
# List open PRs
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" pr-list --repo owner/repo

# Create a PR
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" pr-create --repo owner/repo \
  --title "Add dark mode" --head feature/dark-mode --base main --body "Implements #15"

# Merge with squash
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" pr-merge --repo owner/repo \
  --number 7 --method squash
```

### Releases and Tags

```bash
# List releases
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" release-list --repo owner/repo

# Get latest release details
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" release-get --repo owner/repo --tag latest

# Get a specific tagged release
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" release-get --repo owner/repo --tag v2.0.0

# List tags
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" tag-list --repo owner/repo
```

### Code Search

```bash
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" search --repo owner/repo \
  --query "func handleAuth" --language go
```

## Agent Workflow

Follow this decision tree when processing a GitHub-related request:

1. **Deploy the script** if `/tmp/paperclip_github.py` doesn't already exist. Run the `cp`
   command from the Setup section. Once per session.

2. **Locate the token.** Scan the current message and conversation history. If not found, ask
   the user. Never hardcode, guess, or echo a token. Store it in a shell variable:
   `GH_TOKEN="ghp_..."` and reference as `"$GH_TOKEN"` in commands.

3. **Parse the repo reference.** Users may provide:
   - `owner/repo` format → use directly
   - A full URL like `https://github.com/owner/repo` → extract `owner/repo`
   - Just a repo name → ask for the owner, or check if context makes it obvious

4. **Choose the command** based on user intent:

   | User intent                            | Command         |
   |----------------------------------------|-----------------|
   | "What's in this repo?"                 | `repo-info`     |
   | "Show me the files" / "list the tree"  | `tree`          |
   | "Read/show me this file"               | `file-read`     |
   | "Push/commit/upload this file"         | `file-write`    |
   | "Remove/delete this file"              | `file-delete`   |
   | "Clone this repo"                      | `clone`         |
   | "Find X in the code"                   | `search`        |
   | "Show me the issues" / "any open bugs" | `issue-list`    |
   | "File a bug" / "create an issue"       | `issue-create`  |
   | "Comment on issue #N"                  | `issue-comment` |
   | "Close/reopen issue #N"               | `issue-update`  |
   | "Show PRs" / "any open pull requests"  | `pr-list`       |
   | "Open a PR from X to Y"               | `pr-create`     |
   | "Comment on PR #N"                     | `pr-comment`    |
   | "Merge PR #N"                          | `pr-merge`      |
   | "What's the latest release?"           | `release-get`   |
   | "List releases" / "show versions"      | `release-list`  |
   | "List tags"                            | `tag-list`      |

5. **Handle multi-step workflows.** Common compound operations:

   - **"Review a repo"**: `repo-info` → `tree --recursive` → `file-read` key files (README,
     package.json, etc.)
   - **"Push a local file to a repo"**: `file-write --input /path/to/local/file`
   - **"Create a branch and PR"**: `file-write --branch new-branch` (GitHub auto-creates the
     branch) → `pr-create --head new-branch --base main`
   - **"Triage issues"**: `issue-list` → read each → `issue-update` with labels/assignees

6. **Output conventions:**
   - Structured data (repo-info, file-write result, issue-create, etc.) goes to **stdout as
     JSON** — machine-readable for pipeline chaining
   - Human-readable listings (tree, issue-list, pr-list, etc.) go to **stdout as formatted text**
   - Status/progress messages go to **stderr** with `[github]` prefix
   - After write operations, always show the user the result (commit SHA, issue URL, etc.)

## Output Routing

The script separates machine data (stdout) from status messages (stderr), so it chains cleanly:

```bash
# Read a file from one repo and commit it to another
python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-read --repo source/repo \
  --path config.yaml --output /tmp/config.yaml

python3 /tmp/paperclip_github.py --token "$GH_TOKEN" file-write --repo target/repo \
  --path config.yaml --input /tmp/config.yaml --message "Sync config from source"
```

## Error Reference

The script exits non-zero on any API failure and prints the HTTP status + response body to
stderr.

| HTTP Code | Meaning                              | Action                                               |
|-----------|--------------------------------------|------------------------------------------------------|
| 401       | Bad or expired token                 | Ask user to verify PAT and scopes.                   |
| 403       | Insufficient permissions / rate limit | Check PAT scopes. If rate-limited, wait and retry.  |
| 404       | Repo/file/issue not found            | Verify owner/repo and path. May be a private repo.   |
| 409       | Conflict (SHA mismatch on update)    | Re-read the file to get current SHA, then retry.     |
| 422       | Validation error                     | Check required fields. Common with PR create.        |
| 429       | Secondary rate limit                 | Wait 60s and retry.                                  |

## Token Scopes Quick Reference

| Operation          | Classic token scope  | Fine-grained permission     |
|--------------------|----------------------|-----------------------------|
| Read public repo   | (no scope needed)    | Public Repositories (read)  |
| Read private repo  | `repo`               | Contents (read)             |
| Write files        | `repo`               | Contents (write)            |
| Manage issues      | `repo`               | Issues (write)              |
| Manage PRs         | `repo`               | Pull requests (write)       |
| Read releases/tags | `repo` (private)     | Contents (read)             |

## Limitations

- **Pagination**: List commands return up to 100 items per call (GitHub API maximum). For repos
  with hundreds of issues/PRs, the `--limit` flag caps what you get in one shot. If the user
  needs more, run multiple calls isn't currently supported — note this and suggest they filter
  with `--labels`, `--state`, `--assignee`, etc.
- **Binary files**: `file-read` decodes as UTF-8 with replacement. For true binary files (images,
  archives), use `clone` instead and access them locally.
- **Large files**: The Contents API has a 100MB file size limit. For larger files, use `clone`.
- **Branch creation**: There's no standalone "create branch" command. Use `file-write --branch
  new-branch-name` on any file — GitHub will auto-create the branch if it doesn't exist.
