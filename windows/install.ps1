<#
    Show Finder - Windows installer.

    Driven by Install.cmd in the folder above this one; nothing here
    expects the person running it to know anything about Python.  It:

      1. finds a usable Python (>= 3.10), installing one from python.org
         if the PC has none,
      2. copies the program into %LOCALAPPDATA%\Programs\ShowFinder so it
         keeps working after the download folder is emptied,
      3. builds a private virtual environment there and installs the
         libraries into it, touching nothing else on the machine,
      4. writes the double-click launchers and puts icons on the Desktop
         and in the Start Menu,
      5. runs the setup wizard so the tool is configured for THIS
         business before it is ever used.

    Everything is per-user: no administrator rights, no PATH surgery, no
    system Python required.  A full log lands in %TEMP%\ShowFinder-install.log.
#>

[CmdletBinding()]
param(
    [switch]$SkipWizard,          # install only; configure later
    [string]$InstallDir           # override the destination
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$AppName    = 'Show Finder'
$Source     = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Target     = if ($InstallDir) { $InstallDir } else { Join-Path $env:LOCALAPPDATA 'Programs\ShowFinder' }
$LogFile    = Join-Path $env:TEMP 'ShowFinder-install.log'
$PyVersion  = '3.12.10'
$MinPython  = [version]'3.10'

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

function Log {
    param([string]$Message, [string]$Color = 'Gray', [switch]$Quiet)
    $stamped = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Message
    try { Add-Content -LiteralPath $LogFile -Value $stamped -Encoding UTF8 } catch {}
    if (-not $Quiet) { Write-Host $Message -ForegroundColor $Color }
}

function Step {
    param([int]$Number, [string]$Message)
    Write-Host ''
    Log ("[{0}/6] {1}" -f $Number, $Message) 'Cyan'
}

function Fail {
    param([string]$Message, [string]$Fix)
    Write-Host ''
    Log '------------------------------------------------------------------' 'Red'
    Log "  INSTALL STOPPED: $Message" 'Red'
    Log '------------------------------------------------------------------' 'Red'
    if ($Fix) { Write-Host ''; Write-Host $Fix -ForegroundColor Yellow }
    Write-Host ''
    Write-Host "A detailed log is at: $LogFile" -ForegroundColor Gray
    Write-Host 'You can send that file to whoever set this up for you.' -ForegroundColor Gray
    exit 1
}

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

function Invoke-Native {
    <#
        Run an external program, log everything it prints, return its exit
        code.  $ErrorActionPreference is dropped to Continue for the call
        on purpose: with 2>&1 in effect, a native command that writes to
        stderr raises a terminating NativeCommandError under Stop, and pip
        writes to stderr on perfectly healthy runs (progress, notices,
        deprecation warnings).  Without this, a normal install aborts.
    #>
    param([string]$Exe, [string[]]$Arguments, [string]$WorkingDirectory)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    if ($WorkingDirectory) { Push-Location $WorkingDirectory }
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Log "    $_" -Quiet }
        return $LASTEXITCODE
    } finally {
        if ($WorkingDirectory) { Pop-Location }
        $ErrorActionPreference = $previous
    }
}

function Test-PythonCandidate {
    <# Returns the real interpreter path when it is >= $MinPython, else $null. #>
    param([string]$Command, [string[]]$Prefix = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $probe = 'import sys;print("%d.%d"%sys.version_info[:2]);print(sys.executable)'
        $out = & $Command @Prefix '-c' $probe 2>$null
    } catch { return $null } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0 -or -not $out -or $out.Count -lt 2) { return $null }
    try { $version = [version]$out[0] } catch { return $null }
    if ($version -lt $MinPython) {
        Log "  found Python $version at $($out[1]) - too old, need $MinPython+" 'DarkGray'
        return $null
    }
    if (-not $out[1]) { return $null }
    return [pscustomobject]@{ Exe = $out[1]; Version = $version }
}

function Find-Python {
    # The Windows launcher first: it knows about every installed version and
    # is unaffected by the Microsoft Store's python.exe stub, which answers
    # on PATH but is not a working interpreter.
    $found = Test-PythonCandidate -Command 'py' -Prefix @('-3')
    if ($found) { return $found }
    foreach ($name in @('python', 'python3')) {
        $found = Test-PythonCandidate -Command $name
        if ($found) { return $found }
    }
    $globs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        'C:\Python3*\python.exe',
        (Join-Path $env:ProgramFiles 'Python3*\python.exe')
    )
    foreach ($glob in $globs) {
        $hits = @(Get-ChildItem -Path $glob -ErrorAction SilentlyContinue |
                  Sort-Object FullName -Descending)
        foreach ($hit in $hits) {
            $found = Test-PythonCandidate -Command $hit.FullName
            if ($found) { return $found }
        }
    }
    return $null
}

function Install-Python {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        'ARM64' { $suffix = '-arm64' }
        'AMD64' { $suffix = '-amd64' }
        default { $suffix = '' }          # 32-bit Windows
    }
    $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion$suffix.exe"
    $installer = Join-Path $env:TEMP "python-$PyVersion$suffix.exe"

    Log "  downloading Python $PyVersion (about 27 MB)..." 'Gray'
    Log "  from $url" -Quiet
    try {
        $progress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'      # ~10x faster download
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        $ProgressPreference = $progress
    } catch {
        Log "  download failed: $($_.Exception.Message)" -Quiet
        Fail 'Python could not be downloaded.' @'
This usually means the PC is offline or a company firewall blocked the
download. Two ways forward:

  * Check the internet connection and run this installer again, or
  * Install Python yourself from https://www.python.org/downloads/
    (tick "Add python.exe to PATH" on the first screen), then run this
    installer again - it will find it and carry on.
'@
    }

    Log '  installing Python (this takes a minute, no clicking needed)...' 'Gray'
    $installArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1',
                     'Include_test=0', 'Include_launcher=1', 'AssociateFiles=0',
                     'Shortcuts=0')
    $proc = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    Log "  python installer exit code $($proc.ExitCode)" -Quiet
    Remove-Item $installer -ErrorAction SilentlyContinue

    # PATH in this already-running window is stale, so never trust the bare
    # name here - Find-Python looks in the known install locations too.
    $found = Find-Python
    if (-not $found) {
        Fail 'Python installed but could not be found afterwards.' @'
Restart the computer and run this installer again. If it still fails,
install Python manually from https://www.python.org/downloads/ and tick
"Add python.exe to PATH" on the first screen.
'@
    }
    return $found
}

# ---------------------------------------------------------------------------
# Launchers and shortcuts
# ---------------------------------------------------------------------------

function Write-Launcher {
    param([string]$Name, [string]$Body)
    $path = Join-Path $Target "$Name.bat"
    # ASCII + CRLF: cmd.exe is not reliable with anything else.
    $text = ($Body -replace "`r`n", "`n").TrimEnd("`n") + "`n"
    $text = $text -replace "`n", "`r`n"
    [System.IO.File]::WriteAllText($path, $text, [System.Text.Encoding]::ASCII)
    Log "  $Name.bat" -Quiet
    return $path
}

function New-Shortcut {
    param([string]$Path, [string]$TargetPath, [string]$Icon, [string]$Description)
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $TargetPath
    $link.WorkingDirectory = $Target
    $link.Description = $Description
    if ($Icon -and (Test-Path $Icon)) { $link.IconLocation = "$Icon,0" }
    $link.Save()
    Log "  $(Split-Path -Leaf $Path)" -Quiet
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

Clear-Host
Write-Host ''
Write-Host '  ==================================================================' -ForegroundColor White
Write-Host "   $AppName - installing on this PC" -ForegroundColor White
Write-Host '  ==================================================================' -ForegroundColor White
Write-Host ''
Write-Host '  Finds the fairs and festivals worth booking, ranked by how much' -ForegroundColor Gray
Write-Host '  money they should make you.' -ForegroundColor Gray
Write-Host ''
Write-Host '  Nothing needs administrator rights. Take about 3 minutes, plus a' -ForegroundColor Gray
Write-Host '  few questions about your business at the end.' -ForegroundColor Gray

Log "==== install started $(Get-Date) ====" -Quiet
Log "source=$Source target=$Target user=$env:USERNAME" -Quiet
Log "os=$([Environment]::OSVersion.VersionString) arch=$env:PROCESSOR_ARCHITECTURE ps=$($PSVersionTable.PSVersion)" -Quiet

# --- 1. sanity-check where we are running from -----------------------------
Step 1 'Checking the download'
if (-not (Test-Path (Join-Path $Source 'fnscraper\cli.py'))) {
    Fail 'The program files are missing from this folder.' @'
This almost always means the installer was started from INSIDE the ZIP
file. Windows only unpacks the one file you double-click, so the rest of
the program is not there.

Fix it like this:
  1. Right-click the ZIP file you downloaded.
  2. Choose "Extract All..." and click Extract.
  3. Open the folder that appears and double-click Install.cmd there.
'@
}
Log "  looks good: $Source" 'Gray'

# --- 2. python -------------------------------------------------------------
Step 2 'Looking for Python'
$python = Find-Python
if ($python) {
    Log "  found Python $($python.Version): $($python.Exe)" 'Green'
} else {
    Log '  no usable Python on this PC - installing it now.' 'Yellow'
    $python = Install-Python
    Log "  installed Python $($python.Version): $($python.Exe)" 'Green'
}

# --- 3. copy the program to a permanent home -------------------------------
Step 3 'Copying the program into place'
$sourceFull = (Resolve-Path $Source).Path.TrimEnd('\')
$targetFull = $Target.TrimEnd('\')
if ($sourceFull -ieq $targetFull) {
    Log '  already installed here - refreshing in place.' 'Gray'
} else {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    # Settings and results already on this PC are never overwritten: the
    # excluded files are exactly the ones an existing install owns.
    $excludeDirs  = @('.git', '.venv', '__pycache__', '.pytest_cache', 'data',
                      'reports', 'applications', '.idea', '.vscode')
    $excludeFiles = @('.env', 'vendor_profile.json', 'business.json', '.DS_Store', '*.pyc')
    $rc = @('/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1',
            '/XD') + $excludeDirs + @('/XF') + $excludeFiles
    & robocopy $sourceFull $targetFull @rc | Out-Null
    $code = $LASTEXITCODE
    $global:LASTEXITCODE = 0
    Log "  robocopy exit code $code" -Quiet
    if ($code -ge 8) {
        Fail "The files could not be copied to $Target (code $code)." @'
Something is holding those files open or blocking the copy - most often
antivirus, or an open Show Finder window. Close any Show Finder windows
and run the installer again.
'@
    }
    Log "  installed to $Target" 'Green'
}

# The working folders are excluded from the copy and absent from the ZIP,
# so a brand-new install has none of them. Create them up front: it costs
# nothing and means "Open My Results" works before the first search.
foreach ($dir in @('reports', 'data\cache', 'applications')) {
    New-Item -ItemType Directory -Path (Join-Path $Target $dir) -Force | Out-Null
}

# --- 4. private python environment + libraries -----------------------------
Step 4 'Setting up the program''s own Python environment'
$venv   = Join-Path $Target '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'

if (Test-Path $venvPy) {
    if (-not (Test-PythonCandidate -Command $venvPy)) {
        Log '  the existing environment is broken - rebuilding it.' 'Yellow'
        Remove-Item $venv -Recurse -Force -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path $venvPy)) {
    Log '  creating it...' 'Gray'
    Invoke-Native $python.Exe @('-m', 'venv', $venv) | Out-Null
    if (-not (Test-Path $venvPy)) {
        Fail 'The Python environment could not be created.' @'
Reinstall Python from https://www.python.org/downloads/ - make sure the
optional feature "pip" stays ticked - then run this installer again.
'@
    }
}

Log '  installing the libraries it needs (a minute or two)...' 'Gray'
# An old pip that cannot upgrade itself is not a problem, so ignore the code.
Invoke-Native $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip',
                        '--disable-pip-version-check', '--no-warn-script-location') | Out-Null

$requirements = Join-Path $Target 'requirements.txt'
$pipCode = Invoke-Native $venvPy @('-m', 'pip', 'install', '-r', $requirements,
                                   '--disable-pip-version-check', '--no-warn-script-location')
if ($pipCode -ne 0) {
    Fail 'The libraries could not be installed.' @'
This is nearly always the internet connection or a company firewall
blocking pypi.org. Check the connection and run this installer again -
nothing installed so far has to be undone.
'@
}

# Prove the whole thing actually imports before promising it works.
$importCheck = Invoke-Native $venvPy `
    @('-c', "import fnscraper.cli, requests, bs4, openpyxl, pypdf; print('ok')") `
    -WorkingDirectory $Target
if ($importCheck -ne 0) {
    Fail 'The program did not start correctly after installing.' `
         "See the log for the exact error: $LogFile"
}
Log '  environment ready.' 'Green'

# --- 5. launchers and icons ------------------------------------------------
Step 5 'Creating your desktop icons'

$header = @'
@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Show Finder is not installed correctly - run Install.cmd again.
  echo.
  pause
  exit /b 1
)
'@

$needsSetup = @'
if not exist "business.json" (
  echo.
  echo  First-time setup has not been done yet. Starting it now...
  echo.
  ".venv\Scripts\python.exe" -m fnscraper setup
  if errorlevel 1 (
    echo.
    echo  Setup was not completed, so there is nothing to search with yet.
    echo.
    pause
    exit /b 1
  )
)
'@

$findShows = Write-Launcher '1 - Find My Shows' @"
$header
title Show Finder - Finding your shows
$needsSetup
echo.
echo  ==================================================================
echo   FINDING THE BEST SHOWS FOR YOU
echo  ==================================================================
echo.
echo   The first search of the day reads a few thousand event listings
echo   and can take 45 to 75 minutes. Leave this window open - it will
echo   tell you what it is doing as it goes.
echo.
echo   You can keep using the computer for other things meanwhile.
echo.
".venv\Scripts\python.exe" -m fnscraper best
if errorlevel 1 goto failed
echo.
echo  ==================================================================
echo   DONE - opening the folder with your results
echo  ==================================================================
echo.
start "" "%~dp0reports"
echo  Press any key to close this window.
pause >nul
exit /b 0

:failed
echo.
echo  ------------------------------------------------------------------
echo   That did not finish. The most common reasons:
echo     * the internet connection dropped
echo     * festivalnet.com was down or busy
echo     * no shows matched your settings (try a longer drive time in
echo       "Change My Settings")
echo   Try again in a few minutes. Nothing was broken.
echo  ------------------------------------------------------------------
echo.
pause
exit /b 1
"@

$browse = Write-Launcher '2 - Pick Shows From The List' @"
$header
title Show Finder - Pick your shows
$needsSetup
if not exist "reports\results.json" (
  echo.
  echo  No results yet. Run "1 - Find My Shows" first.
  echo.
  pause
  exit /b 1
)
echo.
rem The picker's columns are far wider than a stock 80-column console;
rem Windows Terminal ignores this harmlessly.
mode con: cols=150 lines=45 >nul 2>&1
echo  Loading your last results...
echo.
echo  HOW TO USE THE LIST:
echo    Arrow keys  move up and down
echo    SPACE       tick or untick a show
echo    D           see full details for a show
echo    ENTER       save the ticked shows and exit
echo    Q           quit without saving
echo.
pause
".venv\Scripts\python.exe" -m fnscraper --browse
if errorlevel 1 (
  echo.
  echo  The list could not be opened. Try making this window bigger,
  echo  or run "1 - Find My Shows" again.
  echo.
)
echo.
pause
"@

$apply = Write-Launcher '3 - Get The Applications' @"
$header
title Show Finder - Downloading applications
if not exist "reports\selected_shows.csv" (
  echo.
  echo  You have not picked any shows yet.
  echo  Run "2 - Pick Shows From The List" first, tick the shows you want,
  echo  and press ENTER to save them.
  echo.
  pause
  exit /b 1
)
echo.
echo  Looking up each show you picked and downloading its vendor
echo  application. Fillable forms are filled in with your details.
echo.
echo  ALWAYS read a filled-in application before you send it.
echo.
".venv\Scripts\python.exe" -m fnscraper apply
if not errorlevel 1 start "" "%~dp0applications"
echo.
pause
"@

$settings = Write-Launcher 'Change My Settings' @"
$header
title Show Finder - Settings
".venv\Scripts\python.exe" -m fnscraper setup
echo.
pause
"@

$reports = Write-Launcher 'Open My Results' @"
$header
if not exist "reports" mkdir "reports"
start "" "%~dp0reports"
"@

Write-Launcher 'Uninstall' @"
@echo off
rem Deleting the folder this script is running from needs a helper that
rem outlives it, so the removal is handed to a one-shot batch file in TEMP.
title Show Finder - Uninstall
cd /d "%~dp0"
set "SHOWFINDER_DIR=$Target"
echo.
echo  This removes Show Finder from this PC, including your settings,
echo  your saved results, and any downloaded applications.
echo.
set "CONFIRM="
set /p CONFIRM=Type YES and press Enter to remove it: 
if /i not "%CONFIRM%"=="YES" goto keep
del "$desktop\Show Finder - Find My Shows.lnk" 2>nul
del "$desktop\Show Finder - Pick Shows.lnk" 2>nul
del "$desktop\Show Finder - Settings.lnk" 2>nul
rmdir /s /q "$startMenu" 2>nul
echo.
echo  Removing the program folder...
set "CLEANUP=%TEMP%\ShowFinder-remove.bat"
> "%CLEANUP%" echo @echo off
>>"%CLEANUP%" echo timeout /t 2 ^>nul
>>"%CLEANUP%" echo rmdir /s /q "%SHOWFINDER_DIR%"
>>"%CLEANUP%" echo echo.
>>"%CLEANUP%" echo echo  Show Finder has been removed.
>>"%CLEANUP%" echo echo.
>>"%CLEANUP%" echo pause
cd /d "%TEMP%"
start "" "%CLEANUP%"
exit /b 0

:keep
echo.
echo  Nothing was removed.
echo.
pause
exit /b 0
"@ | Out-Null

$icons = Join-Path $Target 'windows\icons'
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Show Finder'
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null

$shortcuts = @(
    @{ Name = 'Show Finder - Find My Shows'; Bat = $findShows; Icon = 'find-shows.ico'
       Desc = 'Search for the most profitable shows to book' },
    @{ Name = 'Show Finder - Pick Shows';    Bat = $browse;   Icon = 'reports.ico'
       Desc = 'Choose which shows to apply for' },
    @{ Name = 'Show Finder - Settings';      Bat = $settings; Icon = 'settings.ico'
       Desc = 'Change your business details, prices, and travel limits' }
)
foreach ($sc in $shortcuts) {
    $icon = Join-Path $icons $sc.Icon
    New-Shortcut (Join-Path $desktop "$($sc.Name).lnk") $sc.Bat $icon $sc.Desc
    New-Shortcut (Join-Path $startMenu "$($sc.Name).lnk") $sc.Bat $icon $sc.Desc
}
# The less-used ones live in the Start Menu only, so the Desktop stays clean.
New-Shortcut (Join-Path $startMenu 'Show Finder - Get The Applications.lnk') `
    $apply (Join-Path $icons 'reports.ico') 'Download and fill in vendor applications'
New-Shortcut (Join-Path $startMenu 'Show Finder - Open My Results.lnk') `
    $reports (Join-Path $icons 'reports.ico') 'Open the folder with your results'
Log "  icons added to the Desktop and the Start Menu." 'Green'

# --- 6. configure it for this business -------------------------------------
Step 6 'Setting up your business details'
if ($SkipWizard) {
    Log '  skipped (run "Change My Settings" before the first search).' 'Yellow'
} else {
    Write-Host ''
    Push-Location $Target
    try {
        & $venvPy -m fnscraper setup
        $wizard = $LASTEXITCODE
    } finally {
        Pop-Location
        $global:LASTEXITCODE = 0
    }
    if ($wizard -ne 0) {
        Write-Host ''
        Log '  Setup was not finished. Everything else is installed - open' 'Yellow'
        Log '  "Show Finder - Settings" on the Desktop when you are ready.' 'Yellow'
    }
}

Write-Host ''
Write-Host '  ==================================================================' -ForegroundColor Green
Write-Host '   INSTALLED' -ForegroundColor Green
Write-Host '  ==================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '   Three icons are on your Desktop:' -ForegroundColor White
Write-Host ''
Write-Host '     Show Finder - Find My Shows   search for shows worth booking' -ForegroundColor Gray
Write-Host '     Show Finder - Pick Shows      choose the ones you want' -ForegroundColor Gray
Write-Host '     Show Finder - Settings        change prices, costs, drive time' -ForegroundColor Gray
Write-Host ''
Write-Host "   Installed in: $Target" -ForegroundColor DarkGray
Write-Host "   Install log:  $LogFile" -ForegroundColor DarkGray
Write-Host ''
Log '==== install finished ====' -Quiet
exit 0
