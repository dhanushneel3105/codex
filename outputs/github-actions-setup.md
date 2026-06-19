# GitHub Actions Setup

This repo includes `.github/workflows/amul-stock-check.yml`.

It runs:

- Every hour
- On demand from the GitHub Actions tab
- With Gmail credentials stored as GitHub Secrets
- With state persisted in `work/amul_stock_state.json`

## 1. Create A GitHub Repo

Create a private GitHub repository and push this workspace to it.

From PowerShell in this workspace:

```powershell
git status
git add .
git commit -m "Add Amul stock checker GitHub Action"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

If the remote already exists, skip the `git remote add origin ...` command.

## 2. Add GitHub Secrets

In GitHub:

1. Open the repository.
2. Go to Settings > Secrets and variables > Actions.
3. Click New repository secret.
4. Add:

```text
GMAIL_SMTP_USER
```

Value:

```text
your Gmail address
```

5. Add another secret:

```text
GMAIL_APP_PASSWORD
```

Value:

```text
your Gmail app password
```

## 3. Enable Actions

Open the Actions tab and enable workflows if GitHub asks.

The workflow is named:

```text
Amul stock check
```

Use Run workflow to test it immediately.

## 4. State File Behavior

The workflow commits `work/amul_stock_state.json` after each run.

That prevents repeated emails every hour for a product that is already available. If a product goes unavailable and later becomes available again, the bot will email again.
