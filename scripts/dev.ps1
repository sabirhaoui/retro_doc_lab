param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("setup", "lint", "test", "run")]
    [string]$Task
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "La commande '$Command' a échoué avec le code $LASTEXITCODE."
    }
}

Push-Location $RepoRoot
try {
    switch ($Task) {
        "setup" {
            Invoke-Checked "python" @("-m", "pip", "install", "-e", ".[dev]")
        }
        "lint" {
            Invoke-Checked "ruff" @("check", "src", "tests")
            Invoke-Checked "mypy" @("src")
        }
        "test" {
            Invoke-Checked "pytest" @()
        }
        "run" {
            Invoke-Checked "retro-doc-lab" @(
                "analyze",
                "fixtures\fastapi_api",
                "--out",
                "output\example",
                "--no-llm"
            )
        }
    }
}
finally {
    Pop-Location
}
