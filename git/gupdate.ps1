<#
.SYNOPSIS
Updates selected Git repositories using fast-forward-only pulls.
.DESCRIPTION
Runs git pull --ff-only in supplied repositories or immediate child repositories of supplied folders.
With no paths, updates
each immediate child directory with a .git file or directory in the current working directory.
Continues after failures. Does not recurse, switch branches, stash changes or create merges.
Runs in Windows PowerShell 5.1 and PowerShell 7. Shell wrappers support cmd.exe and Linux.
.PARAMETER Force
Runs git reset --hard HEAD before each pull, discarding tracked local changes after a warning.
Local commits are kept. Untracked paths obstructing tracked files may be removed. --force works too.
.PARAMETER Path
Repository paths or folders containing repositories, relative to the current directory or absolute.
With -Install: one installation folder, default c:\tools on Windows or ~/.local/bin on Linux.
.PARAMETER Install
Copies the script, platform launcher and shared installer to a configurable folder and
adds it to the user PATH, without administrator rights. Updates the session PATH too.
.PARAMETER Help
Prints usage. --help and /? work too.
.EXAMPLE
gupdate
.EXAMPLE
gupdate repo-one "repo with spaces"
.EXAMPLE
gupdate -Install D:\bin
.NOTES
This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)
#>
param(
    [Parameter(Position = 0)]
    [string[]]$Path,

    [switch]$Install,

    [switch]$Force,

    [Alias('h')]
    [switch]$Help,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Stop-Gupdate([string]$Message, [int]$Code) {
    [Console]::Error.WriteLine("gupdate: $Message")
    exit $Code
}

if ($Help -or @(@($Path) + @($Rest) | Where-Object { $_ -in '--help', '/?' }).Count -gt 0) {
    @'
gupdate - updates Git repositories with fast-forward-only pulls

Usage:
  gupdate [path...] [--force]
  gupdate -Install [folder]
  gupdate --help

Paths may be relative or absolute. A repository is updated directly; any other
folder updates its immediate child repositories. With no paths, updates all immediate
child repositories in the current working directory. Does not recurse.
Explicit paths must be directories; all are validated before updating.
Requires Git on PATH. Continues after failed pulls.
--force (or -Force) warns, then runs git reset --hard HEAD before each pull.
This discards tracked local changes and may remove untracked paths obstructing
tracked files. Other untracked files and local commits are kept.
-Install copies the script, platform launcher and shared installer to a configurable
folder (default c:\tools on Windows, ~/.local/bin on Linux), and adds it to the user PATH.

Exit codes: 0 success (also no repositories found); 1 Git missing, reset or pull failed;
2 invalid arguments, directory access or installation failure.
'@
    return
}

$arguments = @($Rest)
if ($PSBoundParameters.ContainsKey('Path')) { $arguments = @($Path) + $arguments }
if ($arguments -contains '--force') { $Force = $true }
$arguments = @($arguments | Where-Object { $_ -ne '--force' })
if (($Install -and ($Force -or $arguments.Count -gt 1)) -or
    @($arguments | Where-Object { $_.StartsWith('-') }).Count -gt 0) {
    Stop-Gupdate 'unexpected argument; try: gupdate --help' 2
}

if ($Install) {
    $folder = ''
    if ($arguments.Count -eq 1) { $folder = $arguments[0] }
    try {
        . (Join-Path $PSScriptRoot 'git-tools-install.ps1')
        Install-GitTool -Name gupdate -SourceFolder $PSScriptRoot -Target $folder
    }
    catch { Stop-Gupdate $_.Exception.Message 2 }
    return
}

$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $git) { Stop-Gupdate 'Git is not available on PATH.' 1 }

# Native stderr is normal Git progress, not a terminating PowerShell error in Windows PowerShell.
$ErrorActionPreference = 'Continue'
$failed = $false
$found = $false
try {
    if ($arguments.Count -eq 0) {
        $directories = @(Get-ChildItem -LiteralPath . -Directory -ErrorAction Stop)
    }
    else {
        $directories = @(foreach ($repository in $arguments) {
            $item = Get-Item -LiteralPath $repository -ErrorAction Stop
            if ($item.PSProvider.Name -ne 'FileSystem' -or -not $item.PSIsContainer) {
                throw "'$repository' is not a directory."
            }
            if (Test-Path -LiteralPath (Join-Path $item.FullName '.git') -ErrorAction Stop) {
                $item
            }
            else {
                Get-ChildItem -LiteralPath $item.FullName -Directory -ErrorAction Stop
            }
        })
    }
    if ($Force) {
        Write-Warning 'Force update: git reset --hard HEAD will discard all staged and unstaged tracked changes in selected repositories and may remove untracked paths obstructing tracked files. Local commits are kept.'
    }
    $comparer = [StringComparer]::Ordinal
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $comparer = [StringComparer]::OrdinalIgnoreCase
    }
    $seen = [Collections.Generic.HashSet[string]]::new($comparer)
    foreach ($directory in $directories) {
        if (-not $seen.Add($directory.FullName)) { continue }
        if (Test-Path -LiteralPath (Join-Path $directory.FullName '.git') -ErrorAction Stop) {
            $found = $true
            Write-Output ''
            Write-Output "Updating `"$($directory.Name)`"..."
            if ($Force) {
                & $git.Source -C $directory.FullName reset --hard HEAD
                if ($LASTEXITCODE -ne 0) {
                    [Console]::Error.WriteLine("gupdate: Reset failed for `"$($directory.Name)`"; skipping pull.")
                    $failed = $true
                    continue
                }
            }
            & $git.Source -C $directory.FullName pull --ff-only
            if ($LASTEXITCODE -ne 0) {
                [Console]::Error.WriteLine("gupdate: Pull failed for `"$($directory.Name)`".")
                $failed = $true
            }
        }
    }
}
catch { Stop-Gupdate $_.Exception.Message 2 }

if (-not $found) { Write-Output 'No Git repositories found in the selected folders.' }
if ($failed) { exit 1 }
exit 0
