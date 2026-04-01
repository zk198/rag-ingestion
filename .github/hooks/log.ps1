param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("UserPromptSubmitted", "SessionEnd")]
    [string]$Event
)

$ErrorActionPreference = "Stop"

function Read-StdInJson {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return [pscustomobject]@{}
    }
    try {
        return $raw | ConvertFrom-Json -Depth 100
    } catch {
        return [pscustomobject]@{
            _raw = $raw
        }
    }
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Get-GitRepoRoot {
    param([string]$RepoPath)
    try {
        $root = git -C $RepoPath rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $root) {
            return ($root | Select-Object -First 1).Trim()
        }
    } catch {}
    return $RepoPath
}

function Get-GitBranch {
    param([string]$RepoPath)
    try {
        $branch = git -C $RepoPath rev-parse --abbrev-ref HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $branch) {
            return ($branch | Select-Object -First 1).Trim()
        }
    } catch {}
    return $null
}

function Get-GitStatusEntries {
    param([string]$RepoPath)

    $items = @()

    try {
        $lines = git -C $RepoPath status --porcelain=v1 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $lines) {
            return @()
        }

        foreach ($line in $lines) {
            if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
                continue
            }

            $xy = $line.Substring(0, 2)
            $path = $line.Substring(3).Trim()

            if ($path -match " -> ") {
                $path = ($path -split " -> ")[-1].Trim()
            }

            $items += [pscustomobject]@{
                status = $xy
                path   = $path
            }
        }
    } catch {}

    return $items
}

function Get-GitDiffSummary {
    param([string]$RepoPath)

    $result = [ordered]@{
        staged   = $null
        unstaged = $null
    }

    try {
        $staged = git -C $RepoPath diff --cached --shortstat 2>$null
        if ($LASTEXITCODE -eq 0 -and $staged) {
            $result.staged = ($staged -join "`n").Trim()
        }
    } catch {}

    try {
        $unstaged = git -C $RepoPath diff --shortstat 2>$null
        if ($LASTEXITCODE -eq 0 -and $unstaged) {
            $result.unstaged = ($unstaged -join "`n").Trim()
        }
    } catch {}

    return [pscustomobject]$result
}

function Get-WorkspaceRootFromTranscriptPath {
    param([string]$TranscriptPath)

    if ([string]::IsNullOrWhiteSpace($TranscriptPath)) {
        return $null
    }

    if (-not (Test-Path -LiteralPath $TranscriptPath)) {
        return $null
    }

    # Expected observed shape:
    # ...\workspaceStorage\<workspaceId>\GitHub.copilot-chat\transcripts\<sessionId>.jsonl
    try {
        $transcriptsDir = Split-Path -Path $TranscriptPath -Parent
        $copilotDir = Split-Path -Path $transcriptsDir -Parent
        $workspaceRoot = Split-Path -Path $copilotDir -Parent

        if (Test-Path -LiteralPath $workspaceRoot) {
            return $workspaceRoot
        }
    } catch {}

    return $null
}

function Convert-FileUriToLocalPath {
    param([string]$UriString)

    if ([string]::IsNullOrWhiteSpace($UriString)) {
        return $null
    }

    try {
        $uri = [System.Uri]$UriString
        if ($uri.IsFile) {
            return $uri.LocalPath
        }
    } catch {}

    return $UriString
}

function Get-VsCodeWorkspaceEnrichment {
    param(
        [string]$WorkspaceRoot,
        [string]$SessionId
    )

    $result = [ordered]@{
        source               = $null
        workspaceRoot        = $WorkspaceRoot
        statePath            = $null
        transcriptPath       = $null
        modelId              = $null
        agentId              = $null
        modeId               = $null
        requestIds           = @()
        editedFiles          = @()
        notes                = @()
    }

    if ([string]::IsNullOrWhiteSpace($WorkspaceRoot) -or [string]::IsNullOrWhiteSpace($SessionId)) {
        return [pscustomobject]$result
    }

    $statePath = Join-Path $WorkspaceRoot "chatEditingSessions\$SessionId\state.json"
    $transcriptPath = Join-Path $WorkspaceRoot "GitHub.copilot-chat\transcripts\$SessionId.jsonl"

    $result.statePath = $statePath
    if (Test-Path -LiteralPath $transcriptPath) {
        $result.transcriptPath = $transcriptPath
    }

    if (-not (Test-Path -LiteralPath $statePath)) {
        $result.notes += "VS Code workspace storage found, but chatEditingSessions state.json was not present for this session."
        return [pscustomobject]$result
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    } catch {
        $result.notes += "Failed to parse chatEditingSessions state.json."
        return [pscustomobject]$result
    }

    $result.source = "vscode-workspaceStorage"

    $requestIds = New-Object System.Collections.Generic.HashSet[string]
    $edited = New-Object System.Collections.Generic.List[object]

    $entries = @()
    if ($state.recentSnapshot -and $state.recentSnapshot.entries) {
        $entries += $state.recentSnapshot.entries
    }

    foreach ($entry in $entries) {
        $localPath = Convert-FileUriToLocalPath -UriString $entry.resource

        if ($entry.telemetryInfo) {
            if (-not $result.modelId -and $entry.telemetryInfo.modelId) {
                $result.modelId = [string]$entry.telemetryInfo.modelId
            }
            if (-not $result.agentId -and $entry.telemetryInfo.agentId) {
                $result.agentId = [string]$entry.telemetryInfo.agentId
            }
            if (-not $result.modeId -and $entry.telemetryInfo.modeId) {
                $result.modeId = [string]$entry.telemetryInfo.modeId
            }
            if ($entry.telemetryInfo.requestId) {
                [void]$requestIds.Add([string]$entry.telemetryInfo.requestId)
            }
        }

        $edited.Add([pscustomobject]@{
            path         = $localPath
            languageId   = $entry.languageId
            originalHash = $entry.originalHash
            currentHash  = $entry.currentHash
            state        = $entry.state
        })
    }

    $result.requestIds = @($requestIds)
    $result.editedFiles = @($edited)

    return [pscustomobject]$result
}

function Get-CliSessionStoreInfo {
    $home = [Environment]::GetFolderPath("UserProfile")
    $path = Join-Path $home ".copilot\session-state"
    if (Test-Path -LiteralPath $path) {
        return [pscustomobject]@{
            path   = $path
            exists = $true
        }
    }
    return [pscustomobject]@{
        path   = $path
        exists = $false
    }
}

function Merge-HashtableIntoOrdered {
    param(
        [System.Collections.IDictionary]$Target,
        [System.Collections.IDictionary]$Patch
    )

    foreach ($k in $Patch.Keys) {
        $Target[$k] = $Patch[$k]
    }
}

function Load-JsonFileAsHashtable {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $obj = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
        $hash = [ordered]@{}
        foreach ($p in $obj.PSObject.Properties) {
            $hash[$p.Name] = $p.Value
        }
        return $hash
    } catch {
        return $null
    }
}

function Save-JsonFile {
    param(
        [string]$Path,
        [object]$Data
    )

    $Data | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$inputObj = Read-StdInJson

$cwd = $inputObj.cwd
if ([string]::IsNullOrWhiteSpace($cwd)) {
    $cwd = (Get-Location).Path
}

$repoRoot = Get-GitRepoRoot -RepoPath $cwd
$branch = Get-GitBranch -RepoPath $repoRoot
$gitStatus = Get-GitStatusEntries -RepoPath $repoRoot
$diffSummary = Get-GitDiffSummary -RepoPath $repoRoot

$sessionId = $null
if ($inputObj.PSObject.Properties.Name -contains "session_id" -and $inputObj.session_id) {
    $sessionId = [string]$inputObj.session_id
}

$transcriptPath = $null
if ($inputObj.PSObject.Properties.Name -contains "transcript_path" -and $inputObj.transcript_path) {
    $transcriptPath = [string]$inputObj.transcript_path
}

$workspaceRoot = Get-WorkspaceRootFromTranscriptPath -TranscriptPath $transcriptPath
$vscodeInfo = Get-VsCodeWorkspaceEnrichment -WorkspaceRoot $workspaceRoot -SessionId $sessionId
$cliStore = Get-CliSessionStoreInfo

$logDir = Join-Path $repoRoot ".github\hooks\logs"
$sessionDir = Join-Path $logDir "sessions"
Ensure-Directory -Path $logDir
Ensure-Directory -Path $sessionDir

# Per-session file only when session_id is available.
$sessionKey = $sessionId
if ([string]::IsNullOrWhiteSpace($sessionKey)) {
    $sessionKey = "no-session-id"
}
$sessionLogPath = Join-Path $sessionDir "$sessionKey.json"
$auditLogPath = Join-Path $logDir "copilot-audit.jsonl"

$existing = Load-JsonFileAsHashtable -Path $sessionLogPath
if (-not $existing) {
    $existing = [ordered]@{
        schemaVersion = 1
        sessionId     = $sessionId
        firstSeenUtc  = (Get-Date).ToUniversalTime().ToString("o")
        notes         = @()
    }
}

# Keep the key limitation explicit in the log itself.
if (-not $sessionId) {
    $existing.notes += "Hook payload did not include session_id. Per-session correlation is best-effort only."
}
if (-not $transcriptPath) {
    $existing.notes += "Hook payload did not include transcript_path. VS Code workspaceStorage enrichment may be unavailable."
}

$patch = [ordered]@{
    lastUpdatedUtc = (Get-Date).ToUniversalTime().ToString("o")
    repo = [ordered]@{
        cwd      = $cwd
        repoRoot = $repoRoot
        branch   = $branch
    }
    git = [ordered]@{
        changedFiles = $gitStatus
        diffSummary  = $diffSummary
    }
    copilot = [ordered]@{
        sessionId            = $sessionId
        transcriptPath       = $transcriptPath
        vscodeWorkspaceRoot  = $workspaceRoot
        cliSessionStorePath  = $cliStore.path
        cliSessionStoreFound = $cliStore.exists
        modelId              = $vscodeInfo.modelId
        agentId              = $vscodeInfo.agentId
        modeId               = $vscodeInfo.modeId
        requestIds           = $vscodeInfo.requestIds
        enrichmentSource     = $vscodeInfo.source
        statePath            = $vscodeInfo.statePath
    }
    editsFromWorkspace = $vscodeInfo.editedFiles
}

switch ($Event) {
    "UserPromptSubmitted" {
        $patch["userPromptSubmitted"] = [ordered]@{
            timestamp = $inputObj.timestamp
            prompt    = $inputObj.prompt
        }
    }

    "SessionEnd" {
        $patch["sessionEnd"] = [ordered]@{
            timestamp = $inputObj.timestamp
            reason    = $inputObj.reason
        }
    }
}

Merge-HashtableIntoOrdered -Target $existing -Patch $patch

if ($vscodeInfo.notes -and $vscodeInfo.notes.Count -gt 0) {
    $existing.notes += $vscodeInfo.notes
    $existing.notes = @($existing.notes | Select-Object -Unique)
}

Save-JsonFile -Path $sessionLogPath -Data $existing

$auditRecord = [ordered]@{
    timestampUtc = (Get-Date).ToUniversalTime().ToString("o")
    event        = $Event
    sessionId    = $sessionId
    cwd          = $cwd
    repoRoot     = $repoRoot
    branch       = $branch
    prompt       = $inputObj.prompt
    reason       = $inputObj.reason
    modelId      = $vscodeInfo.modelId
    agentId      = $vscodeInfo.agentId
    modeId       = $vscodeInfo.modeId
    editedFiles  = @($vscodeInfo.editedFiles | ForEach-Object { $_.path } | Select-Object -Unique)
    transcript   = $transcriptPath
    workspace    = $workspaceRoot
}

($auditRecord | ConvertTo-Json -Depth 50 -Compress) | Add-Content -LiteralPath $auditLogPath -Encoding UTF8