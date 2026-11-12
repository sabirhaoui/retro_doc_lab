# Lance uniquement les fixtures synthetiques du laboratoire.
[CmdletBinding()]
param(
    [string]$PythonPath,
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$SansDashboard
)

$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
$locationPushed = $false

try {
    # Aucun telechargement, installation ou script du depot cible.
    $candidates = if ($PythonPath) { @($PythonPath) } else { @('python', 'py', 'python3') }
    $interpreter = $null
    $pythonArgs = @()
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        $candidateArgs = if ($command.Name -eq 'py.exe' -or $command.Name -eq 'py') { @('-3') } else { @() }
        try {
            & $command.Source @candidateArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $interpreter = $command.Source
                $pythonArgs = $candidateArgs
                break
            }
        } catch { continue }
    }
    if (-not $interpreter) { throw 'Python 3.10+ introuvable. Utilisez -PythonPath avec le chemin de python.exe.' }

    Push-Location -LiteralPath $labRoot
    $locationPushed = $true
    $env:PYTHONPATH = Join-Path $labRoot 'src'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $outputRoot = Join-Path $labRoot 'output'
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

    Write-Host '1/3 - Tests du laboratoire (fixtures synthetiques uniquement)'
    & $interpreter @pythonArgs -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Echec des tests. Le lancement est arrete.' }

    # Un espace neuf par lancement evite tout ecrasement et toute reprise implicite.
    $runId = 'premier-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    $sessionRoot = Join-Path $outputRoot $runId
    $demoLab = Join-Path $sessionRoot 'lab'
    $source = Join-Path $sessionRoot 'source-synthetique'
    $configDirectory = Join-Path $demoLab 'config'
    New-Item -ItemType Directory -Path $source, $configDirectory | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $source 'app.py'), "# Fixture synthetique : ne jamais executer.`ndef greeting():`n    return 'demo'`n", $utf8)
    [System.IO.File]::WriteAllText((Join-Path $source 'README.md'), "# Documentation synthetique`nComparaison semantique non realisee.`n", $utf8)
    $config = [ordered]@{
        schema_version = 1
        implemented = $true
        source_root = $source
        output_root = 'output'
        skills = @('inventory', 'architecture', 'workflows', 'documentation', 'diagrams', 'coverage')
        exclude = @('.env', '*.pem', '*.key')
        max_file_bytes = 1000000
        max_total_bytes = 10000000
        max_files = 2000
        network = 'disabled'
        source_access = 'read-only'
    }
    $configPath = Join-Path $configDirectory 'agent.json'
    [System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 5), $utf8)

    Write-Host '2/3 - Execution de demonstration'
    & $interpreter @pythonArgs pipeline.py --config $configPath run --run-id demonstration
    $pipelineCode = $LASTEXITCODE
    if ($pipelineCode -notin @(0, 3)) { throw "Echec de la pipeline (code $pipelineCode)." }
    Write-Host "Rapports : $(Join-Path $demoLab 'output\demonstration')"
    if ($pipelineCode -eq 3) { Write-Host 'Statut partial attendu : la revue semantique reste a effectuer.' }
    Write-Host "Configuration de cette session : $configPath"
    if (-not $SansDashboard) {
        Write-Host "3/3 - Dashboard : http://127.0.0.1:$Port (Ctrl+C pour arreter)"
        & $interpreter @pythonArgs pipeline.py --config $configPath dashboard --port $Port
        if ($LASTEXITCODE -ne 0) { throw "Dashboard indisponible. Essayez un autre port avec -Port 8766." }
    }
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    exit 1
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
    if ($locationPushed) { Pop-Location }
}
