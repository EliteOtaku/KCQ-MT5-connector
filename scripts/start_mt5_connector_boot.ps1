# start_mt5_connector_boot.ps1 - KCQ MT5 connector (8090) detached bootstrap.
# Local dev tooling. MUST stay pure ASCII.
# Uses the project venv python (uvicorn lives there, not in global python).
# Launched via Invoke-CimMethod Win32_Process.Create (separate process tree).

$ErrorActionPreference = 'Stop'
$repo = 'D:\AI\KCQ-MT5-connector'
$py = 'D:\AI\KCQ-MT5-connector\.venv\Scripts\python.exe'
$outLog = 'D:\AI\KCQ-MT5-connector\server_out.log'
$errLog = 'D:\AI\KCQ-MT5-connector\server_err.log'

$listener = Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
if ($listener) { exit 0 }

if (-not (Test-Path -LiteralPath $py)) { exit 1 }

Start-Process -FilePath $py -ArgumentList './server.py' -WorkingDirectory $repo `
  -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
