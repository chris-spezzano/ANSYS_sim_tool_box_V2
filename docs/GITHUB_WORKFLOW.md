# Git & GitHub Workflow Guide

> A practical reference for managing the ANSYS Simulation Toolbox (and any simulation
> project) on GitHub. Covers SSH setup, daily push/pull, branching strategy, pull
> requests, permissions, and best practices for large binary files.

---

## Table of Contents

1. [One-Time Setup](#1-one-time-setup)
   - 1.1 Install Git
   - 1.2 Configure your identity
   - 1.3 Generate an SSH key
   - 1.4 Add the SSH key to GitHub
   - 1.5 Test the connection
2. [Creating and Linking a Repository](#2-creating-and-linking-a-repository)
   - 2.1 New project from scratch
   - 2.2 Clone an existing repository
3. [Daily Workflow](#3-daily-workflow)
   - 3.1 Pull before you work
   - 3.2 Stage and commit
   - 3.3 Push your changes
   - 3.4 Checking status at any time
4. [Branching Strategy](#4-branching-strategy)
   - 4.1 Branch naming conventions
   - 4.2 Create and switch to a branch
   - 4.3 Merge a feature branch
   - 4.4 Rebase vs merge
   - 4.5 Delete stale branches
5. [Pull Requests and Code Review](#5-pull-requests-and-code-review)
   - 5.1 Open a pull request
   - 5.2 Review and approve
   - 5.3 Merge strategies
6. [Permissions and Collaborators](#6-permissions-and-collaborators)
   - 6.1 Add a collaborator
   - 6.2 Branch protection rules
   - 6.3 Required status checks
7. [Resolving Merge Conflicts](#7-resolving-merge-conflicts)
8. [Advanced Commands](#8-advanced-commands)
   - 8.1 git stash
   - 8.2 git cherry-pick
   - 8.3 git bisect
   - 8.4 git reflog (undo disasters)
9. [Simulation-Specific Best Practices](#9-simulation-specific-best-practices)
   - 9.1 .gitignore for ANSYS projects
   - 9.2 Git LFS for large binaries
   - 9.3 Versioning config.yaml and results
10. [SSH Key Rotation and Troubleshooting](#10-ssh-key-rotation-and-troubleshooting)
11. [Quick Reference Card](#11-quick-reference-card)

---

## 1. One-Time Setup

### 1.1 Install Git

```bash
# Windows (winget)
winget install --id Git.Git -e --source winget

# Verify
git --version
# git version 2.45.x
```

### 1.2 Configure your identity

Git embeds your name and email in every commit.  Set them once globally:

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"

# Optional quality-of-life settings
git config --global core.editor "code --wait"   # VS Code as commit editor
git config --global init.defaultBranch main      # use 'main' not 'master'
git config --global pull.rebase false            # merge-style pull (safe default)
git config --global core.autocrlf true           # Windows: normalise line endings on commit

# Confirm everything
git config --global --list
```

### 1.3 Generate an SSH key

SSH keys let you push/pull without typing a password on every operation.

```bash
# Generate a new Ed25519 key (preferred over RSA)
ssh-keygen -t ed25519 -C "you@example.com"

# When prompted:
#   Enter file: press Enter to accept default (~/.ssh/id_ed25519)
#   Passphrase: enter a strong passphrase (stored in the SSH agent, so you
#               only type it once per login session)
```

The command creates two files:

| File | Purpose |
|------|---------|
| `~/.ssh/id_ed25519` | **Private key** — never share this |
| `~/.ssh/id_ed25519.pub` | **Public key** — paste this into GitHub |

Start the SSH agent and load your key (Windows PowerShell):

```powershell
# Start the agent service (run once; or add to your PowerShell profile)
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent

# Load the key
ssh-add ~/.ssh/id_ed25519
```

### 1.4 Add the SSH key to GitHub

1. Copy the public key to the clipboard:
   ```bash
   cat ~/.ssh/id_ed25519.pub
   # or on Windows PowerShell:
   Get-Content ~/.ssh/id_ed25519.pub | Set-Clipboard
   ```

2. Go to **GitHub → Settings → SSH and GPG keys → New SSH key**

3. Give it a descriptive title (e.g., `workstation-2026`) and paste the key.

4. Click **Add SSH key**.

### 1.5 Test the connection

```bash
ssh -T git@github.com
# Expected output:
# Hi <username>! You've successfully authenticated, but GitHub does not
# provide shell access.
```

If you see `Permission denied (publickey)`, see [Section 10](#10-ssh-key-rotation-and-troubleshooting).

---

## 2. Creating and Linking a Repository

### 2.1 New project from scratch

```bash
# 1. Initialise a local repo
cd E:/Projects/ansys_sim_toolbox
git init

# 2. Add a .gitignore (see Section 9.1) then stage everything
git add .gitignore
git add .

# 3. First commit
git commit -m "Initial commit: ANSYS simulation toolbox v1.0"

# 4. Create the repo on GitHub (website or gh CLI)
gh repo create ansys_sim_toolbox --private --source=. --remote=origin --push
# This creates the repo, adds the remote, and pushes in one step.

# Alternatively, create on GitHub manually then:
git remote add origin git@github.com:<username>/ansys_sim_toolbox.git
git push -u origin main
# -u sets the upstream so future 'git push' needs no extra arguments
```

### 2.2 Clone an existing repository

```bash
# SSH (preferred — uses your SSH key, no password prompts)
git clone git@github.com:<username>/ansys_sim_toolbox.git

# HTTPS (fallback if SSH is blocked by a corporate firewall)
git clone https://github.com/<username>/ansys_sim_toolbox.git

# Clone into a specific folder
git clone git@github.com:<username>/ansys_sim_toolbox.git E:/Projects/ansys_sim_toolbox
```

---

## 3. Daily Workflow

The safe daily sequence is: **pull → work → stage → commit → push**.

### 3.1 Pull before you work

Always sync with the remote before making changes to avoid divergence:

```bash
git pull
# Fetches remote changes and merges them into your current branch.
# Equivalent to: git fetch && git merge origin/<branch>
```

If your team uses rebase-style pulls:

```bash
git pull --rebase
# Replays your local commits on top of the fetched remote commits.
# Produces a cleaner linear history.
```

### 3.2 Stage and commit

```bash
# See what has changed
git status
git diff                     # unstaged changes
git diff --staged            # changes already staged

# Stage specific files
git add ams/resources/manager.py
git add notebooks/02_resource_management.ipynb

# Stage everything in the current directory
git add .

# Unstage a file (keeps the changes, just removes from staging area)
git restore --staged ams/resources/manager.py

# Commit
git commit -m "feat: add kill_ansys_zombies() dry_run mode"

# Commit all tracked modified files in one step (skips untracked files)
git commit -am "fix: replace Unicode symbols with ASCII for Windows compatibility"
```

**Commit message conventions** (makes git log readable and generates changelogs):

```
<type>: <short description>

Types: feat, fix, docs, refactor, test, chore
Examples:
  feat: add SHELL181 element reassignment in GeometryImporter
  fix: correct bilinear QUAD4 Jacobian for 2D meshes
  docs: add solver reference and bug catalogue
  test: add Kirsch stress concentration validation
  refactor: split SolverStrategy into dataclass + builder
  chore: update .gitignore for ANSYS RST/CDB files
```

### 3.3 Push your changes

```bash
# Push the current branch to its upstream
git push

# Push and set upstream for a new branch (first push only)
git push -u origin feature/shell181-import

# Force push (only on your own feature branches, never on main)
git push --force-with-lease
# --force-with-lease is safer than --force: it refuses if someone else
# pushed to the branch since your last fetch.
```

### 3.4 Checking status at any time

```bash
git status                   # working tree / staging summary
git log --oneline -10        # last 10 commits, compact
git log --oneline --graph --all  # visual branch tree
git diff HEAD~1              # diff against one commit ago
git show <commit-hash>       # full diff for a specific commit
git blame ams/mapdl/solver.py   # who wrote each line
```

---

## 4. Branching Strategy

The recommended workflow for this toolbox is **GitHub Flow** — simple and
appropriate for a small team:

```
main          ← always deployable / passing tests
  |
  +-- feature/shell281-fix
  +-- fix/periodic-bc-node-count
  +-- docs/github-workflow
```

**Never commit directly to `main`.**  All changes go through a feature branch
and pull request.

### 4.1 Branch naming conventions

| Prefix | Use case | Example |
|--------|----------|---------|
| `feature/` | New functionality | `feature/chaboche-material` |
| `fix/` | Bug fixes | `fix/zombie-port-cleanup` |
| `docs/` | Documentation only | `docs/solver-reference` |
| `refactor/` | Code restructuring, no behaviour change | `refactor/pipeline-checkpointing` |
| `test/` | Adding or fixing tests | `test/mesh-quality-smoke` |
| `chore/` | Tooling, CI, dependencies | `chore/update-requirements` |

### 4.2 Create and switch to a branch

```bash
# Create and switch in one command
git checkout -b feature/arc-length-solver

# Modern equivalent (Git 2.23+)
git switch -c feature/arc-length-solver

# Push the new branch to GitHub
git push -u origin feature/arc-length-solver

# Switch to an existing branch
git checkout main
git switch main

# List all branches (local and remote)
git branch -a
```

### 4.3 Merge a feature branch

After your PR is approved (see Section 5), merge into main:

```bash
# Switch to main and make sure it is up to date
git checkout main
git pull

# Merge the feature branch
git merge --no-ff feature/arc-length-solver
# --no-ff creates a merge commit even if fast-forward is possible.
# This preserves the branch topology in the history.

# Push main
git push

# Delete the local feature branch
git branch -d feature/arc-length-solver

# Delete the remote feature branch
git push origin --delete feature/arc-length-solver
```

### 4.4 Rebase vs merge

| Method | History shape | When to use |
|--------|--------------|-------------|
| `git merge --no-ff` | Preserves branch topology with merge commit | Default for feature branches |
| `git merge --ff-only` | Linear if possible, fails if not | Small single-commit fixes |
| `git rebase main` | Replays commits on top of main; linear | Before opening a PR to clean up messy history |
| `git rebase -i HEAD~n` | Interactive: squash, reword, drop commits | Polishing a branch before review |

**Golden rule:** Never rebase commits that have been pushed to a shared
branch.  Rebasing rewrites commit hashes — anyone else who pulled the old
hashes will have a diverged history.

Squash before merging a noisy branch:

```bash
# Squash the last 4 commits into one
git rebase -i HEAD~4
# In the editor: change 'pick' to 'squash' (or 's') for commits 2-4.
# Write a clean combined commit message.
git push --force-with-lease
```

### 4.5 Delete stale branches

```bash
# List merged branches (safe to delete)
git branch --merged main

# Delete all merged local branches except main and the current one
git branch --merged main | grep -v '^\*\|main' | xargs git branch -d

# Prune remote-tracking references for branches deleted on GitHub
git fetch --prune
git remote prune origin
```

---

## 5. Pull Requests and Code Review

### 5.1 Open a pull request

Using the GitHub CLI (`gh`):

```bash
# Install gh
winget install --id GitHub.cli

gh auth login   # follow prompts; choose SSH

# Open a PR from the current branch into main
gh pr create \
  --base main \
  --title "feat: add arc-length solver for snap-through analysis" \
  --body "$(cat <<'EOF'
## Changes
- Added ARCLEN,ON command to _solve_static()
- Added documentation: AUTOTS must be disabled when ARCLEN is active (BUG-09)
- Unit test: snap-through of shallow arch benchmark

## Testing
- Offline smoke tests: PASS
- Manually verified snap-through load-displacement curve matches theory

## References
- BUG-09 in docs/BUG_CATALOGUE.md
- ANSYS Theory Reference §17.5
EOF
)"

# Or just open the GitHub UI
gh pr create --web
```

### 5.2 Review and approve

```bash
# List open PRs
gh pr list

# Checkout a PR locally to review and test it
gh pr checkout 42

# Run smoke tests on the checked-out branch
python smoke_tests/run_all.py

# Approve (from the website, or CLI)
gh pr review 42 --approve --body "Tests pass. ARCLEN logic looks correct."

# Request changes
gh pr review 42 --request-changes --body "Please add a test for AUTOTS + ARCLEN conflict."
```

### 5.3 Merge strategies

From the GitHub website pull request, you have three options:

| Strategy | Effect | When to use |
|----------|--------|-------------|
| **Create a merge commit** | Preserves all commits + adds a merge commit | Default; full history |
| **Squash and merge** | Collapses branch into one commit on main | Noisy branches with many fixup commits |
| **Rebase and merge** | Replays commits onto main without a merge commit | Clean single-commit feature branches |

For this toolbox, **squash and merge** is recommended for feature branches so
that `main` log stays readable: one commit per feature.

---

## 6. Permissions and Collaborators

### 6.1 Add a collaborator

```bash
# Via CLI
gh api repos/<owner>/ansys_sim_toolbox/collaborators/<username> \
  --method PUT \
  --field permission=push
  # permission: pull, triage, push, maintain, admin

# Remove a collaborator
gh api repos/<owner>/ansys_sim_toolbox/collaborators/<username> --method DELETE
```

Permission levels:

| Level | Can do |
|-------|--------|
| `pull` | Read only; cannot push |
| `triage` | Read + manage issues/PRs (no push) |
| `push` | Read + write; can push to non-protected branches |
| `maintain` | push + manage settings (no admin) |
| `admin` | Full control including settings, delete, transfers |

### 6.2 Branch protection rules

Protect `main` from direct pushes and force-pushes:

1. Go to **Repository → Settings → Branches → Add branch ruleset**
2. Branch name pattern: `main`
3. Enable:
   - [x] Require a pull request before merging
   - [x] Require approvals: **1** (or more for team repos)
   - [x] Dismiss stale pull request approvals when new commits are pushed
   - [x] Require status checks to pass before merging (see 6.3)
   - [x] Require branches to be up to date before merging
   - [x] Do not allow bypassing the above settings

Via `gh` CLI:

```bash
gh api repos/<owner>/ansys_sim_toolbox/branches/main/protection \
  --method PUT \
  --header "Accept: application/vnd.github+json" \
  --field required_status_checks='{"strict":true,"contexts":["smoke-tests"]}' \
  --field enforce_admins=true \
  --field required_pull_request_reviews='{"required_approving_review_count":1}' \
  --field restrictions=null
```

### 6.3 Required status checks

If you add a GitHub Actions CI workflow (`.github/workflows/smoke.yml`), you
can require it to pass before merging:

```yaml
# .github/workflows/smoke.yml
name: Smoke Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  offline-tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python smoke_tests/run_all.py
        # Runs offline tests only (no ANSYS license on CI)
```

---

## 7. Resolving Merge Conflicts

A merge conflict occurs when two branches changed the same lines differently.
Git cannot automatically decide which version is correct.

```bash
# You see this after a failing merge:
# CONFLICT (content): Merge conflict in ams/mapdl/solver.py
# Automatic merge failed; fix conflicts and then commit the result.

# Open the conflicting file in VS Code
code ams/mapdl/solver.py
```

The file will contain conflict markers:

```python
<<<<<<< HEAD (your branch)
    mapdl.nsubst(10, 50, 2)
=======
    mapdl.nsubst(20, 100, 5)
>>>>>>> feature/finer-substeps (incoming branch)
```

Edit the file to keep the correct version (or combine both):

```python
    mapdl.nsubst(20, 100, 2)   # use incoming max but keep your min
```

Remove all `<<<<<<<`, `=======`, `>>>>>>>` markers, then:

```bash
git add ams/mapdl/solver.py
git commit -m "merge: resolve substep conflict, keep finer increments"
```

**VS Code** has a built-in merge editor (three-way diff) that makes this
visual.  The **GitLens** extension adds author information inline.

**Aborting a merge** (if you want to start over):

```bash
git merge --abort
```

---

## 8. Advanced Commands

### 8.1 git stash

Save work-in-progress without committing so you can switch branches cleanly:

```bash
# Stash everything (tracked + staged)
git stash push -m "WIP: ARCLEN substep tuning"

# Include untracked files
git stash push -u -m "WIP: new notebook draft"

# List stashes
git stash list
# stash@{0}: On feature/arclen: WIP: ARCLEN substep tuning
# stash@{1}: On main: WIP: new notebook draft

# Apply the most recent stash (keeps it in the stash list)
git stash apply

# Apply and remove from the list
git stash pop

# Apply a specific stash
git stash apply stash@{1}

# Discard a stash
git stash drop stash@{0}

# Discard all stashes
git stash clear
```

### 8.2 git cherry-pick

Apply a specific commit from one branch onto another:

```bash
# Find the commit hash
git log --oneline feature/hfss-cleanup
# a3f9c12 fix: delete _Unnamed_6 objects after CAD import

# Apply that commit to the current branch
git cherry-pick a3f9c12

# Cherry-pick a range of commits
git cherry-pick a3f9c12..b7e0d45

# Cherry-pick without auto-committing (lets you edit the message)
git cherry-pick --no-commit a3f9c12
```

### 8.3 git bisect

Find which commit introduced a regression using binary search:

```bash
# Start bisect
git bisect start

# Mark the current commit as bad (regression present)
git bisect bad

# Mark a known-good commit (e.g., the tag from last week)
git bisect good v1.0.0

# Git checks out the midpoint commit.
# Run your test:
python smoke_tests/run_all.py

# Tell Git whether this commit is good or bad
git bisect good    # or: git bisect bad

# Git keeps halving the range until it isolates the bad commit.
# When done:
git bisect reset   # return to HEAD
```

For a large regression window, `bisect` finds the culprit in ~log2(N) steps
instead of checking all N commits manually.

### 8.4 git reflog (undo disasters)

`git reflog` records every time HEAD moved — including commits that appear
"lost" after a reset or rebase:

```bash
git reflog
# HEAD@{0}: reset: moving to HEAD~1
# HEAD@{1}: commit: feat: add ARCLEN solver
# HEAD@{2}: commit: fix: substep tuning
# ...

# Recover a "lost" commit
git checkout HEAD@{1}               # detached HEAD, inspect the state
git checkout -b recovery/arclen     # save it as a new branch
# or:
git reset --hard HEAD@{1}           # restore main to that commit
```

`reflog` entries expire after 90 days by default.

---

## 9. Simulation-Specific Best Practices

### 9.1 .gitignore for ANSYS projects

```gitignore
# ── ANSYS working files ───────────────────────────────────────────────────
*.rst           # result database (can be GB)
*.rth           # thermal result
*.rfl           # FLOTRAN result
*.emat          # element matrix file
*.esav          # element saved data
*.full          # full matrix file
*.sub           # superelement
*.cdb           # mesh/model database (large; use LFS if needed)
*.log           # ANSYS log (generated each run)
*.err           # ANSYS error log
*.lock          # AEDT lock file
*.aedt          # AEDT project (binary; use LFS if large)
*.aedt.auto     # auto-save
*.aedtresults/  # adaptive pass results directory

# ── Python ────────────────────────────────────────────────────────────────
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
dist/
build/
*.egg-info/

# ── Jupyter ───────────────────────────────────────────────────────────────
.ipynb_checkpoints/
# To strip cell outputs before committing (keeps diffs clean):
# Use nbstripout: pip install nbstripout && nbstripout --install

# ── Environment ───────────────────────────────────────────────────────────
.env
.venv/
venv/
*.pth

# ── VS Code ───────────────────────────────────────────────────────────────
.vscode/settings.json
# Keep .vscode/extensions.json (recommended extensions) in git

# ── OS ────────────────────────────────────────────────────────────────────
Thumbs.db
.DS_Store

# ── Large outputs (keep paths, not files) ─────────────────────────────────
outputs/
runs/
*.vtk
*.stl
```

Install `nbstripout` to automatically strip notebook outputs on commit
(outputs can be MB each and cause noisy diffs):

```bash
pip install nbstripout
nbstripout --install            # installs a pre-commit git filter
nbstripout --install --global   # for all repos on this machine
```

### 9.2 Git LFS for large binaries

CDB and AEDT project files can be 10–500 MB.  Git LFS stores them outside the
main repository object store (only a pointer is in the repo):

```bash
# Install Git LFS
git lfs install

# Track file types
git lfs track "*.cdb"
git lfs track "*.aedt"
git lfs track "*.rst"
git lfs track "*.stl"

# This creates / updates .gitattributes — commit it
git add .gitattributes
git commit -m "chore: track large binary files with Git LFS"

# Normal workflow after that — git handles LFS transparently
git add geometry/origami_v3.cdb
git commit -m "data: add origami mesh v3"
git push
```

Check what is tracked:

```bash
git lfs ls-files       # LFS-tracked files in the working tree
git lfs status         # which LFS files changed
git lfs env            # LFS configuration
```

GitHub Free: 1 GB LFS storage + 1 GB/month bandwidth included.
GitHub Pro / Team: higher limits.

### 9.3 Versioning config.yaml and results

**Do commit:**
- `config.yaml` — the simulation parameters that produced a result
- `notebooks/*.ipynb` (with outputs stripped by nbstripout)
- `docs/` and `ams/` source code
- `.gitattributes`, `.gitignore`, `requirements.txt`

**Do not commit:**
- `outputs/` directories with RST / VTK result files
- `*.log` from ANSYS runs

**Tag releases** when a set of results is published or shared:

```bash
git tag -a v1.2.0 -m "Release: origami fold angle sweep, 50k element mesh"
git push origin v1.2.0

# List tags
git tag

# Check out the exact state used for a result
git checkout v1.2.0
```

---

## 10. SSH Key Rotation and Troubleshooting

### Rotate a key (annual practice or after a security incident)

```bash
# 1. Generate a new key
ssh-keygen -t ed25519 -C "you@example.com-2027" -f ~/.ssh/id_ed25519_2027

# 2. Add the new public key to GitHub (Settings → SSH keys → New key)

# 3. Test the new key
ssh -i ~/.ssh/id_ed25519_2027 -T git@github.com

# 4. Update ~/.ssh/config to use the new key
```

`~/.ssh/config`:
```
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_2027
    IdentitiesOnly yes
```

```bash
# 5. Remove the old key from GitHub (Settings → SSH keys → Delete)

# 6. Load the new key in the agent
ssh-add ~/.ssh/id_ed25519_2027
ssh-add -D ~/.ssh/id_ed25519    # remove the old key from agent
```

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Permission denied (publickey)` | SSH key not loaded or wrong key | Run `ssh-add ~/.ssh/id_ed25519`; verify with `ssh -T git@github.com` |
| `Host key verification failed` | `known_hosts` entry changed | Run `ssh-keygen -R github.com`, then reconnect to re-accept |
| `remote: Repository not found` | Wrong URL or no access | Check `git remote -v`; verify you are a collaborator |
| `error: failed to push some refs` | Remote has commits you don't have | Run `git pull --rebase` then push again |
| `fatal: refusing to merge unrelated histories` | Repos initialised independently | `git pull --allow-unrelated-histories` (once only) |
| `LFS: Storage quota exceeded` | GitHub LFS limit reached | Purge old LFS objects or upgrade plan |
| `Updates were rejected because the tip of your current branch is behind` | Someone else pushed to the same branch | `git pull`, resolve conflicts, push again |

### Diagnose SSH with verbose output

```bash
ssh -vT git@github.com
# Look for lines starting with "Offering public key" and "Server accepts key"
# If no key is offered, the agent is empty — run ssh-add
```

---

## 11. Quick Reference Card

```
SETUP
  git config --global user.name "Name"       Set identity
  git config --global user.email "x@y.com"
  ssh-keygen -t ed25519 -C "x@y.com"         Generate SSH key
  ssh -T git@github.com                       Test connection

REPO
  git init                                    Init local repo
  git clone git@github.com:u/repo.git         Clone from GitHub
  git remote -v                               Show remotes
  git remote add origin git@github.com:...   Add remote
  git remote set-url origin git@github.com:. Change remote URL

DAILY WORKFLOW
  git pull                                    Sync from remote
  git status                                  What changed?
  git diff                                    Unstaged changes
  git diff --staged                           Staged changes
  git add <file>                              Stage a file
  git add .                                   Stage everything
  git restore --staged <file>                 Unstage a file
  git commit -m "type: description"           Commit
  git push                                    Push to remote
  git push -u origin <branch>                 Push new branch

BRANCHES
  git branch -a                               List all branches
  git checkout -b <name>                      Create + switch
  git switch <name>                           Switch branch
  git merge --no-ff <branch>                  Merge with commit
  git rebase main                             Rebase onto main
  git branch -d <branch>                      Delete local branch
  git push origin --delete <branch>           Delete remote branch
  git fetch --prune                           Remove stale refs

HISTORY
  git log --oneline -10                       Last 10 commits
  git log --oneline --graph --all             Visual tree
  git show <hash>                             Show a commit
  git diff HEAD~1                             Diff vs last commit
  git blame <file>                            Who wrote each line

UNDO
  git restore <file>                          Discard unstaged changes
  git reset HEAD~1                            Undo last commit, keep changes
  git reset --hard HEAD~1                     Undo last commit, DISCARD changes
  git revert <hash>                           New commit that undoes <hash>
  git reflog                                  Find lost commits

STASH
  git stash push -m "WIP: message"            Save work-in-progress
  git stash list                              List stashes
  git stash pop                               Apply and remove top stash
  git stash drop stash@{n}                    Discard a stash

ADVANCED
  git cherry-pick <hash>                      Apply one commit
  git bisect start/good/bad/reset             Binary search for regression
  git tag -a v1.0 -m "message"               Tag a release
  git push origin v1.0                        Push a tag

GIT LFS
  git lfs install                             Enable LFS
  git lfs track "*.cdb"                       Track a file type
  git lfs ls-files                            List LFS files

GITHUB CLI
  gh repo create <name> --private             Create repo
  gh pr create --base main --web              Open PR in browser
  gh pr list                                  List open PRs
  gh pr checkout <number>                     Checkout a PR locally
  gh pr merge <number> --squash               Merge with squash
  gh auth login                               Authenticate gh CLI
```

---

*Next:* For CI integration examples, see `.github/workflows/smoke.yml` (Section 6.3).  
*For ANSYS-specific debugging,* see `docs/BUG_CATALOGUE.md` and `notebooks/10_debug_workflow.ipynb`.
