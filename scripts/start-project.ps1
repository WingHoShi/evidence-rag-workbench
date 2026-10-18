param([switch]$NoBrowser, [switch]$Build, [string]$DockerPath)

$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:AppUrl = 'http://127.0.0.1:8000'

function Resolve-DockerPath {
    param([string]$ExplicitPath)
    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) { throw 'Docker executable not found at the specified path.' }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Docker not found. Install and open Docker Desktop, or pass -DockerPath with its full executable path. See README.'
}

function Invoke-DockerCommand {
    param([string[]]$CommandArgs)
    # PowerShell 5.1 wraps native stderr as ErrorRecord even on exit 0.
    # Convert it before Out-Host can render progress as a false error.
    $ErrorActionPreference = 'Continue'
    $result = & $script:Docker @CommandArgs 2>&1 | ForEach-Object { $_.ToString() }
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) { throw "Docker command failed (exit $nativeExit).`n$($result -join [Environment]::NewLine)" }
    return $result
}

function Assert-LocalDockerEndpoint {
    param([string]$Endpoint)
    if ($Endpoint -notmatch '^npipe:/+\./pipe/[A-Za-z0-9_.-]+$') {
        throw 'Only a local Docker Desktop named-pipe engine is supported; remote Docker contexts are not used.'
    }
}

function Resolve-ComposePath {
    param([string]$DockerExecutable)
    $sibling = Join-Path (Split-Path -Parent $DockerExecutable) 'docker-compose.exe'
    if (Test-Path -LiteralPath $sibling -PathType Leaf) { return $sibling }
    throw 'Docker Compose not found. Install Docker Desktop with Compose, or check the executable directory.'
}

function Invoke-StandaloneCompose {
    param([string[]]$ComposeArgs)
    $ErrorActionPreference = 'Continue'
    $result = & $script:StandaloneCompose @ComposeArgs 2>&1 | ForEach-Object { $_.ToString() }
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) { throw "Docker Compose command failed (exit $nativeExit).`n$($result -join [Environment]::NewLine)" }
    return $result
}

function Invoke-ComposeCommand {
    param([string[]]$ComposeArgs)
    if ($script:StandaloneCompose) { return Invoke-StandaloneCompose -ComposeArgs $ComposeArgs }
    return Invoke-DockerCommand -CommandArgs (@('compose') + $ComposeArgs)
}

function Assert-ComposeVersion {
    param([string]$VersionText)
    if ($VersionText -notmatch '(\d+)\.(\d+)\.(\d+)' -or
        [version]$Matches[0] -lt [version]'2.24.0') {
        throw 'Docker Compose 2.24 or newer is required. Update Docker Desktop.'
    }
}

function Test-AppReady {
    try {
        $health = Invoke-RestMethod -Uri "$script:AppUrl/api/health" -TimeoutSec 5
        $null = Invoke-RestMethod -Uri "$script:AppUrl/api/knowledge-bases" -TimeoutSec 5
        $page = Invoke-WebRequest -Uri $script:AppUrl -UseBasicParsing -TimeoutSec 5
        return ($health.status -eq 'ok' -and $page.StatusCode -eq 200 -and $page.Content -match '<div id="root">')
    } catch { return $false }
}

function Wait-AppReady {
    $deadline = (Get-Date).AddMinutes(2)
    while (-not (Test-AppReady)) {
        if ((Get-Date) -ge $deadline) {
            throw 'App readiness timeout. Run docker compose ps and docker compose logs --tail 50 api. Containers were left running.'
        }
        Start-Sleep -Seconds 2
    }
}

function Open-ProjectBrowser { Start-Process $script:AppUrl }

function Invoke-ProjectStart {
    param([switch]$NoBrowser, [switch]$Build, [string]$DockerPath)
    $script:Docker = Resolve-DockerPath -ExplicitPath $DockerPath
    Push-Location -LiteralPath $script:ProjectRoot
    try {
        Write-Host '[1/3] Checking Docker Desktop and Compose...'
        try { $null = Invoke-DockerCommand -CommandArgs @('info', '--format', '{{.ServerVersion}}') }
        catch { throw 'Docker Desktop is not ready. Open Docker Desktop manually, wait until the Linux engine is running, then click this shortcut again. No containers were started by this attempt.' }
        $script:StandaloneCompose = $null
        try { $versionText = (Invoke-DockerCommand -CommandArgs @('compose', 'version')) -join ' ' }
        catch {
            $script:StandaloneCompose = Resolve-ComposePath -DockerExecutable $script:Docker
            $versionText = (Invoke-StandaloneCompose -ComposeArgs @('version')) -join ' '
        }
        Assert-ComposeVersion $versionText
        # DOCKER_CONTEXT overrides DOCKER_HOST in the Docker CLI.
        if ($env:DOCKER_HOST -and -not $env:DOCKER_CONTEXT) {
            $endpoint = $env:DOCKER_HOST
        } else {
            $endpoint = ((Invoke-DockerCommand -CommandArgs @('context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}')) -join '').Trim('"')
        }
        Assert-LocalDockerEndpoint $endpoint

        $null = New-Item -ItemType Directory -Path (Join-Path $script:ProjectRoot 'runtime-config') -Force
        Write-Host '[2/3] Starting Evidence RAG Workbench...'
        $commandArgs = @('-f', (Join-Path $script:ProjectRoot 'compose.yaml'), 'up', '-d')
        if ($Build) {
            Write-Host 'Explicit build requested: dependencies/images may be downloaded. Existing data volumes are retained.'
            $commandArgs += '--build'
        } else { $commandArgs += @('--no-build', '--pull', 'never') }
        try { Invoke-ComposeCommand -ComposeArgs $commandArgs | Out-Host }
        catch { throw "Startup failed. $($_.Exception.Message)`nFor the first build or after updating code, use: .\Evidence Studio.cmd -Build . See README for logs and setup." }
        Write-Host '[3/3] Waiting for API, database and frontend...'
        Wait-AppReady
        Write-Host "Ready: $script:AppUrl" -ForegroundColor Green
        if (-not $NoBrowser) { Open-ProjectBrowser }
    } finally { Pop-Location }
}

# Loading this file for tests defines functions only; it never starts anything.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-ProjectStart -NoBrowser:$NoBrowser -Build:$Build -DockerPath $DockerPath
        exit 0
    } catch {
        Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}
