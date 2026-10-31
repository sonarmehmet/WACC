# WACC environment check (read-only). Run: powershell -ExecutionPolicy Bypass -File scripts\check_env.ps1
$ErrorActionPreference = "SilentlyContinue"
$report = [ordered]@{}

$report.windows = (Get-CimInstance Win32_OperatingSystem).Caption + " " + (Get-CimInstance Win32_OperatingSystem).Version
$report.ram_gb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
$report.gpu = $gpu.Name
$nv = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null
$report.nvidia_smi = if ($nv) { $nv } else { "not found" }
$disk = Get-PSDrive C
$report.disk_c_free_gb = [math]::Round($disk.Free / 1GB, 1)

function Ver($cmd, $arg) {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $c) { return "MISSING" }
    return ((& $cmd $arg 2>&1 | Select-Object -First 1) -as [string])
}
$report.python  = Ver "python" "--version"
$report.git     = Ver "git" "--version"
$report.node    = Ver "node" "--version"
$report.flutter = Ver "flutter" "--version"
$report.dart    = Ver "dart" "--version"
$report.adb     = Ver "adb" "--version"
$report.java    = Ver "java" "-version"
$report.android_sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { "MISSING (ANDROID_HOME not set)" }
$report.android_studio = if (Test-Path "C:\Program Files\Android\Android Studio") { "found" } else { "not found" }

$missing = $report.GetEnumerator() | Where-Object { "$($_.Value)" -like "MISSING*" -or "$($_.Value)" -eq "not found" } | ForEach-Object { $_.Key }
$report.missing = @($missing)

$out = Join-Path (Split-Path $PSScriptRoot -Parent) "data\env_report.json"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$report | ConvertTo-Json | Set-Content -Encoding UTF8 $out
$report | ConvertTo-Json
Write-Host "`nRapor: $out"
