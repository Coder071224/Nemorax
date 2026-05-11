# GitHub Source Control

This repository is already a Git repository. Use GitHub as the source of truth
for app code, docs, build scripts, and deployment config. Do not commit local
secrets or generated build outputs.

## Check Current Remote

```powershell
git remote -v
```

If no remote exists, add one:

```powershell
git remote add origin https://github.com/USERNAME/REPOSITORY.git
```

If the remote is wrong, replace it:

```powershell
git remote set-url origin https://github.com/USERNAME/REPOSITORY.git
```

## Commit And Push

```powershell
git status
git add .
git commit -m "Prepare Windows exe build and GitHub setup"
git branch -M main
git push -u origin main
```

## Before Pushing

Check that these are not staged:

- `.env`
- `.env.*`
- `.venv/`
- `build/`
- `dist/`
- private key files
- generated `.exe`, `.apk`, `.aab`, `.msix`, or installer files

If a secret was ever committed, remove it from the repository history and rotate
the secret immediately. Ignoring it later is not enough.
