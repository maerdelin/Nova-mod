# NOVA_GLOBAL_LOGS_TOGGLE_V1
# Settings > Logs checkbox is the ONLY gate. ADB only exports Logcat.
# No setprop, broadcast, shell app-control command, or server-side collection.
[CmdletBinding()]
param(
    [string]$Adb = 'adb',
    [string]$Serial = '',
    [string]$OutputPath = '',
    [ValidateRange(1,86400)][int]$DurationSeconds = 300
)
$ErrorActionPreference = 'Stop'
$deviceArgs = @()
if ($Serial) { $deviceArgs = @('-s', $Serial) }
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (-not $desktop) { $desktop = $HOME }
    $OutputPath = Join-Path $desktop ('NOVA_LOGS_' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
}
$proc = $null
try {
    & $Adb @deviceArgs wait-for-device | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'ADB device unavailable.' }
    Write-Host 'App setting > 日志 must be checked to collect application diagnostics.'
    Write-Host "Saving complete Logcat to $OutputPath"
    # Capture ALL buffers, not just a limited selection of app tags.
    # -T 1 starts at the latest available record; never clears Android logs.
    $argsList = @($deviceArgs + @('logcat','-b','all','-v','threadtime','-T','1'))
    $proc = Start-Process -FilePath $Adb -ArgumentList $argsList -RedirectStandardOutput $OutputPath -NoNewWindow -PassThru
    $until = (Get-Date).AddSeconds($DurationSeconds)
    while (-not $proc.HasExited -and (Get-Date) -lt $until) {
        Start-Sleep -Milliseconds 200
    }
} finally {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $proc.WaitForExit()
    }
    Write-Host "Saved: $OutputPath"
    Write-Host 'The app checkbox value was not modified.'
}
