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

1. Bump version tag (e.g. `v1.0.3`)
2. Build the exe locally (one at a time; PyInstaller is CPU-heavy)
3. Upload to GitHub Releases:

```bat
gh release create v1.0.3 dist\DashcamRepair.exe --title "v1.0.3" --notes-file RELEASE_NOTES.md
```

Do not commit `dist/` or `build/` to git. Put binaries on Releases only.

## v1.0.3 highlights

- moov-first / moov-last auto-detection and truncated `stco` rebuild
- Three Novatek chunk header types (A/B/C)
- Dynamic search window (`MAX_GAP`, `REACH_SLACK`) with 1-byte forward search
- Output safety guardrails (`validate_output_plan`)
- Parallel batch repair via `--workers` (default 1)
- FULL / PARTIAL / FAIL logging with sample counts
- Compression removed (produced unplayable output)

## What we skip for this project

| Skip | Reason |
|------|--------|
| `src/` package layout | Two scripts, not a library |
| PyPI publish | Desktop tool, not a pip package |
| Committing `.exe` to `main` | Bloats git history; use Releases |
| Long build docs in README | Most visitors want the download link |
| Post-repair compression | Broke playback in testing |
