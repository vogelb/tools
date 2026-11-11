<#
.SYNOPSIS
Adds ignore patterns and untracks matching ignored files without deleting working files.
.DESCRIPTION
Patterns use Git's ignore syntax, relative to the selected .gitignore file. Defaults to
the repository-root .gitignore. Existing entries are skipped. Only files covered by the
requested patterns and effectively ignored by Git are listed and removed from the index.
.PARAMETER Pattern
One or more ignore patterns. Backslashes are converted to forward slashes.
Quote wildcards to prevent shell expansion.
With -Install: one installation folder.
.PARAMETER IgnoreFile
The .gitignore to edit. Must belong to the current repository. Defaults to its root.
.PARAMETER Install
Installs the script, platform launcher and shared installer to the specified folder.
.PARAMETER Help
Prints usage. --help and /? work too.
.EXAMPLE
gitignore "*.log" "build/"
.EXAMPLE
gitignore "*.tmp" -IgnoreFile .\src\.gitignore
.NOTES
This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)
#>
param(
    [Parameter(Position = 0)]
    [string[]]$Pattern,

    [string]$IgnoreFile,

    [switch]$Install,

    [Alias('h')]
    [switch]$Help,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Stop-Gitignore([string]$Message, [int]$Code) {
    [Console]::Error.WriteLine("gitignore: $Message")
    exit $Code
}

$patterns = @($Rest)
if ($PSBoundParameters.ContainsKey('Pattern')) { $patterns = @($Pattern) + $patterns }
if ($Help -or @($patterns | Where-Object { $_ -in '--help', '/?' }).Count -gt 0) {
    @'
gitignore - adds Git ignore patterns and untracks matching ignored files

Usage:
  gitignore pattern... [-IgnoreFile path]
  gitignore -Install [folder]
  gitignore --help

Quote wildcards, for example: gitignore "*.log" "build/"
Backslashes in paths and wildcard patterns are converted to forward slashes.
Patterns are relative to the selected .gitignore, not the current directory.
The default is the repository-root .gitignore; -IgnoreFile selects another one.
Existing entries are skipped. Lists only effectively ignored files covered by the
requested entries. Matching tracked files are removed from the index after a warning;
working files are preserved. Staged content is not forcibly discarded.
The .gitignore edit itself is not automatically staged.

-Install uses the shared installer (default c:\tools on Windows, ~/.local/bin on Linux).
Exit codes: 0 success; 1 Git or file operation failed; 2 invalid arguments.
'@
    return
}

if ($Install) {
    if ($patterns.Count -gt 1 -or $PSBoundParameters.ContainsKey('IgnoreFile')) {
        Stop-Gitignore '-Install takes one folder and cannot be combined with -IgnoreFile.' 2
    }
    $folder = ''
    if ($patterns.Count -eq 1) { $folder = $patterns[0] }
    try {
        . (Join-Path $PSScriptRoot 'git-tools-install.ps1')
        Install-GitTool -Name gitignore -SourceFolder $PSScriptRoot -Target $folder
    }
    catch { Stop-Gitignore $_.Exception.Message 1 }
    return
}

if ($patterns.Count -eq 0) { Stop-Gitignore 'provide at least one ignore pattern; try: gitignore --help' 2 }
foreach ($entry in $patterns) {
    if ([string]::IsNullOrWhiteSpace($entry) -or $entry.IndexOfAny([char[]]@("`0", "`r", "`n")) -ge 0) {
        Stop-Gitignore 'each pattern must be a non-empty, single line without NUL characters.' 2
    }
    if ($entry.StartsWith('-') -or $entry.StartsWith('#') -or $entry.StartsWith('!')) {
        Stop-Gitignore "invalid ignore pattern '$entry'; use / to anchor a literal name starting with -, # or !." 2
    }
}
$patterns = @($patterns | ForEach-Object { $_.Replace('\', '/') })

$windows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
$gitName = 'git'
$pathComparer = [StringComparer]::Ordinal
if ($windows) {
    $gitName = 'git.exe'
    $pathComparer = [StringComparer]::OrdinalIgnoreCase
}
$git = Get-Command $gitName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $git) { Stop-Gitignore 'Git is not available on PATH.' 1 }
$utf8 = New-Object Text.UTF8Encoding($false, $true)

function Invoke-Git([string]$Arguments, [string]$Directory, [string]$InputText = '', [int[]]$Allowed = @(0)) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $git.Source
    $info.Arguments = $Arguments
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    $process = [Diagnostics.Process]::Start($info)
    try {
        $output = $process.StandardOutput.ReadToEndAsync()
        $errorOutput = $process.StandardError.ReadToEndAsync()
        try {
            $inputBytes = $utf8.GetBytes($InputText)
            $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
        }
        finally { $process.StandardInput.Close() }
        $text = $output.Result
        $errorText = $errorOutput.Result
        $process.WaitForExit()
        if ($Allowed -notcontains $process.ExitCode) {
            throw "git $Arguments failed (exit $($process.ExitCode)): $($errorText.Trim())"
        }
        if ($errorText) { [Console]::Error.Write($errorText) }
        return $text
    }
    finally { $process.Dispose() }
}

try {
    $root = [IO.Path]::GetFullPath((Invoke-Git 'rev-parse --show-toplevel' (Get-Location).ProviderPath).TrimEnd("`r", "`n"))
    $file = Join-Path $root '.gitignore'
    if ($PSBoundParameters.ContainsKey('IgnoreFile')) {
        $requested = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($IgnoreFile)
        if ([IO.Path]::GetFileName($requested) -cne '.gitignore') {
            Stop-Gitignore '-IgnoreFile must select a file named .gitignore inside the current repository.' 2
        }
        $parent = [IO.Path]::GetDirectoryName($requested)
        $parentRoot = [IO.Path]::GetFullPath((Invoke-Git 'rev-parse --show-toplevel' $parent).TrimEnd("`r", "`n"))
        if (-not $pathComparer.Equals($root, $parentRoot)) {
            Stop-Gitignore 'the selected .gitignore belongs to a different repository.' 2
        }
        $prefix = (Invoke-Git 'rev-parse --show-prefix' $parent).TrimEnd("`r", "`n")
        $file = Join-Path $root ($prefix + '.gitignore')
    }
    if (Test-Path -LiteralPath $file) {
        $item = Get-Item -LiteralPath $file -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Stop-Gitignore 'the selected .gitignore must be a regular file, not a directory or link.' 2
        }
    }

    $content = ''
    if ([IO.File]::Exists($file)) { $content = [IO.File]::ReadAllText($file, $utf8) }
    $lines = @($content -split '\r?\n')
    $existing = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($line in $lines) { $null = $existing.Add($line) }
    $added = [Collections.Generic.List[string]]::new()
    foreach ($entry in $patterns) {
        if ($existing.Add($entry)) { $added.Add($entry) }
        else { Write-Output "Already present: $entry" }
    }
    if ($added.Count -gt 0) {
        $newline = [Environment]::NewLine
        if ($content.Contains("`n")) {
            $newline = "`n"
            if ($content.Contains("`r`n")) { $newline = "`r`n" }
        }
        $append = ''
        if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) { $append = $newline }
        $append += ($added -join $newline) + $newline
        [IO.File]::AppendAllText($file, $append, $utf8)
        foreach ($entry in $added) { Write-Output "Added: $entry" }
    }

    # A unique per-directory exclude file lets Git match the requested patterns with
    # exactly the same scope as the selected .gitignore, without including unrelated rules.
    $temporaryName = '.gitignore-' + [guid]::NewGuid().ToString('N') + '.tmp'
    $temporaryFile = Join-Path ([IO.Path]::GetDirectoryName($file)) $temporaryName
    try {
        [IO.File]::WriteAllText($temporaryFile, ($patterns -join "`n") + "`n", $utf8)
        $coverage = Invoke-Git "ls-files --cached --others --ignored -z --exclude-per-directory=$temporaryName" $root
    }
    finally {
        if ([IO.File]::Exists($temporaryFile)) { [IO.File]::Delete($temporaryFile) }
    }
    $candidates = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $rootPrefix = $root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $temporaryRelative = $temporaryFile.Substring($rootPrefix.Length).Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
    foreach ($path in $coverage.Split([char]0)) {
        if ($path -and $path -cne $temporaryRelative) { $null = $candidates.Add($path) }
    }
    $ignored = @()
    if ($candidates.Count -gt 0) {
        $inputText = ($candidates -join [char]0) + [char]0
        $effective = Invoke-Git 'check-ignore --no-index --stdin -z' $root $inputText @(0, 1)
        $ignored = @($effective.Split([char]0) | Where-Object { $_ } | Sort-Object)
    }
    if ($ignored.Count -eq 0) {
        Write-Output 'No effectively ignored files match the requested entries.'
        exit 0
    }

    $tracked = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($path in (Invoke-Git 'ls-files --cached -z' $root).Split([char]0)) {
        if ($path) { $null = $tracked.Add($path) }
    }
    $toUntrack = @($ignored | Where-Object { $tracked.Contains($_) })
    if ($toUntrack.Count -gt 0) {
        Write-Warning 'Matching tracked files will be removed from the Git index (staged deletions). Working files are preserved.'
        $inputText = ($toUntrack -join [char]0) + [char]0
        $null = Invoke-Git '--literal-pathspecs rm --cached --quiet --pathspec-from-file=- --pathspec-file-nul' $root $inputText
        foreach ($path in $toUntrack) { Write-Output "Removed from index: $path" }
    }
    Write-Output 'Effectively ignored files (relative to repository root):'
    foreach ($path in $ignored) { Write-Output "  $path" }
}
catch { Stop-Gitignore $_.Exception.Message 1 }
