[CmdletBinding()]
param(
    [string]$RunDir,
    [string]$OptiTrackCsv,
    [string]$PythonExe = "python",
    [string[]]$Scenarios
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
    Write-Host "$PythonExe $($Arguments -join ' ')"

    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Krok '$Title' selhal s exit code $LASTEXITCODE."
    }
}

function Add-OptionalArgument {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Target,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string]$Value
    )

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $Target.Add($Name)
        $Target.Add($Value)
    }
}

function Add-OptionalArgumentList {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Target,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string[]]$Values
    )

    if ($null -ne $Values -and $Values.Count -gt 0) {
        $Target.Add($Name)
        foreach ($value in $Values) {
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $Target.Add($value)
            }
        }
    }
}

$splitArgs = [System.Collections.Generic.List[string]]::new()
$splitArgs.Add((Join-Path $scriptDir "split_scenarios.py"))
Add-OptionalArgument -Target $splitArgs -Name "--run-dir" -Value $RunDir

$fusionArgs = [System.Collections.Generic.List[string]]::new()
$fusionArgs.Add((Join-Path $scriptDir "run_offline_fusion.py"))
Add-OptionalArgument -Target $fusionArgs -Name "--run-dir" -Value $RunDir
Add-OptionalArgumentList -Target $fusionArgs -Name "--scenarios" -Values $Scenarios

$evaluateArgs = [System.Collections.Generic.List[string]]::new()
$evaluateArgs.Add((Join-Path $scriptDir "evaluate_all.py"))
Add-OptionalArgument -Target $evaluateArgs -Name "--run-dir" -Value $RunDir
Add-OptionalArgument -Target $evaluateArgs -Name "--optitrack-csv" -Value $OptiTrackCsv
Add-OptionalArgumentList -Target $evaluateArgs -Name "--scenarios" -Values $Scenarios

Write-Host "Projekt: $projectDir"
if (-not [string]::IsNullOrWhiteSpace($RunDir)) {
    Write-Host "RunDir: $RunDir"
}
if (-not [string]::IsNullOrWhiteSpace($OptiTrackCsv)) {
    Write-Host "OptiTrackCsv: $OptiTrackCsv"
}
if ($null -ne $Scenarios -and $Scenarios.Count -gt 0) {
    Write-Host "Scenarios: $($Scenarios -join ', ')"
}

Push-Location $projectDir
try {
    Invoke-Step -Title "Split raw data into scenarios" -Arguments $splitArgs
    Invoke-Step -Title "Run offline fusion for all scenarios" -Arguments $fusionArgs
    Invoke-Step -Title "Evaluate all scenarios and generate graphs" -Arguments $evaluateArgs

    Write-Host ""
    Write-Host "Pipeline hotova." -ForegroundColor Green
}
finally {
    Pop-Location
}
