# Building from source

Most people should use **DashcamRepair.exe** from [Releases](https://github.com/lun7n/novatek-dashcam-repair/releases). This page is for developers and maintainers.

## Run without building

Repair engine (stdlib only):

```bat
python repair_all.py "D:\path\to\videos"
```

GUI:

```bat
python repair_gui.py
```

Requires **Python 3.10+**. No pip packages needed for repair.

## Build Windows `.exe`

```bat
build_exe.bat
```

Or manually:

```bat
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name DashcamRepair --clean repair_gui.py
```

Output: `dist\DashcamRepair.exe` (~10 MB).

## Publish a release (maintainers)

1. Bump version tag (e.g. `v1.0.1`)
2. Build the exe locally (or via CI; see below)
3. Upload to GitHub Releases:

```bat
gh release create v1.0.1 dist\DashcamRepair.exe --title "v1.0.1" --notes "Release notes here"
```

Do not commit `dist/` or `build/` to git. Put binaries on Releases only.

## Optional: CI build on tag

Some repos use `.github/workflows/release.yml` to build the exe when a tag is pushed. Useful if you release often; optional for a small tool.

## What we skip for this project

| Skip | Reason |
|------|--------|
| `src/` package layout | Two scripts, not a library |
| PyPI publish | Desktop tool, not a pip package |
| Committing `.exe` to `main` | Bloats git history; use Releases |
| Long build docs in README | Most visitors want the download link |
