param(
    [string]$OutDir = "$(Split-Path -Parent $MyInvocation.MyCommand.Path)\certs"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$generator = Join-Path $scriptDir "generate_certs.py"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv run python $generator --out-dir $OutDir
} else {
    python $generator --out-dir $OutDir
}
