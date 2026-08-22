# Packaging the desktop app

Four artifacts, each in the shape that platform's users expect:

    FestivalNet-Scraper-<version>-windows-x64.exe        one self-contained .exe
    FestivalNet-Scraper-<version>-windows-arm64.exe
    FestivalNet-Scraper-<version>-macos-arm64.dmg        a mountable disk image
    FestivalNet-Scraper-<version>-macos-universal2.dmg   Intel + Apple silicon

Windows gets a **one-file** build: everything is folded into the binary,
which unpacks to a temp directory at launch.  That costs a second or two of
startup and buys a single file you can hand someone, rather than a folder
they have to keep intact.  macOS keeps the layered form, because a `.app`
*is* a directory and cannot be a one-file binary; the `.dmg` wraps it with
an Applications symlink to drag it into.

## Build one

```bash
pip install -r requirements-build.txt
python packaging/build.py                 # this machine's platform + arch
python packaging/build.py --target arm64  # macOS cross-build
python packaging/build.py --no-package    # leave the raw build, skip naming
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

### Why there is no Intel macOS runner

`macos-13` was the last Intel runner image and GitHub is winding it down;
jobs targeting it queue and frequently never start. Marking such a job
`continue-on-error` does **not** help: that only applies to a job that
runs and fails, while a job stuck in the queue never concludes at all — so
anything depending on it waits indefinitely. An unobtainable runner has to
be out of the dependency graph, not merely optional within it.

Intel Macs are served instead by a **universal2** build made on Apple
silicon, which carries both slices in one app. PyInstaller can only emit
that from a universal2 interpreter, which `actions/setup-python` does not
provide, so the job installs CPython from the python.org `.pkg` — the
build that ships both architectures, Tk included. It then asserts with
`lipo` that the interpreter really has both slices before building, since
a single-slice interpreter would happily produce an arm64-only app wearing
a universal name.

That job is `continue-on-error`, which is safe here precisely because its
runner is obtainable: it concludes one way or the other rather than
hanging. The release does not wait on it.

## Signing and notarizing (optional)

Unsigned builds work; they just make the OS ask the user once. To sign a
macOS build, set `FN_CODESIGN_IDENTITY` to a Developer ID Application
identity before building, then notarize the zip:

```bash
export FN_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
python packaging/build.py
xcrun notarytool submit dist/FestivalNet-Scraper-*-macos-*.dmg \
    --apple-id you@example.com --team-id TEAMID --wait
xcrun stapler staple dist/FestivalNet-Scraper-*-macos-*.dmg
```

On Windows, sign with `signtool` — the one-file `.exe` is the whole
deliverable, so there is nothing else to sign or repackage.

## Environment variables the spec reads

| Variable | Effect |
|----------|--------|
| `FN_VERSION` | Version stamped into the macOS bundle (default: `fnscraper.__version__`, set by `build.py`) |
| `FN_TARGET_ARCH` | macOS target architecture (`x86_64`, `arm64`, `universal2`) |
| `FN_CODESIGN_IDENTITY` | macOS signing identity; unset means an unsigned build |
