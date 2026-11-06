<#
.SYNOPSIS
Shared installer for the Git PowerShell tools.
.NOTES
This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)
#>

function Get-UserPath {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    try { return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    finally { $key.Dispose() }
}

function Set-UserPath([string]$Value) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
        $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        if ($key.GetValueNames() -contains 'Path') { $kind = $key.GetValueKind('Path') }
        $key.SetValue('Path', $Value, $kind)
    }
    finally { $key.Dispose() }
}

function Get-MachinePath {
    [string][Environment]::GetEnvironmentVariable('Path', 'Machine')
}

function Send-EnvironmentChange {
    if (-not ('GitTools.Native' -as [type])) {
        Add-Type -Namespace GitTools -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint flags, uint timeout, out UIntPtr result);
'@
    }
    $result = [UIntPtr]::Zero
    $null = [GitTools.Native]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
}

function ConvertTo-PathKey([string]$Entry) {
    [Environment]::ExpandEnvironmentVariables($Entry.Trim().Trim('"')).Replace('/', '\').TrimEnd('\')
}

function Test-OnPath([string]$PathValue, [string]$Folder) {
    $wanted = ConvertTo-PathKey $Folder
    foreach ($entry in $PathValue.Split(';')) {
        if ($entry.Trim() -and (ConvertTo-PathKey $entry) -eq $wanted) { return $true }
    }
    return $false
}

function Install-GitTool([string]$Name, [string]$SourceFolder, [string]$Target) {
    $windows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
    if (-not $Target) {
        if ($windows) { $Target = 'c:\tools' }
        else {
            if (-not $env:HOME) { throw 'HOME must be set to choose the default install folder' }
            $Target = Join-Path $env:HOME '.local/bin'
        }
    }
    if (-not $Target) { throw 'the install folder is empty' }
    if ($Target.Contains([IO.Path]::PathSeparator)) { throw "the install folder must not contain '$([IO.Path]::PathSeparator)', it separates the PATH entries" }
    if ($windows -and $Target.Contains('%')) { throw "the install folder must not contain '%'; PowerShell does not expand %VARIABLES%, use `$env:NAME" }
    $launcher = $Name
    if ($windows) { $launcher = "$Name.cmd" }
    $files = @("$Name.ps1", $launcher, 'git-tools-install.ps1')
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $SourceFolder $file) -PathType Leaf)) {
            throw "cannot install: $file is missing next to the running script"
        }
    }
    $folder = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Target)
    if (-not [System.IO.Path]::IsPathRooted($folder)) { throw "'$Target' is not a file system folder" }
    $root = [IO.Path]::GetPathRoot($folder)
    if ($folder.Length -gt $root.Length) { $folder = $folder.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) }
    if (Test-Path -LiteralPath $folder -PathType Leaf) { throw "'$folder' is a file, not a folder" }

    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $folder
        "created folder: $folder"
    }
    foreach ($file in $files) {
        $from = Join-Path $SourceFolder $file
        $to = Join-Path $folder $file
        if (Test-Path -LiteralPath $to -PathType Container) { throw "'$to' is a folder, not a file" }
        if ((Test-Path -LiteralPath $to -PathType Leaf) -and
            (Get-FileHash -LiteralPath $from).Hash -eq (Get-FileHash -LiteralPath $to).Hash) {
            "up to date: $to"
        }
        else {
            Copy-Item -LiteralPath $from -Destination $to -Force
            "copied: $to"
        }
    }

    if (-not $windows) {
        $chmod = Get-Command chmod -CommandType Application -ErrorAction Stop | Select-Object -First 1
        & $chmod.Source '+x' (Join-Path $folder $Name)
        if ($LASTEXITCODE -ne 0) { throw 'could not make the launcher executable' }
        if (@($env:PATH.Split(':') | Where-Object { $_.TrimEnd('/') -ceq $folder }).Count -gt 0) {
            "already on the PATH: $folder"
        }
        else {
            if (-not $env:HOME) { throw 'HOME must be set to update the shell PATH' }
            $bashrc = Join-Path $env:HOME '.bashrc'
            $line = 'export PATH="$PATH":' + "'" + $folder.Replace("'", "'\''") + "'"
            $lines = @()
            if (Test-Path -LiteralPath $bashrc) { $lines = @(Get-Content -LiteralPath $bashrc) }
            if ($lines -ccontains $line) { "already in ${bashrc}: $folder" }
            else {
                Add-Content -LiteralPath $bashrc -Value "`n# added by $Name --install`n$line" -Encoding utf8
                "added to ${bashrc}: $line"
            }
            $env:PATH = $env:PATH.TrimEnd(':') + ':' + $folder
        }
        "Done. New bash shells can run: $Name --help"
        return
    }

    $userPath = Get-UserPath
    if ((Test-OnPath $userPath $folder) -or (Test-OnPath (Get-MachinePath) $folder)) {
        "already on the PATH: $folder"
    }
    else {
        $newPath = $folder
        if ($userPath.Trim()) { $newPath = $userPath.TrimEnd(';') + ';' + $folder }
        Set-UserPath $newPath
        Send-EnvironmentChange
        "added to the user PATH: $folder"
    }
    if (-not (Test-OnPath $env:Path $folder)) { $env:Path = $env:Path.TrimEnd(';') + ';' + $folder }
    "Done. Terminals opened from now on can run: $Name --help"
}
