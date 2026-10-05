<#
.SYNOPSIS
Lists a directory like DIR, with every entry colored by its git state.

.DESCRIPTION
Shows the entries of a directory (default: the current one) with date, size and name, like
DIR, and colors each entry by its state in git: current, changed, staged, unmanaged
(untracked), deleted, conflict or ignored. A deleted file no longer exists on disk, so it is
listed from git. A directory takes the most severe state of its contents.
Run "gdir --help" for the usage page and "gdir -Legend" for the color key.
The colors are set in the configuration block at the top of the script.

Outside a git work tree the listing is plain. Needs git on the PATH. Runs in Windows
PowerShell 5.1 and PowerShell 7; gdir.cmd starts it from cmd.exe.
gdir -Install copies gdir to a folder (default c:\tools) and puts that folder on the PATH.

.PARAMETER Path
Files and directories to show, separated by spaces or commas. Default: the current directory.
A directory is listed; a file shows just its own entry, even when it is hidden, and so does a
file that git has deleted, even if its directory is gone as well. With several paths, every
directory and the files of every directory come below a localized directory-header line. A path must
exist, otherwise the exit code is 2 (the other paths are still shown); quote it if it
contains spaces. Wildcards are not expanded.
With -Install: the folder to install into, default c:\tools.

.PARAMETER Wide
Short form -w. Names only, in columns like DIR /W; directories are shown in [brackets].
One name per line when the output is not a terminal.

.PARAMETER All
Short form -a. Also list entries with the Hidden or System attribute (such as .git).

.PARAMETER Recurse
Short form -r. Also lists the subdirectories, each below a localized directory-header line, like DIR /S.
A subdirectory that is its own git repository (submodule, nested clone) is colored by that
repository. The .git directory and directory links are listed but not entered. Subdirectories
that cannot be read are reported on stderr.

.PARAMETER Color
auto (default) colors only on a terminal and only if the NO_COLOR environment variable is
not set; always colors even when the output is redirected; never prints plain text.

.PARAMETER Legend
Prints the color key and exits.

.PARAMETER Install
Copies gdir.ps1 and gdir.cmd to a folder (the Path argument, default c:\tools; created if
needed) and adds the folder to the PATH of the current user, unless it is already part of the
PATH (user or machine). The user PATH is edited in the registry, so entries with %VARIABLES%
keep working. The PATH of this session is updated too; programs that are already running keep
their old PATH, new terminals see the new one. Files that are already up to date are left
alone, so running -Install again updates an installation. Needs no administrator rights.

.PARAMETER Help
Short form -h. Prints the usage page and exits. "--help" and "/?" do the same.

.PARAMETER Rest
Not an option. Collects what no parameter took: further paths after the first one, and "--help"
and "/?", which are recognized anywhere. An argument that starts with "-" is reported as
unknown (exit code 2).

.EXAMPLE
gdir

.EXAMPLE
gdir -Wide ..\other-repo

.EXAMPLE
gdir -Recurse

.EXAMPLE
gdir -Install D:\bin

.EXAMPLE
gdir current.txt ..\other\changed.txt sub

.NOTES
This file was created with the help of AI — model: Claude Sonnet 5.5 (model ID: claude-sonnet-5.5)
#>
param(
    [Parameter(Position = 0)]
    [string[]]$Path = @('.'),

    [Alias('w')]
    [switch]$Wide,

    [Alias('a')]
    [switch]$All,

    [Alias('r')]
    [switch]$Recurse,

    [ValidateSet('auto', 'always', 'never')]
    [string]$Color = 'auto',

    [switch]$Legend,

    [switch]$Install,

    [Alias('h')]
    [switch]$Help,

    # Not an option: what no parameter took (further paths, --help and /?, mistakes) ends up here.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# =============================================================================================
# Configuration: colors of the git states
# =============================================================================================
# Named colors: ANSI escape codes (SGR, Select Graphic Rendition) for the text color. The
# terminal theme decides the exact shade. Add more the same way, for example $Cyan = '36'.
$Blue       = '34'
$Red        = '31'
$Yellow     = '33'
$Green      = '32'
$LightBlue  = '94'
$LightRed   = '91'
$LightGreen = '92'
$Gray       = '90'
$LightGray  = '37'
$White      = '97'
$Purple     = '35'

# The color of every state: change the named color on the right. A state can also take
#   @{ Color = $Red; Strike = $true; Bold = $true; Background = $White }
# where Strike (strikethrough), Bold and Background (a named color) are optional.
$StateColors = @{
    current   = $Green
    changed   = $Yellow
    staged    = $LightBlue
    unmanaged = $White
    deleted   = @{ Color = $Red; Strike = $true }
    conflict  = @{ Color = $White; Bold = $true; Background = $Red }
    ignored   = $Gray
}
# =============================================================================================

# Git state of an entry. The number is its severity: a directory takes the most severe state
# found below it. Never test a state for truthiness, IGNORED is 0.
$IGNORED = 0; $CURRENT = 1; $UNMANAGED = 2; $STAGED = 3; $CHANGED = 4; $DELETED = 5; $CONFLICT = 6
# Indexed by state: legend label, tag column, meaning. The Color entry (the SGR parameters of
# the state's color) is added below from the configuration block.
$Style = @(
    @{ Label = 'ignored';   Tag = '!'; Text = 'matches .gitignore' }
    @{ Label = 'current';   Tag = '✓'; Text = 'tracked, unchanged' }
    @{ Label = 'unmanaged'; Tag = '?'; Text = 'untracked: git does not manage it' }
    @{ Label = 'staged';    Tag = '+'; Text = 'changes staged in the index, nothing newer in the working tree' }
    @{ Label = 'changed';   Tag = 'M'; Text = 'modified in the working tree' }
    @{ Label = 'deleted';   Tag = 'D'; Text = 'tracked but gone from the working tree (listed from git)' }
    @{ Label = 'conflict';  Tag = 'U'; Text = 'unmerged paths' }
)

$useColor = switch ($Color) {
    'always' { $true }
    'never'  { $false }
    default  { -not $env:NO_COLOR -and -not [Console]::IsOutputRedirected -and $Host.UI.SupportsVirtualTerminal }
}
$esc = [char]27

function Stop-Gdir([string]$Message, [int]$Code) {
    [Console]::Error.WriteLine("gdir: $Message")
    exit $Code
}

# Turns the settings of one state (a named color, or a hashtable as described in the
# configuration block) into the SGR parameters of its escape sequence.
function ConvertTo-Ansi([string]$StateName, $Spec) {
    if ($Spec -is [string]) { $Spec = @{ Color = $Spec } }
    foreach ($key in 'Color', 'Background') {
        if ($Spec[$key] -and $Spec[$key] -notmatch '^\d+$') {
            Stop-Gdir "the configuration block has an invalid $key for the state '$StateName'; use a named color such as `$Green" 2
        }
    }
    if (-not $Spec['Color']) { Stop-Gdir "the configuration block has no Color for the state '$StateName'" 2 }
    $codes = @()
    if ($Spec['Bold']) { $codes += '1' }
    $codes += [string]$Spec['Color']
    if ($Spec['Strike']) { $codes += '9' }
    if ($Spec['Background']) { $codes += [string]([int]$Spec['Background'] + 10) }
    return $codes -join ';'
}

function Show-Usage {
    $usage = @'
gdir - lists a directory like DIR, with every entry colored by its git state

Usage:
  gdir [path...] [-Recurse] [-Wide] [-All] [-Color when] [-Legend]
  gdir -Install [folder]
  gdir --help

Arguments:
  path...       Files and directories to show. Default: the current directory.
                A directory is listed, a file shows just its own entry (also a
                hidden file, and a file that git has deleted, even when its
                directory is gone too). With several paths, each directory and
                the files of each directory come below a localized directory-header line.
                A path must exist, otherwise the exit code is 2; the other
                paths are still shown. Quote paths that contain spaces.
                Wildcards are not expanded.
  -Recurse, -r  Also list the subdirectories, each below a localized directory-header line,
                like DIR /S. A subdirectory that is its own git repository is
                colored by that repository. Listed but not entered: .git and
                directory links. Unreadable subdirectories are reported on
                stderr.
  -Wide, -w     Names only, in columns like DIR /W; directories in [brackets].
                One name per line when the output is not a terminal.
  -All, -a      Also list entries with the Hidden or System attribute, such as
                .git. Without it they are left out, like DIR does.
  -Color when   auto (default): color only on a terminal and only if the
                NO_COLOR environment variable is not set.
                always: color even when the output is redirected.
                never: plain text.
  -Legend       Print the color key and exit.
  -Install      Copy gdir.ps1 and gdir.cmd to a folder and add the folder to
                the user PATH, unless it is already on the PATH. The folder is
                the path argument, default c:\tools; it is created if needed.
                Needs no administrator rights. Terminals opened afterwards can
                run gdir; running ones keep their old PATH.
  --help        Print this page and exit. Also: -Help, -h, /?

Options are PowerShell parameters: not case-sensitive, and unambiguous
abbreviations work (-Col never). DIR switches such as /W are not supported.

The colors of the git states are set in the configuration block at the top of
gdir.ps1; gdir -Legend shows the ones in use.

Examples:
  gdir                      list the current directory
  gdir -Wide ..\other       names only, another directory
  gdir -r                   the whole tree below the current directory
  gdir -All -Color never    include .git, no color codes
  gdir -Install             copy gdir to c:\tools and put it on the PATH
  gdir -Install D:\bin      the same for another folder
  gdir a.txt ..\b\c.txt     show just these files, with their git state
  gdir -r src a.txt         a directory with its subdirectories, and a file

Exit codes: 0 listing printed (a plain one, with a note on stderr, outside a
git work tree); 2 a path cannot be shown (does not exist, or cannot be read),
or an argument is unknown; 1 invalid -Color value (reported by PowerShell).
'@
    $usage -split '\r?\n'
}

$helpWords = '--help', '/?'
if ($Help -or @(@($Path) + @($Rest) | Where-Object { $helpWords -contains $_ }).Count -gt 0) {
    Show-Usage
    return
}
$unknown = @($Rest | Where-Object { $_.StartsWith('-') })
if ($unknown.Count -gt 0) { Stop-Gdir "unknown argument '$($unknown[0])'; try: gdir --help" 2 }

# --- install ---------------------------------------------------------------------------------

# The user PATH as stored, with %VARIABLES% not expanded, so that writing it back keeps them.
function Get-UserPath {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    try { return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    finally { $key.Dispose() }
}

# Written back with the kind it has (an expandable string, which is what Windows uses for PATH,
# when there is no value yet), so that appending a folder changes nothing else.
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

# Tells the running programs (Explorer, and with it every terminal opened from now on) that the
# environment changed: WM_SETTINGCHANGE to all top-level windows.
function Send-EnvironmentChange {
    if (-not ('Gdir.Native' -as [type])) {
        Add-Type -Namespace Gdir -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint flags, uint timeout, out UIntPtr result);
'@
    }
    $result = [UIntPtr]::Zero
    $null = [Gdir.Native]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
}

# A PATH entry as it is compared: %VARIABLES% expanded, quotes removed, '/' written as '\',
# trailing separators removed.
function ConvertTo-PathKey([string]$Entry) {
    [Environment]::ExpandEnvironmentVariables($Entry.Trim().Trim('"')).Replace('/', '\').TrimEnd('\')
}

function Test-OnPath([string]$PathValue, [string]$Folder) {
    $wanted = ConvertTo-PathKey $Folder
    foreach ($entry in $PathValue.Split(';')) {
        if ($entry.Trim() -and (ConvertTo-PathKey $entry) -eq $wanted) { return $true }    # -eq ignores case
    }
    return $false
}

# Copies gdir.ps1 and gdir.cmd to $Target, which is created if needed, and adds that folder to
# the user PATH unless it is already part of the PATH.
function Install-Gdir([string]$Target) {
    if (-not $Target) { Stop-Gdir 'the install folder is empty' 2 }
    if ($Target.Contains(';')) { Stop-Gdir "the install folder must not contain ';', it separates the PATH entries" 2 }
    if ($Target.Contains('%')) { Stop-Gdir "the install folder must not contain '%'; PowerShell does not expand %VARIABLES%, use `$env:NAME" 2 }
    $sources = @(
        @{ From = $PSCommandPath; Name = 'gdir.ps1' }
        @{ From = Join-Path $PSScriptRoot 'gdir.cmd'; Name = 'gdir.cmd' }
    )
    foreach ($source in $sources) {
        if (-not (Test-Path -LiteralPath $source.From -PathType Leaf)) { Stop-Gdir "cannot install: $($source.Name) is missing next to the running script" 2 }
    }
    $folder = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Target)
    if (-not [System.IO.Path]::IsPathRooted($folder)) { Stop-Gdir "'$Target' is not a file system folder" 2 }
    if ($folder.Length -gt 3) { $folder = $folder.TrimEnd('\', '/') }
    if (Test-Path -LiteralPath $folder -PathType Leaf) { Stop-Gdir "'$folder' is a file, not a folder" 2 }

    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $folder
        "created folder: $folder"
    }
    foreach ($source in $sources) {
        $to = Join-Path $folder $source.Name
        if ((Test-Path -LiteralPath $to -PathType Leaf) -and
            (Get-FileHash -LiteralPath $source.From).Hash -eq (Get-FileHash -LiteralPath $to).Hash) {
            "up to date: $to"
        }
        else {
            Copy-Item -LiteralPath $source.From -Destination $to -Force
            "copied: $to"
        }
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
    'Done. Terminals opened from now on can run: gdir --help'
}

# --- run the installer ---
if ($Install) {
    $given = @($Rest)
    if ($PSBoundParameters.ContainsKey('Path')) { $given = @($Path) + $given }
    if ($given.Count -gt 1) { Stop-Gdir "-Install takes one folder, not $($given.Count)" 2 }
    $installFolder = 'c:\tools'
    if ($given.Count -eq 1) { $installFolder = $given[0] }
    Install-Gdir $installFolder
    return
}

# The configuration block gives the color of every state.
foreach ($s in $IGNORED..$CONFLICT) {
    $label = $Style[$s].Label
    if (-not $StateColors.Contains($label)) { Stop-Gdir "the configuration block has no color for the state '$label'" 2 }
    $Style[$s].Color = ConvertTo-Ansi $label $StateColors[$label]
}

# The escape sequences that start and end the colored text of each state; index $NOSTATE is for
# entries without git information. Empty without color.
$NOSTATE = 7
$paintOn = @('') * 8
$paintOff = @('') * 8
if ($useColor) {
    foreach ($s in $IGNORED..$CONFLICT) {
        $paintOn[$s] = $esc + '[' + $Style[$s].Color + 'm'
        $paintOff[$s] = $esc + '[0m'
    }
}

if ($Legend) {
    foreach ($s in $CURRENT, $CHANGED, $STAGED, $UNMANAGED, $DELETED, $CONFLICT, $IGNORED) {
        '{0} {1}{2}{3} {4}' -f $Style[$s].Tag, $paintOn[$s], $Style[$s].Label.PadRight(9), $paintOff[$s], $Style[$s].Text
    }
    ''
    'The first column is the tag shown by the default listing.'
    'A directory shows the most severe state inside it: conflict > changed > staged > unmanaged > current > ignored.'
    'A deleted file inside a directory makes the directory changed.'
    return
}

# --- git -------------------------------------------------------------------------------------

# Starts git without waiting, so that the three queries run at the same time. The real git.exe
# is used on purpose: a git.bat wrapper on the PATH may swallow git's exit code.
function Start-Git([string]$WorkDir, [string]$GitArgs) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.Arguments = $GitArgs
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    try { $proc = [System.Diagnostics.Process]::Start($psi) }
    catch { throw 'git not found on PATH' }
    [pscustomobject]@{
        Proc = $proc
        Out  = $proc.StandardOutput.ReadToEndAsync()
        Err  = $proc.StandardError.ReadToEndAsync()
    }
}

function Receive-Git($Job) {
    $out = $Job.Out.Result
    $err = $Job.Err.Result.Trim()
    $Job.Proc.WaitForExit()
    if ($Job.Proc.ExitCode -ne 0) {
        if ($err) { throw ($err -split '\r?\n')[0] }
        throw "git exited with status $($Job.Proc.ExitCode)"
    }
    return $out
}

# Maps the XY pair of "git status --porcelain=v1" to a state.
function Get-StateOf([char]$X, [char]$Y) {
    if ($X -ceq '?') { return $UNMANAGED }
    if ($X -ceq '!') { return $IGNORED }
    if ($X -ceq 'U' -or $Y -ceq 'U' -or ($X -ceq 'A' -and $Y -ceq 'A') -or ($X -ceq 'D' -and $Y -ceq 'D')) { return $CONFLICT }
    if ($X -ceq 'D' -or $Y -ceq 'D') { return $DELETED }
    if ($Y -cne ' ') { return $CHANGED }
    return $STAGED
}

# What git knows about the entries below $Dir. Paths are relative to $Dir, separated by '/',
# and compared case-insensitively. Without $Deep only the names directly in $Dir are keys.
#   Mask       path -> bit mask (1 -shl state) of the states reported at or below it
#   Tracked    paths in the index, and directories that contain such paths
#   Collapsed  directory -> state, for untracked or ignored directories that git reports whole
#   Ghosts     directory -> (name -> isDir) of the deleted entries directly below it
#   Base       state of $Dir itself when it lies inside an untracked or ignored directory, else -1
# Returns $null, after saying why on stderr (once for every distinct message), when there is no
# git information.
$script:notes = [System.Collections.Generic.HashSet[string]]::new()
function Read-GitState([string]$Dir, [bool]$Deep) {
    try {
        $jobs = @(
            Start-Git $Dir 'rev-parse --show-prefix'
            # --no-renames: every path gets its own state, no ORIG_PATH fields to parse
            Start-Git $Dir '--no-optional-locks status --porcelain=v1 -z --no-renames --ignored=matching --untracked-files=normal -- .'
            Start-Git $Dir 'ls-files -z -- .'
        )
        $prefixRaw = Receive-Git $jobs[0]
        $statusRaw = Receive-Git $jobs[1]
        $filesRaw = Receive-Git $jobs[2]
    }
    catch {
        $note = "gdir: $($_.Exception.Message); showing a plain listing"
        if ($script:notes.Add($note)) { [Console]::Error.WriteLine($note) }
        return $null
    }

    # '' at the repository root, else 'sub/dir/'. Status paths are relative to the root.
    $prefix = $prefixRaw.TrimEnd("`r", "`n")
    $cmp = [System.StringComparer]::OrdinalIgnoreCase

    # After "git rm --cached" a path is reported twice (D and ??); the later record wins.
    $paths = [System.Collections.Generic.Dictionary[string, int]]::new($cmp)
    $collapsed = [System.Collections.Generic.Dictionary[string, int]]::new($cmp)
    $base = -1
    foreach ($rec in $statusRaw.Split([char]0)) {
        if ($rec.Length -lt 4) { continue }   # "XY path"; skips the empty tail
        $state = Get-StateOf $rec[0] $rec[1]
        $p = $rec.Substring(3)
        $isDirRecord = $p.EndsWith('/', [StringComparison]::Ordinal)
        if ($isDirRecord -and $prefix.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) {
            $base = $state    # an untracked or ignored directory that contains $Dir
        }
        elseif ($p.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            $rel = $p.Substring($prefix.Length).TrimEnd('/')
            $paths[$rel] = $state
            if ($isDirRecord) { $collapsed[$rel] = $state }
        }
    }

    # Every status path adds its state to itself and to each directory above it.
    $mask = [System.Collections.Generic.Dictionary[string, int]]::new($cmp)
    $ghosts = [System.Collections.Generic.Dictionary[string, object]]::new($cmp)
    foreach ($kv in $paths.GetEnumerator()) {
        $rel = $kv.Key
        $state = $kv.Value
        $start = 0
        while ($true) {
            $slash = $rel.IndexOf([char]'/', $start)
            $end = if ($slash -lt 0) { $rel.Length } else { $slash }
            $key = $rel.Substring(0, $end)            # one more component of the path
            $old = 0
            $null = $mask.TryGetValue($key, [ref]$old)
            $mask[$key] = $old -bor (1 -shl $state)
            if ($state -eq $DELETED) {
                $parent = if ($start -eq 0) { '' } else { $rel.Substring(0, $start - 1) }
                $kids = $null
                if (-not $ghosts.TryGetValue($parent, [ref]$kids)) {
                    $kids = [System.Collections.Generic.Dictionary[string, bool]]::new($cmp)
                    $ghosts[$parent] = $kids
                }
                $name = $rel.Substring($start, $end - $start)
                $isDir = $slash -ge 0
                if ($kids.ContainsKey($name)) { $isDir = $isDir -or $kids[$name] }
                $kids[$name] = $isDir
            }
            if ($slash -lt 0 -or -not $Deep) { break }
            $start = $slash + 1
        }
    }

    $tracked = [System.Collections.Generic.HashSet[string]]::new($cmp)
    $last = ''
    foreach ($f in $filesRaw.Split([char]0)) {
        if ($f.Length -eq 0) { continue }
        if ($Deep) {
            $null = $tracked.Add($f)
            $dirEnd = $f.LastIndexOf([char]'/')
            if ($dirEnd -lt 0) { continue }
            $d = $f.Substring(0, $dirEnd)
            if ($d -ceq $last) { continue }           # ls-files is sorted: same directory as before
            $last = $d
            $start = 0
            while ($true) {                           # the directory and every directory above it
                $slash = $d.IndexOf([char]'/', $start)
                $null = $tracked.Add($(if ($slash -lt 0) { $d } else { $d.Substring(0, $slash) }))
                if ($slash -lt 0) { break }
                $start = $slash + 1
            }
        }
        else {
            $slash = $f.IndexOf([char]'/')
            $top = if ($slash -ge 0) { $f.Substring(0, $slash) } else { $f }
            if ($top -ceq $last) { continue }         # one visit per top-level name
            $last = $top
            $null = $tracked.Add($top)
        }
    }
    return @{ Mask = $mask; Tracked = $tracked; Collapsed = $collapsed; Ghosts = $ghosts; Base = $base }
}

# --- listing ---------------------------------------------------------------------------------

# The code below runs once per entry. Function calls and New-Object are slow in Windows
# PowerShell 5.1, so the per-entry work is written inline and objects are made with ::new().
$hiddenOrSystem = [System.IO.FileAttributes]::Hidden -bor [System.IO.FileAttributes]::System
$directoryAttribute = [System.IO.FileAttributes]::Directory
$linkAttribute = [System.IO.FileAttributes]::ReparsePoint
$currentBit = 1 -shl $CURRENT
$changedBit = 1 -shl $CHANGED
$deletedBit = 1 -shl $DELETED
$controlCharacters = [char[]]((0..31) + (127..159))

# The entries of one directory, sorted like DIR (case-insensitive, ordinal): what is on disk
# plus the files git has deleted there. $Rel is the path of the directory below the root that
# $Git describes, $Inherited the state of the untracked or ignored directory that contains it
# (-1: none). Without $Git (no git information) the entries have no state. With $Only (a set of
# names) just those entries, whatever their attributes.
function Get-Entries([string]$Dir, [string]$Rel, [int]$Inherited, $Git, $Only = $null) {
    $names = [System.Collections.Generic.List[string]]::new()
    $recs = [System.Collections.Generic.List[object]]::new()
    $onDisk = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($fsi in ([System.IO.DirectoryInfo]$Dir).EnumerateFileSystemInfos()) {
        $name = $fsi.Name
        $null = $onDisk.Add($name)
        $attributes = $fsi.Attributes
        if ($null -ne $Only) { if (-not $Only.Contains($name)) { continue } }
        elseif (-not $All -and ($attributes -band $hiddenOrSystem) -ne 0) { continue }
        $isDir = ($attributes -band $directoryAttribute) -ne 0
        $childRel = if ($Rel -eq '') { $name } else { $Rel + '/' + $name }
        $state = $null
        if ($null -ne $Git) {
            if ($Inherited -ge 0) { $state = $Inherited }
            elseif ($name -eq '.git') { $state = $IGNORED }           # git never reports its own directory
            else {
                $mask = 0
                $known = $Git.Mask.TryGetValue($childRel, [ref]$mask)
                if ($Git.Tracked.Contains($childRel)) { $mask = $mask -bor $currentBit; $known = $true }
                if (-not $known) { $state = $UNMANAGED }              # git knows nothing about it, e.g. an empty directory
                else {
                    # a directory that still exists is changed, not deleted
                    if ($isDir -and ($mask -band $deletedBit)) { $mask = ($mask -band (-bnot $deletedBit)) -bor $changedBit }
                    $state = $CONFLICT                                # the most severe state in the mask
                    while (($mask -band (1 -shl $state)) -eq 0) { $state-- }
                }
            }
        }
        $size = $null
        if (-not $isDir) { $size = $fsi.Length }
        $names.Add($name)
        $recs.Add([pscustomobject]@{
            Name   = $name
            Rel    = $childRel
            IsDir  = $isDir
            Link   = ($attributes -band $linkAttribute) -ne 0
            State  = $state
            Size   = $size
            Time   = $fsi.LastWriteTime
            OnDisk = $true
        })
    }
    # Deleted files are not on disk; list them from git.
    if ($null -ne $Git -and $Inherited -lt 0) {
        $kids = $null
        if ($Git.Ghosts.TryGetValue($Rel, [ref]$kids)) {
            foreach ($kid in $kids.GetEnumerator()) {
                if ($onDisk.Contains($kid.Key) -or ($null -ne $Only -and -not $Only.Contains($kid.Key))) { continue }
                $names.Add($kid.Key)
                $recs.Add([pscustomobject]@{
                    Name = $kid.Key; Rel = ''; IsDir = $kid.Value; Link = $false
                    State = $DELETED; Size = $null; Time = $null; OnDisk = $false
                })
            }
        }
    }
    $keys = $names.ToArray()
    $entries = $recs.ToArray()
    # The IComparer cast selects the non-generic overload; the generic one would sort a
    # converted copy of $entries and leave it unsorted.
    [System.Array]::Sort($keys, $entries, [System.Collections.IComparer][System.StringComparer]::OrdinalIgnoreCase)
    $entries
}

# Lays out cells column by column like DIR /W. Plain texts give the widths, painted ones are printed.
function Format-Columns([string[]]$Plain, [string[]]$Painted, [int]$Width) {
    $count = $Plain.Count
    $nrows = $count
    $widths = @()
    $maxCols = [Math]::Max(1, [Math]::Min($count, [int][Math]::Floor($Width / 3)))
    for ($ncols = $maxCols; $ncols -ge 1; $ncols--) {
        $nrows = [int][Math]::Ceiling($count / [double]$ncols)
        $widths = [int[]]::new([int][Math]::Ceiling($count / [double]$nrows))
        for ($i = 0; $i -lt $count; $i++) {
            $c = [int][Math]::Floor($i / $nrows)
            if ($Plain[$i].Length -gt $widths[$c]) { $widths[$c] = $Plain[$i].Length }
        }
        $total = 2 * ($widths.Count - 1)
        foreach ($w in $widths) { $total += $w }
        if ($ncols -eq 1 -or $total -le $Width) { break }
    }
    for ($r = 0; $r -lt $nrows; $r++) {
        $line = [System.Text.StringBuilder]::new()
        for ($c = 0; $c -lt $widths.Count; $c++) {
            $i = $c * $nrows + $r
            if ($i -ge $count) { break }
            $null = $line.Append($Painted[$i])
            if ($i + $nrows -lt $count) { $null = $line.Append(' ' * ($widths[$c] - $Plain[$i].Length + 2)) }
        }
        $line.ToString()
    }
}

$termWidth = 0   # 0: one name per line, because the output is not a terminal
if ($Wide -and -not [Console]::IsOutputRedirected) {
    try { $termWidth = $Host.UI.RawUI.WindowSize.Width } catch { $termWidth = 80 }
    if ($termWidth -le 0) { $termWidth = 80 }
}

# The lines of one directory: names in columns with -Wide, else tag, date, size and name.
function Format-Entries($Entries) {
    $n = $Entries.Count
    if ($n -eq 0) { return }
    if ($Wide) {
        $plain = [string[]]::new($n)
        $painted = [string[]]::new($n)
        for ($i = 0; $i -lt $n; $i++) {
            $e = $Entries[$i]
            $name = $e.Name
            # no terminal control codes from file names
            if ($name.IndexOfAny($controlCharacters) -ge 0) { $name = [regex]::Replace($name, '[\x00-\x1f\x7f-\x9f]', '?') }
            if ($e.IsDir) { $name = '[' + $name + ']' }
            $k = $NOSTATE
            if ($null -ne $e.State) { $k = $e.State }
            $plain[$i] = $name
            $painted[$i] = $paintOn[$k] + $name + $paintOff[$k]
        }
        if ($termWidth -gt 0) { Format-Columns $plain $painted $termWidth } else { $painted }
        return
    }
    $sizes = [string[]]::new($n)
    $times = [string[]]::new($n)
    $sizeWidth = 0
    $timeWidth = 1
    for ($i = 0; $i -lt $n; $i++) {
        $e = $Entries[$i]
        if ($e.IsDir) { $sizes[$i] = '<DIR>' }
        elseif ($null -eq $e.Size) { $sizes[$i] = '-' }
        else { $sizes[$i] = $e.Size.ToString('N0') }
        if ($sizes[$i].Length -gt $sizeWidth) { $sizeWidth = $sizes[$i].Length }
        if ($e.OnDisk) { $times[$i] = $e.Time.ToString('g') }
        else { $times[$i] = '-' }
        if ($times[$i].Length -gt $timeWidth) { $timeWidth = $times[$i].Length }
    }
    for ($i = 0; $i -lt $n; $i++) {
        $e = $Entries[$i]
        $name = $e.Name
        if ($name.IndexOfAny($controlCharacters) -ge 0) { $name = [regex]::Replace($name, '[\x00-\x1f\x7f-\x9f]', '?') }
        $k = $NOSTATE
        $tag = ' '
        if ($null -ne $e.State) { $k = $e.State; $tag = $Style[$k].Tag }
        $paintOn[$k] + $tag + $paintOff[$k] + ' ' + $times[$i].PadRight($timeWidth) + ' ' + $sizes[$i].PadLeft($sizeWidth) + ' ' + $paintOn[$k] + $name + $paintOff[$k]
    }
}

$script:printed = 0       # blocks printed so far; a blank line goes between them
$script:failed = $false   # a path could not be shown: exit code 2 at the end
$script:wholeTrees = [System.Collections.Generic.Dictionary[string, object]]::new([System.StringComparer]::OrdinalIgnoreCase)
# directory -> what git knows below it; read for deleted files in directories that are gone

# Starts a block: the localized directory-header line, after a blank line unless it is the first block.
function Get-DirectoryHeaderPrefix {
    switch ([System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName) {
        'de' { return 'Verzeichnis von' }
        default { return 'Directory of' }
    }
}

$directoryHeaderPrefix = Get-DirectoryHeaderPrefix

function Get-GitBranchStatus([string]$Dir) {
    try {
        $job = Start-Git $Dir 'status --porcelain=v2 --branch --untracked-files=no'
        $raw = Receive-Git $job
    }
    catch {
        return $null
    }
    $branch = ''
    $upstream = ''
    $ahead = 0
    $behind = 0
    foreach ($line in $raw -split '\r?\n') {
        if ($line.StartsWith('# branch.head ')) { $branch = $line.Substring(14) }
        elseif ($line.StartsWith('# branch.upstream ')) { $upstream = $line.Substring(18) }
        elseif ($line -match '^# branch\.ab \+(\d+) -(\d+)$') {
            $ahead = [int]$matches[1]
            $behind = [int]$matches[2]
        }
    }
    if (-not $branch -or $branch -eq '(detached)') { return $null }
    if (-not $upstream) { $status = ': no upstream' }
    else {
        if ($ahead -eq 0 -and $behind -eq 0) { $state = 'up to date' }
        else {
            $states = @()
            if ($ahead -gt 0) { $states += "+$ahead" }
            if ($behind -gt 0) { $states += "-$behind" }
            $state = $states -join ' '
        }
        $status = " [$upstream]: $state"
    }
    return [pscustomobject]@{ Name = $branch; Upstream = $upstream; Status = $status }
}

function Write-Header([string]$Dir, $Branch) {
    ''
    if ($Branch) {
        $branchName = $Branch.Name
        $branchStatus = $Branch.Status
        if ($useColor) {
            $branchName = $esc + '[' + $Green + 'm' + $branchName + $esc + '[0m'
            if ($Branch.Upstream) {
                $remoteName = $esc + '[' + $Blue + 'm' + $Branch.Upstream + $esc + '[0m'
                $branchStatus = $branchStatus.Replace($Branch.Upstream, $remoteName)
            }
        }
        'Branch ' + $branchName + $branchStatus
    }
    $directoryHeaderPrefix + ' ' + $Dir
    ''
    $script:printed++
}

# Says what could not be shown. The other paths are still shown, the exit code becomes 2.
function Write-Failure([string]$Message) {
    [Console]::Error.WriteLine("gdir: $Message")
    $script:failed = $true
}

# Why reading a directory failed. PowerShell wraps the .NET error in a long localized message;
# the inner one says why.
function Get-ErrorReason($ErrorRecord) {
    $exception = $ErrorRecord.Exception
    if ($null -ne $exception.InnerException) { return $exception.InnerException.Message }
    return $exception.Message
}

# Prints one directory and, with -Recurse, everything below it, depth first. $Git is what git
# knows about the repository that contains $Dir, $Rel the path of $Dir below that repository's
# listing root, $Inherited as for Get-Entries.
function Write-Dir([string]$Dir, [string]$Rel, [int]$Inherited, $Git, $Branch = $null) {
    try { $entries = @(Get-Entries $Dir $Rel $Inherited $Git) }
    catch {
        Write-Failure "cannot read '$Dir': $(Get-ErrorReason $_)"
        return
    }
    if ($showHeaders) { Write-Header $Dir $Branch }
    Format-Entries $entries
    if (-not $Recurse) { return }
    foreach ($e in $entries) {
        if (-not $e.OnDisk -or -not $e.IsDir -or $e.Link -or $e.Name -eq '.git') { continue }
        $childDir = [System.IO.Path]::Combine($Dir, $e.Name)
        $childRel = $e.Rel
        $childInherited = $Inherited
        $childGit = $Git
        $marker = [System.IO.Path]::Combine($childDir, '.git')
        if ([System.IO.Directory]::Exists($marker) -or [System.IO.File]::Exists($marker)) {
            # Another repository (submodule, nested clone): its own git state colors its files.
            $childGit = Read-GitState $childDir $true
            $childRel = ''
            $childInherited = -1
            if ($null -ne $childGit) { $childInherited = $childGit.Base }
        }
        elseif ($Inherited -lt 0 -and $null -ne $Git) {
            $collapsedState = 0
            if ($Git.Collapsed.TryGetValue($e.Rel, [ref]$collapsedState)) { $childInherited = $collapsedState }
        }
        Write-Dir $childDir $childRel $childInherited $childGit
    }
}

# Prints the named files of one directory, as the entries a listing of the directory would
# show. $Names are @{ Name; Arg } records: the file name, and the argument as it was typed.
function Write-Files([string]$Dir, $Names) {
    $git = Read-GitState $Dir $false
    $inherited = -1
    $branch = $null
    if ($null -ne $git) { $inherited = $git.Base; $branch = Get-GitBranchStatus $Dir }
    $only = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($n in $Names) { $null = $only.Add($n.Name) }
    try { $entries = @(Get-Entries $Dir '' $inherited $git $only) }
    catch {
        Write-Failure "cannot read '$Dir': $(Get-ErrorReason $_)"
        return
    }
    $shown = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($e in $entries) { $null = $shown.Add($e.Name) }
    foreach ($n in $Names) {
        if (-not $shown.Contains($n.Name)) { Write-Failure "cannot access '$($n.Arg)': no such file or directory" }
    }
    if ($entries.Count -eq 0) { return }
    if ($showHeaders) { Write-Header $Dir $branch }
    Format-Entries $entries
}

# Deleted files whose directory is gone as well. Git still knows them: what it reports for the
# nearest directory that exists tells which files below it are deleted. $Dir is the directory
# that is gone, $Names as for Write-Files.
function Write-DeletedFiles([string]$Dir, $Names) {
    $ancestor = $Dir
    $branch = $null
    while ($ancestor -and -not [System.IO.Directory]::Exists($ancestor)) { $ancestor = [System.IO.Path]::GetDirectoryName($ancestor) }
    $kids = $null
    if ($ancestor) {
        $git = $null
        if (-not $script:wholeTrees.TryGetValue($ancestor, [ref]$git)) {
            $git = Read-GitState $ancestor $true
            $script:wholeTrees[$ancestor] = $git
        }
        if ($null -ne $git) { $branch = Get-GitBranchStatus $ancestor }
        if ($null -ne $git -and $git.Base -lt 0) {
            $below = $Dir.Substring($ancestor.Length).Trim('\', '/').Replace('\', '/')
            $null = $git.Ghosts.TryGetValue($below, [ref]$kids)
        }
    }
    $keys = [System.Collections.Generic.List[string]]::new()
    $recs = [System.Collections.Generic.List[object]]::new()
    foreach ($n in $Names) {
        $spelled = $null      # the name as git spells it
        if ($null -ne $kids) { foreach ($k in $kids.Keys) { if ($k -eq $n.Name) { $spelled = $k; break } } }
        if ($null -eq $spelled) { Write-Failure "cannot access '$($n.Arg)': no such file or directory"; continue }
        $keys.Add($spelled)
        $recs.Add([pscustomobject]@{
            Name = $spelled; Rel = ''; IsDir = $kids[$spelled]; Link = $false
            State = $DELETED; Size = $null; Time = $null; OnDisk = $false
        })
    }
    if ($recs.Count -eq 0) { return }
    $sortKeys = $keys.ToArray()
    $entries = $recs.ToArray()
    [System.Array]::Sort($sortKeys, $entries, [System.Collections.IComparer][System.StringComparer]::OrdinalIgnoreCase)
    if ($showHeaders) { Write-Header $Dir $branch }
    Format-Entries $entries
}

# --- what to show ----------------------------------------------------------------------------

# Every directory argument is a block of its own. The file arguments of one directory form one
# block, which stands where the first of them was given.
$targets = [System.Collections.Generic.List[object]]::new()
$fileTargets = [System.Collections.Generic.Dictionary[string, object]]::new([System.StringComparer]::OrdinalIgnoreCase)
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($arg in (@($Path) + @($Rest))) {
    if (-not $arg) { Write-Failure "cannot access '': no such file or directory"; continue }
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($arg)
    if (-not [System.IO.Path]::IsPathRooted($full)) { Write-Failure "cannot access '$arg': not a file system path"; continue }
    if ($full.Length -gt 3) { $full = $full.TrimEnd('\', '/') }
    if (-not $seen.Add($full)) { continue }
    if ([System.IO.Directory]::Exists($full)) { $targets.Add(@{ Dir = $full; Names = $null; Gone = $false }); continue }
    $parent = [System.IO.Path]::GetDirectoryName($full)
    if (-not $parent) { Write-Failure "cannot access '$arg': no such file or directory"; continue }
    $target = $null
    if (-not $fileTargets.TryGetValue($parent, [ref]$target)) {
        # Gone: the directory does not exist (any more); only a deleted file can be found there.
        $target = @{ Dir = $parent; Names = [System.Collections.Generic.List[object]]::new(); Gone = -not [System.IO.Directory]::Exists($parent) }
        $fileTargets[$parent] = $target
        $targets.Add($target)
    }
    $target.Names.Add(@{ Name = [System.IO.Path]::GetFileName($full); Arg = $arg })
}

$showHeaders = $true
foreach ($target in $targets) {
    if ($target.Gone) { Write-DeletedFiles $target.Dir $target.Names; continue }
    if ($null -ne $target.Names) { Write-Files $target.Dir $target.Names; continue }
    $rootGit = Read-GitState $target.Dir ([bool]$Recurse)
    $rootBase = -1
    $branch = $null
    if ($null -ne $rootGit) { $rootBase = $rootGit.Base; $branch = Get-GitBranchStatus $target.Dir }
    Write-Dir $target.Dir '' $rootBase $rootGit $branch
}
if ($script:failed) { exit 2 }
