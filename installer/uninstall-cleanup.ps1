# Apex Roller uninstall cleanup.
# Runs as a separate PowerShell process during Inno's [UninstallRun] step,
# so it isn't tangled with apex-roller.exe (which we have to kill).
#
# Responsibilities:
#   1. Kill any running apex-roller.exe (tray instance + bootloader child).
#   2. Deregister 'APEX_ROLLER' from SteelSeries GameSense.
#   3. Wipe %LocalAppData%\ApexRoller (config + logs).
#   4. Sleep enough for the OS to fully release the install dir's
#      apex-roller.exe before the Inno uninstaller deletes it.

$ErrorActionPreference = 'SilentlyContinue'

# Optional diagnostic marker. Comment out the next two lines to disable.
$marker = Join-Path $env:TEMP 'apex-cleanup-marker.txt'
function Log($msg) { try { Add-Content -LiteralPath $marker -Value "$(Get-Date -Format 'HH:mm:ss') $msg" } catch {} }

Log "=== ps cleanup START pid=$PID ==="
Log "  LocalAppData=$($env:LocalAppData)"

# --- 1. Kill apex-roller.exe ---------------------------------------------
$procs = Get-Process -Name 'apex-roller' -ErrorAction SilentlyContinue
Log "  found apex-roller pids: $(@($procs | ForEach-Object Id) -join ',')"
foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.Id -Force
        Log "    killed pid=$($p.Id)"
    } catch {
        Log "    kill pid=$($p.Id) failed: $_"
    }
}

# Wait generously for the kernel to finish reaping and release file
# handles. A killed process's log file enters "delete pending" state and
# can stay invisible to Test-Path for several seconds after taskkill.
Start-Sleep -Seconds 10

# Re-check and re-kill any stragglers (e.g. a process that spawned during
# our wait).
$leftover = Get-Process -Name 'apex-roller' -ErrorAction SilentlyContinue
if ($leftover) {
    Log "  WARNING leftover pids after wait: $(@($leftover | ForEach-Object Id) -join ',')"
    foreach ($p in $leftover) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

# --- 2. Deregister from SteelSeries GameSense ----------------------------
try {
    $coreProps = Join-Path $env:ProgramData 'SteelSeries\SteelSeries Engine 3\coreProps.json'
    if (Test-Path -LiteralPath $coreProps) {
        $props = Get-Content -LiteralPath $coreProps -Raw | ConvertFrom-Json
        $body = '{"game":"APEX_ROLLER"}'
        Invoke-WebRequest -Uri "http://$($props.address)/remove_game" -Method Post -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5 | Out-Null
        Log "  gamesense remove_game posted"
    } else {
        Log "  coreProps.json not present; skipping GameSense deregister"
    }
} catch {
    Log "  GameSense deregister failed (harmless): $_"
}

# --- 3. Wipe %LocalAppData%\ApexRoller ------------------------------------
# Strategy:
#   a) UNCONDITIONALLY schedule the known paths for reboot deletion. Test-Path
#      on a "delete pending" directory can falsely return False, so we don't
#      gate this on existence checks. MoveFileEx is silent on already-gone
#      paths -- no harm if they're already deleted.
#   b) Iteratively delete leaf files (don't rely on Remove-Item -Recurse,
#      which can bail when ONE child is locked).
#   c) Sleep + recheck.
Add-Type -Namespace W -Name FS -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
public static extern bool MoveFileExW(string ExistingFileName, string NewFileName, int Flags);
'@
$MOVEFILE_DELAY_UNTIL_REBOOT = 4

$appData = Join-Path $env:LocalAppData 'ApexRoller'
Log "  appData=$appData (Test-Path says exists=$(Test-Path -LiteralPath $appData))"

# a) UNCONDITIONAL reboot-deletion scheduling for known paths. If they
#    don't exist right now, MoveFileEx fails silently (we ignore). If they
#    appear later (delete-pending rollback, etc.), the OS deletes them on
#    next reboot.
$known = @(
    "$appData\logs\apex-roller.log",
    "$appData\logs\apex-roller.log.1",
    "$appData\logs\apex-roller.log.2",
    "$appData\logs\apex-roller.log.3",
    "$appData\logs",
    "$appData\config.json",
    "$appData"
)
foreach ($p in $known) {
    $ok = [W.FS]::MoveFileExW($p, $null, $MOVEFILE_DELAY_UNTIL_REBOOT)
    Log "  reboot-schedule $p -> $ok"
}

# b) Iterative leaf-first deletion. Best-effort; per-file errors swallowed.
for ($i = 0; $i -lt 20; $i++) {
    $children = @()
    try { $children = Get-ChildItem -LiteralPath $appData -Recurse -Force -ErrorAction Stop } catch {}
    if (-not $children) { break }
    $children |
        Sort-Object -Property { $_.FullName.Length } -Descending |
        ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop } catch {}
        }
    try { Remove-Item -LiteralPath $appData -Force -ErrorAction Stop } catch {}
    Start-Sleep -Milliseconds 500
}

# c) Final settle + verification.
Start-Sleep -Seconds 5
$finalExists = Test-Path -LiteralPath $appData
Log "  FINAL CHECK: appdata exists=$finalExists"
if ($finalExists) {
    Get-ChildItem -LiteralPath $appData -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        Log "    leftover: $($_.FullName) (mtime $($_.LastWriteTime))"
    }
    # Re-schedule everything currently visible (in case any new files
    # appeared after the initial unconditional schedule).
    Get-ChildItem -LiteralPath $appData -Recurse -Force -ErrorAction SilentlyContinue |
        Sort-Object -Property { $_.FullName.Length } -Descending |
        ForEach-Object { [W.FS]::MoveFileExW($_.FullName, $null, $MOVEFILE_DELAY_UNTIL_REBOOT) | Out-Null }
    [W.FS]::MoveFileExW($appData, $null, $MOVEFILE_DELAY_UNTIL_REBOOT) | Out-Null
}
Log "=== ps cleanup END ==="
