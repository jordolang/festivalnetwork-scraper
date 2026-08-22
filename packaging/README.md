# Packaging the desktop app

Four artifacts, one per platform/architecture pair:

    FestivalNet-Scraper-<version>-windows-x64.zip
    FestivalNet-Scraper-<version>-windows-arm64.zip
    FestivalNet-Scraper-<version>-macos-x64.zip
    FestivalNet-Scraper-<version>-macos-arm64.zip

## Build one

```bash
pip install -r requirements-build.txt
python packaging/build.py                 # this machine's platform + arch
python packaging/build.py --target arm64  # macOS cross-build
python packaging/build.py --dmg           # macOS: also roll a disk image
python packaging/build.py --no-archive    # leave the app folder, skip the zip
```

Output lands in `dist/`. `build.py` regenerates the icons first if they are
missing, and refuses to start on a Python without Tk — which would
otherwise produce an app that builds cleanly and then cannot open a window.

## What is here

| File | What it does |
|------|--------------|
| `entry.py` | The frozen app's entry point. Also the only place that can report a startup crash, since a windowed app has no console to print to. |
| `festivalnet.spec` | The PyInstaller recipe. One spec for all four targets — the architecture comes from the interpreter running the build. |
| `build.py` | Driver: freezes, then archives with the right tool for the platform. |
| `entitlements.plist` | Hardened-runtime entitlements, used only when `FN_CODESIGN_IDENTITY` is set. |

## Why a Windows ARM64 build needs an ARM64 Windows machine

A frozen app is that machine's CPython plus its compiled extension modules
plus a bootloader built for its CPU. Nothing in the toolchain can retarget
those from an x64 host, so the ARM64 Windows app comes off an ARM64 runner
(`windows-11-arm` on GitHub) or an ARM64 PC. macOS is the exception:
`--target` works there because the wheels and the interpreter can carry
both slices at once.

## Cutting a release

Tag it and push the tag; the workflow does the rest.

```bash
git tag -a v1.0.0 -m "FestivalNet Scraper 1.0.0"
git push origin v1.0.0
```

That runs the test suite, builds every target, and publishes a GitHub
release with the zips attached. Keep the tag in step with
`fnscraper.__version__`, since that is what names the artifacts.

### When a Mac build is missing

macOS Intel builds run on `macos-13`, the last Intel runner image, which
GitHub is winding down — jobs against it can queue indefinitely. The job
is therefore `continue-on-error`, and a release can go out without it; the
workflow logs a warning naming what is absent.

The durable fix is to stop needing an Intel runner at all: build one
**universal2** app on Apple silicon that runs on both. PyInstaller's
`--target universal2` (already wired to `build.py --target universal2`)
needs a universal2 CPython, which `actions/setup-python` does not provide
— it would have to come from the python.org installer. Every dependency
here is pure Python, so nothing else stands in the way. Untested, hence
not wired into CI yet.

## Signing and notarizing (optional)

Unsigned builds work; they just make the OS ask the user once. To sign a
macOS build, set `FN_CODESIGN_IDENTITY` to a Developer ID Application
identity before building, then notarize the zip:

```bash
export FN_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
python packaging/build.py
xcrun notarytool submit dist/FestivalNet-Scraper-*-macos-*.zip \
    --apple-id you@example.com --team-id TEAMID --wait
xcrun stapler staple "dist/FestivalNet Scraper.app"
```

On Windows, sign the executable inside the app folder with `signtool` and
re-zip.

## Environment variables the spec reads

| Variable | Effect |
|----------|--------|
| `FN_VERSION` | Version stamped into the macOS bundle (default: `fnscraper.__version__`, set by `build.py`) |
| `FN_TARGET_ARCH` | macOS target architecture (`x86_64`, `arm64`, `universal2`) |
| `FN_CODESIGN_IDENTITY` | macOS signing identity; unset means an unsigned build |
