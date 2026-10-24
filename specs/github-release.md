# Preparing a GitHub repository

The repository has no commits yet. The README, ignore rules, package metadata,
and GitHub Actions workflow are prepared. These commands assume Bash, Python
3.11+, Git, and (for repository creation) the GitHub CLI.

## Verify the release contents

Run from the repository root:

```bash
source .venv/bin/activate
python -m pip install -e ".[ui,dev]"
python -m ruff check src tests tools/smoke.py
python -m pytest -q
python -m pip check
python -m build
python -m pip install --force-reinstall --no-deps dist/research_cockpit-0.1.0-py3-none-any.whl
python tools/smoke.py
python -m pip install -e ".[ui,dev]"
```

Read [the verification report](verification.md) before describing the release as
complete. Select a project license and add its `LICENSE` file when you have
chosen the reuse terms. The README currently says no license is selected.

## Review and commit

```bash
git status --short
git add README.md pyproject.toml .gitignore .github .streamlit/config.toml src tests tools specs
# If you added a license, also run: git add LICENSE
git diff --cached --stat
git diff --cached --check
git diff --cached
# After reviewing the staged files:
git commit -m "Initial Research Cockpit preview"
```

The ignore rules exclude the handoff PDF, virtual environment, build artifacts,
local databases, `.env` files, and Streamlit secrets. Keep personal papers and
configuration outside the published source tree. The staged diff is the actual
content of the first commit.

## Create and push

If there is no GitHub repository yet:

```bash
gh auth login
gh repo create research-cockpit --public --source=. --remote=origin --push
gh run list --limit 5
```

Use `--private` instead of `--public` if preferred. After the Checks workflow
appears, inspect it with `gh run view RUN_ID` or `gh run watch RUN_ID`.

If you already created an empty repository on GitHub, use this path instead
(replace `YOUR_USERNAME`):

```bash
git remote add origin https://github.com/YOUR_USERNAME/research-cockpit.git
git push -u origin main
```

If `origin` already exists, inspect `git remote -v` and use that remote instead of
adding it again. No commits, remotes, or uploads were performed during this audit.
