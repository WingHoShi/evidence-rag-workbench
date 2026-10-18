# Self-contained tests: no real Docker, browser or service is started.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../start-project.ps1')
function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
}
function Assert-Throws([scriptblock]$Action, [string]$Pattern) {
    $caught = $false
    try { & $Action } catch { $caught = $_.Exception.Message -match $Pattern }
    Assert-True $caught "Expected error matching $Pattern"
}
$resolved = Resolve-DockerPath -ExplicitPath (Join-Path $PSScriptRoot '../start-project.ps1')
Assert-True (Test-Path -LiteralPath $resolved) 'Explicit path resolves'
Assert-Throws { Resolve-DockerPath -ExplicitPath 'Z:/missing/docker.exe' } 'Docker'
Assert-Throws { Assert-LocalDockerEndpoint 'tcp://example.com:2375' } 'local'
Assert-Throws { Assert-LocalDockerEndpoint 'ssh://user@example.com' } 'local'
Assert-LocalDockerEndpoint 'npipe:////./pipe/dockerDesktopLinuxEngine'
Assert-Throws { Assert-ComposeVersion 'Docker Compose version v2.20.0' } '2.24'
Assert-ComposeVersion 'Docker Compose version v2.24.0-desktop.1'
$script:Docker = $env:ComSpec
Assert-Throws { Invoke-DockerCommand -CommandArgs @('/d', '/c', 'exit', '17') } 'Docker command failed'
$progress = @(Invoke-DockerCommand -CommandArgs @('/d', '/c', 'echo docker-progress 1>&2'))
Assert-True ($progress.Count -eq 1 -and $progress[0] -is [string] -and $progress[0].Trim() -eq 'docker-progress') 'Successful Docker stderr is plain progress text, not ErrorRecord'
$mixed = @(Invoke-DockerCommand -CommandArgs @('/d', '/c', 'echo standard-output & echo progress-output 1>&2'))
Assert-True ($mixed.Count -eq 2 -and ($mixed | Where-Object { $_ -isnot [string] }).Count -eq 0) 'Mixed native streams remain plain text'
$script:StandaloneCompose = $env:ComSpec
$progress = @(Invoke-StandaloneCompose -ComposeArgs @('/d', '/c', 'echo compose-progress 1>&2'))
Assert-True ($progress.Count -eq 1 -and $progress[0] -is [string] -and $progress[0].Trim() -eq 'compose-progress') 'Successful Compose stderr is plain progress text, not ErrorRecord'
$failureMessage = ''
try { Invoke-StandaloneCompose -ComposeArgs @('/d', '/c', 'echo genuine-failure 1>&2 & exit /b 19') }
catch { $failureMessage = $_.Exception.Message }
Assert-True ($failureMessage -match 'exit 19' -and $failureMessage -match 'genuine-failure') 'Real Compose failures retain exit code and diagnostic text'
$spaceRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('evidence startup ' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $spaceRoot
$fakePath = Join-Path $spaceRoot 'docker.exe'
$null = New-Item -ItemType File -Path $fakePath
Assert-True ((Resolve-DockerPath -ExplicitPath $fakePath) -eq $fakePath) 'Explicit path containing spaces'
$composePath = Join-Path $spaceRoot 'docker-compose.exe'
$null = New-Item -ItemType File -Path $composePath
Assert-True ((Resolve-ComposePath -DockerExecutable $fakePath) -eq $composePath) 'Standalone Compose beside a nonstandard Docker installation'

# Path lookup and standard-install fallback, without requiring Docker installed.
$originalGetCommand = ${function:Resolve-DockerPath}
function Get-Command { param($Name, $ErrorAction) return @{ Source = 'C:/mock-path/docker.exe' } }
Assert-True ((Resolve-DockerPath) -eq 'C:/mock-path/docker.exe') 'PATH discovery first'
function Get-Command { param($Name, $ErrorAction) return $null }
function Test-Path { param($LiteralPath, $PathType) return $LiteralPath -eq (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe') }
Assert-True ((Resolve-DockerPath) -eq (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe')) 'Per-user standard install fallback'
function Test-Path { param($LiteralPath, $PathType) return $false }
Assert-Throws { Resolve-DockerPath } 'Docker not found'
Remove-Item Function:Get-Command
Remove-Item Function:Test-Path

$script:Calls = @()
$script:OpenCount = 0
$script:Mode = 'ok'
$script:ProjectRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('evidence-startup-test-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $script:ProjectRoot
function Resolve-DockerPath { param([string]$ExplicitPath) return 'C:/Program Files/Docker/docker.exe' }
function Invoke-DockerCommand {
    param([string[]]$CommandArgs)
    $script:Calls += ,$CommandArgs
    $command = $CommandArgs -join ' '
    if ($script:Mode -in @('missing-compose', 'standalone') -and $command -eq 'compose version') { throw 'Compose missing' }
    if ($script:Mode -eq 'stopped' -and $command -like 'info*') { throw 'engine not ready' }
    if ($command -eq 'compose version') { return 'Docker Compose version v2.30.0' }
    if ($command -like 'context inspect*') { return '"npipe:////./pipe/dockerDesktopLinuxEngine"' }
    if ($script:Mode -eq 'up-failed' -and $CommandArgs -contains 'up') { throw 'up failed' }
    return ''
}
function Wait-AppReady { if ($script:Mode -eq 'app-timeout') { throw 'app timeout' } }
function Open-ProjectBrowser { $script:OpenCount += 1 }
function Resolve-ComposePath {
    param([string]$DockerExecutable)
    if ($script:Mode -eq 'standalone') { return 'C:/mock/docker-compose.exe' }
    throw 'Compose not installed'
}
function Invoke-StandaloneCompose {
    param([string[]]$ComposeArgs)
    $script:Calls += ,$ComposeArgs
    if ($ComposeArgs -contains 'version') { return 'Docker Compose version v2.30.0' }
    return ''
}

$savedHost = $env:DOCKER_HOST
$savedContext = $env:DOCKER_CONTEXT
$savedConfig = $env:DOCKER_CONFIG
try {
    $env:DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
    $env:DOCKER_CONTEXT = 'my-local-context'
    $env:DOCKER_CONFIG = 'C:/custom docker profile'
    Invoke-ProjectStart -NoBrowser
    $up = @($script:Calls | Where-Object { $_ -contains 'up' })
    Assert-True ($up.Count -eq 1) 'One startup command'
    Assert-True ($up[0] -contains '--no-build') 'Daily startup must not rebuild'
    Assert-True ($up[0] -contains 'never') 'Daily startup must not pull'
    Assert-True ($script:OpenCount -eq 0) 'NoBrowser honored'
    Assert-True ($env:DOCKER_CONTEXT -eq 'my-local-context') 'Context preserved'
    Assert-True ($env:DOCKER_CONFIG -eq 'C:/custom docker profile') 'Config preserved'
    Assert-True ($env:DOCKER_HOST -eq 'npipe:////./pipe/dockerDesktopLinuxEngine') 'Host preserved'
    $script:Calls = @()
    Invoke-ProjectStart -Build
    $up = @($script:Calls | Where-Object { $_ -contains 'up' })
    Assert-True ($up[0] -contains '--build') 'Build requires explicit flag'
    Assert-True ($script:OpenCount -eq 1) 'Browser opens after readiness'
    $script:Mode = 'standalone'
    $script:Calls = @()
    Invoke-ProjectStart -NoBrowser
    $up = @($script:Calls | Where-Object { $_ -contains 'up' })
    Assert-True ($up.Count -eq 1 -and $up[0] -contains '--no-build') 'Standalone Compose fallback launches safely'
    $script:Mode = 'up-failed'
    Assert-Throws { Invoke-ProjectStart -NoBrowser } '-Build'
    $script:Mode = 'stopped'
    Assert-Throws { Invoke-ProjectStart -NoBrowser } 'Docker Desktop'
    $script:Mode = 'missing-compose'
    Assert-Throws { Invoke-ProjectStart -NoBrowser } 'Compose'
    $script:Mode = 'app-timeout'
    Assert-Throws { Invoke-ProjectStart -NoBrowser } 'timeout'
    Assert-True ($script:OpenCount -eq 1) 'Failures never open browser'
} finally {
    $env:DOCKER_HOST = $savedHost
    $env:DOCKER_CONTEXT = $savedContext
    $env:DOCKER_CONFIG = $savedConfig
}
Write-Host 'PASS: portable startup contract tests (no services started).'
