# gdir - DIR listing colored by git state

## AI disclaimer
This document was created with the help of AI — model: Claude Sonnet 5.5 (model ID: claude-sonnet-5.5)

## What it does
`gdir` lists a directory like `DIR` (tag, date, size, name) and colors every entry by its state in git.
Name files instead, or as well, and it shows just those entries, the same way.
A file that was deleted is gone from the disk, so `gdir` lists it from git as well.
Outside a git work tree the listing is plain, with a note on stderr.

```
M 2026-09-03 15:03   8.175 build_articles.py
D -                      - company-product.schema.json
? 2026-09-11 13:12 741.494 consolidated-articles.json
  2026-09-02 13:17  34.003 asyncapi.bundle.yaml
```

## Files
| File | Purpose |
|---|---|
| `gdir.ps1` | The implementation, including the installer (`-Install`). Runs in Windows PowerShell 5.1 and PowerShell 7. |
| `gdir.cmd` | Starts `gdir.ps1` from `cmd.exe` (via Windows PowerShell, about 0.25 s start-up). |
| `.gitattributes` | Keeps `gdir.cmd` on CRLF line endings; `cmd.exe` mis-parses LF-only batch files that contain non-ASCII characters. |

## Usage
```
gdir [path...] [-Recurse] [-Wide] [-All] [-Color when] [-Legend]
gdir -Install [folder]
gdir --help
```
`gdir --help` prints a summary of the arguments; `gdir -?` shows the PowerShell help of the script.

### Arguments
| Argument | Short | Default | Description |
|---|---|---|---|
| `path...` (or `-Path path,...`) | | current directory | Files and directories to show, separated by spaces or commas. A directory is listed (with `-Recurse`: with its subdirectories). A file shows just its own entry, even when it is hidden, and so does a file that git has deleted, even when its directory is gone too. With several paths, every directory and the files of every directory come below a `Directory of <path>` line; the files of one directory are shown together in `DIR` order, the blocks follow the order of the arguments, and a path given twice is shown once. A path must exist, otherwise the exit code is 2; the other paths are still shown. Quote a path that contains spaces. Wildcards are not expanded. With `-Install`: the folder to install into. |
| `-Recurse` | `-r` | off | Also list the subdirectories, like `DIR /S`: every directory gets a `Directory of <path>` line, and the subdirectories follow depth first in `DIR` order. A subdirectory that is its own git repository (submodule, nested clone) is colored by that repository. The `.git` directory and directory links (junctions, symbolic links) are listed but not entered, and a directory that git reports as deleted is listed, not entered. Subdirectories that cannot be read are reported on stderr and skipped. |
| `-Wide` | `-w` | off | Names only, in columns like `DIR /W`; directories in `[brackets]`. One name per line when the output is not a terminal. |
| `-All` | `-a` | off | Also list entries with the Hidden or System attribute, such as `.git`. Without it they are left out, like `DIR` does. Deleted files are always listed. |
| `-Color when` | | `auto` | `auto`: color only on a terminal and only if the `NO_COLOR` environment variable is not set. `always`: color even when the output is redirected. `never`: plain text. |
| `-Legend` | | off | Print the color key and exit. |
| `-Install` | | off | Copy `gdir.ps1` and `gdir.cmd` to a folder and put that folder on the user `PATH`. The folder is the `path` argument, default `c:\tools`. See Install. |
| `--help` | `-h`, `-Help`, `/?` | | Print the usage page and exit. |

Options are PowerShell parameters: not case-sensitive, and unambiguous abbreviations work (`-Col never`, `-Rec`); `-Color:never` works too. DIR switches such as `/W` are not supported.
Entries are sorted case-insensitively, like `DIR`.

Exit codes: `0` listing printed (a plain one, with a note on stderr, outside a git work tree) or installation done; `2` a path cannot be shown (it does not exist or cannot be read; with `-Install`: the folder is not valid, or a file to install is missing), or unknown argument; `1` invalid `-Color` value (reported by PowerShell).

### Examples
```
gdir                    list the current directory
gdir ..\other           list another directory
gdir a.txt ..\b\c.txt   show just these files
gdir src a.txt          a directory and a file, each below a Directory of line
gdir (git diff --name-only --relative)
                        the files git reports as changed (PowerShell)
gdir -r                 the whole tree below the current directory
gdir -r -Wide           the whole tree, names only
gdir -All -Color never  include .git, no color codes
gdir -Install           copy gdir to c:\tools and put it on the PATH
gdir -Install D:\bin    the same for another folder
```

## States
| State | Color | Tag | Meaning |
|---|---|---|---|
| current | green | blank | tracked, unchanged |
| changed | yellow | `M` | modified in the working tree |
| staged | light blue | `+` | changes staged in the index, nothing newer in the working tree |
| unmanaged | white | `?` | untracked: git does not manage it |
| deleted | red, struck through | `D` | tracked but gone from the working tree |
| conflict | bold white on red | `U` | unmerged paths |
| ignored | gray | `!` | matches `.gitignore` |

These are the default colors, see Configuration.
A directory shows the most severe state inside it: conflict > changed > staged > unmanaged > current > ignored.
A deleted file inside a directory makes the directory *changed*; *deleted* is only shown for entries that are gone.
A directory that git does not know (for example an empty one) is *unmanaged*.

## Configuration
The colors are set in the configuration block at the top of `gdir.ps1`. It names the colors and gives every state one of them:

```powershell
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

$StateColors = @{
    current   = $Green
    changed   = $Yellow
    staged    = $LightBlue
    unmanaged = $White
    deleted   = @{ Color = $Red; Strike = $true }
    conflict  = @{ Color = $White; Bold = $true; Background = $Red }
    ignored   = $Gray
}
```

Change the named color on the right of a state to recolor it; `gdir -Legend` shows the result.
A state can also take `@{ Color = ...; Strike = $true; Bold = $true; Background = ... }`: `Strike` (strikethrough), `Bold` and `Background` (a named color) are optional.
The named colors are ANSI escape codes (SGR, Select Graphic Rendition) for the text color; the terminal theme decides the exact shade. Add more the same way, for example `$Cyan = '36'`.
A broken block (a state without a color, a color that is not a number) stops `gdir` with exit code 2 and names the state; `gdir --help` still works.

## How it works
For the listed directory `gdir` runs three git queries in parallel:
`git rev-parse --show-prefix`, `git status --porcelain=v1 -z --no-renames --ignored=matching --untracked-files=normal`
and `git ls-files -z`. With `-Recurse` the same three queries cover the whole subtree, and a subdirectory that is
its own repository gets its own queries. They only read: `--no-optional-locks` keeps `gdir` from taking the index lock,
so it does not disturb an IDE that runs git in the background. `git.exe` is started directly, not a `git.bat` wrapper,
because a wrapper may swallow git's exit code.

Because renames are not detected, the old name of a renamed file is listed as *deleted* and the new name as *staged*.

## Install
`gdir -Install` copies `gdir.ps1` and `gdir.cmd` to a folder and puts that folder on the user `PATH`. Run it from the folder that holds the two files:

```powershell
.\gdir.ps1 -Install          # into c:\tools
.\gdir.ps1 -Install D:\bin   # into another folder
```

From `cmd.exe`: `gdir.cmd -Install` or `gdir.cmd -Install D:\bin`.

- The folder is the `path` argument, default `c:\tools`. It is created if needed. A file that is already up to date is left alone, so running `-Install` again updates an installation. The folder must not contain `;` or `%`.
- The folder is added to the user `PATH`, unless it is already part of the user or the machine `PATH`. Entries are compared ignoring case, quotes, a trailing `\`, `/` versus `\`, and `%VARIABLES%`. No administrator rights are needed.
- The `PATH` value is written back with the kind it has (a new value becomes an expandable string), so `%VARIABLES%` in existing entries keep working.
- Programs that are already running keep their old `PATH`. `-Install` notifies running programs of the change (`WM_SETTINGCHANGE`), so terminals opened afterwards see it, and it updates the `PATH` of the running PowerShell session, so `gdir` works there at once.

In PowerShell, `gdir` then runs `gdir.ps1` in the current session; in `cmd.exe` it runs `gdir.cmd`.
Requirements: `git` on the `PATH` and an execution policy that allows local scripts (`Get-ExecutionPolicy`: RemoteSigned or less strict).
