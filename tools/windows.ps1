param([ValidateSet('start','stop','settings','setup','check','diagnose','local-hd','update')][string]$Action='start')
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $sourceRoot
$candidatePaths=@($env:BAILONG_PYTHON,(Join-Path $sourceRoot '.venv\Scripts\python.exe'),(Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$pythonCalls=@()
foreach ($candidatePython in $candidatePaths) {
  if ($candidatePython -and (Test-Path -LiteralPath $candidatePython)) {$pythonCalls+=,@($candidatePython)}
}
if (Get-Command py -ErrorAction SilentlyContinue) {$pythonCalls+=,@('py','-3.12');$pythonCalls+=,@('py','-3.13')}
if (Get-Command python -ErrorAction SilentlyContinue) {$pythonCalls+=,@('python')}
foreach ($pythonCall in $pythonCalls) {
  $pythonExe=$pythonCall[0]
  $pythonArgs=@($pythonCall | Select-Object -Skip 1)
  try { & $pythonExe @pythonArgs -c 'import sys; sys.exit(not ((3,12)<=sys.version_info[:2]<(3,14)))' 2>$null }
  catch { continue }
  if ($LASTEXITCODE -eq 0) {
    & $pythonExe @pythonArgs (Join-Path $sourceRoot 'launch.py') $Action
    exit $LASTEXITCODE
  }
}
Write-Host '未找到 Python 3.12 / 3.13，请安装 Python 后重试，或设置 BAILONG_PYTHON。'
exit 1
