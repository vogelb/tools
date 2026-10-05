# gdir - DIR listing colored by git state

## What it does
`gdir` lists a directory like `DIR` (a directory header, tag, date, size, name) and colors every entry by its state in git.  
A file that was deleted is gone from the disk, so `gdir` lists it from git as well.
Outside a git work tree the listing is plain, with a note on stderr.
There are two implementations with the same behavior, and both are called `gdir`: `gdir.ps1` (with `gdir.cmd`) runs in Windows PowerShell and `cmd.exe`, the bash script `gdir` in bash (Git Bash, WSL, Linux).  
All of them can sit in one folder on the `PATH` (`c:\tools`): every shell runs its own. The sections below describe `gdir.ps1`; the section *gdir (bash)* says how the bash script is used and where it differs.

```
M 2026-09-03 15:03   8.175 build_articles.py
D -                      - company-product.schema.json
? 9/11/2026 1:12:00 PM 741.494 consolidated-articles.json
  2026-09-02 13:17  34.003 asyncapi.bundle.yaml
```

## Files
| File | Purpose |
|---|---|
| `gdir.ps1` | The PowerShell implementation, including the installer (`-Install`). Runs in Windows PowerShell 5.1 and PowerShell 7. |
| `gdir.cmd` | Starts `gdir.ps1` from `cmd.exe` (via Windows PowerShell, about 0.25 s start-up). |
| `gdir` | The bash implementation, including the installer (`--install`). Runs in Git Bash, WSL and Linux. |
| `.gitattributes` | Keeps `gdir.cmd` on CRLF line endings (`cmd.exe` mis-parses LF-only batch files that contain non-ASCII characters) and `gdir` on LF (bash does not run a script with CRLF line endings). |
| `test/test_gdir_sh.py` | Tests of the bash script `gdir` against a git oracle. See Tests. |

## Usage (gdir.ps1)
```
gdir [path...] [-Recurse] [-Wide] [-All] [-Color when] [-Legend]
gdir -Install [folder]
gdir --help
```
`gdir --help` prints a summary of the arguments; `gdir -?` shows the PowerShell help of the script.

### Arguments
| Argument | Short | Default | Description |
|---|---|---|---|
| `path...` (or `-Path path,...`) | | current directory | Files and directories to show, separated by spaces or commas. A directory is listed (with `-Recurse`: with its subdirectories). A file shows just its own entry, even when it is hidden, and so does a file that git has deleted, even when its directory is gone too. A top-level block in a Git work tree starts with `Branch <name> [<upstream>]: up to date` above its localized `DIR`-style directory header. The local branch is green and its upstream is blue when color is enabled. Branches ahead or behind show only the relevant counts, such as `+2`, `-1`, or `+2 -1`. A branch without an upstream shows `Branch <name>: no upstream`. The files of one directory are shown together in `DIR` order, the blocks follow the order of the arguments, and a path given twice is shown once. A path must exist, otherwise the exit code is 2; the other paths are still shown. Quote a path that contains spaces. Wildcards are not expanded. With `-Install`: the folder to install into. |
| `-Recurse` | `-r` | off | Also list the subdirectories, like `DIR /S`: every directory gets a localized directory-header line, and the subdirectories follow depth first in `DIR` order. The branch line is shown only for each top-level argument, not recursive child blocks. A subdirectory that is its own git repository (submodule, nested clone) is colored by that repository. The `.git` directory and directory links (junctions, symbolic links) are listed but not entered, and a directory that git reports as deleted is listed, not entered. Subdirectories that cannot be read are reported on stderr and skipped. |
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
gdir src a.txt          a directory and a file, each below a localized directory header
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
| current | green | `✓` | tracked, unchanged |
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

## Configuration (gdir.ps1)
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

## Install (gdir.ps1)
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

## gdir (bash)
The bash script `gdir` is the port of `gdir.ps1`: the same listing, states, colors, file lists, localized directory-header blocks and exit codes (`0`, `2`). It runs in Git Bash, WSL and Linux and needs bash 4.4 or newer, `git`, and GNU `find` and `sort`.

### Usage
```
gdir [options] [path...]
gdir --install [folder]
gdir --help
```

| Option | Short | Description |
|---|---|---|
| `path...` | | Files and directories to show, as for `gdir.ps1`. The shell expands wildcards, not `gdir`. |
| `--recurse` | `-r` | Also list the subdirectories, like `gdir -Recurse`. |
| `--wide` | `-w` | Names only, in columns like `DIR /W`; directories in `[brackets]`. One name per line when the output is not a terminal. On a terminal the width is the one of the terminal, or `COLUMNS` if that is set. |
| `--all` | `-a` | Also list entries whose names start with a dot, such as `.git`. Without it they are left out, like `ls` does. |
| `--color=when` | | `auto` (default), `always` or `never`, as `-Color` of `gdir.ps1`. A bare `--color` means `always`. |
| `--legend` | | Print the color key and exit. |
| `--install` | | Copy `gdir` to a folder and add the folder to the `PATH` of new shells. See Install (bash). |
| `--help` | `-h` | Print the usage page and exit. |

Short options combine (`-ra`); `--` ends the options; `--help` anywhere shows the usage page.

```
gdir                    list the current directory
gdir -r                 the whole tree below the current directory
gdir a.txt ../b/c.txt   show just these files
git diff -z --name-only --relative | xargs -0 -r gdir
                        the files git reports as changed
```

### Differences from gdir.ps1
- *Hidden* means a leading dot, as for `ls`: `.gitignore` is listed with `-a` only. `gdir.ps1` leaves out entries with the Hidden or System attribute instead, which on Windows are not the dot files.
- The options are GNU style (`-r`, `--recurse`), not PowerShell parameters.
- Paths in directory-header lines and in messages are spelled the way bash spells them (`/c/dev/x` in Git Bash). Paths you pass may use any spelling bash accepts, and in Git Bash also `C:\dev\x` and `C:/dev/x`.
- Sizes get a thousands separator only if the locale defines one.
- A directory link is what `find` reports as a symbolic link; in Git Bash that includes junctions. It is listed and, with `-r`, not entered.

### Configuration (bash)
The colors are set in the configuration block at the top of `gdir`: named colors (ANSI SGR codes) and the color of every state.

```bash
STATE_COLORS=(
    [current]=$GREEN
    [changed]=$YELLOW
    [staged]=$LIGHTBLUE
    [unmanaged]=$WHITE
    [deleted]="$RED strike"
    [conflict]="$WHITE bold on $RED"
    [ignored]=$GRAY
)
```

After the color a state can take `bold`, `strike` (strikethrough) and `on COLOR` (a background). A broken block stops `gdir` with exit code 2 and names the state; `gdir --legend` shows the colors in use.

### Install (bash)
`gdir --install [folder]` copies the script to a folder and makes it available in new shells:

- The folder is created if needed. Default: `/c/tools` in Git Bash (the folder `gdir -Install` uses, too), else `~/.local/bin`. A copy that is already up to date is left alone, so running it again updates an installation.
- Unless the folder is already on the `PATH`, the line `export PATH="$PATH":<folder>` is appended to `~/.bashrc` (once). Open a new shell, or run `source ~/.bashrc`.
- The script is installed as `gdir`, next to `gdir.ps1` and `gdir.cmd` if `gdir -Install` put them in the same folder. If the folder already holds a folder named `gdir`, `--install` stops with exit code 2.

### How the bash version works
The three git queries of `gdir.ps1` run as background processes. The entries come from one `find -printf` and one `sort`, and the listing is made inside bash, without a process per entry. Two details come from Git Bash: git runs inside the directory (`cd`), not with `git -C`, because Git Bash cannot convert a path argument that contains `[` or `$` for a native Windows program; and a terminal's width is asked with `stty size`, because `tput` inside a command substitution cannot see the terminal.

Speed: a small directory takes about 0.2 s in Git Bash; a directory with 8,000 entries (3,000 of them deleted files) takes about 5 s.

## Tests
`test/test_gdir_sh.py` tests the bash script `gdir` against a git oracle. It builds a sandbox repository with something in every state (modified, staged, untracked, ignored, deleted, conflicted, a nested repository, a linked worktree, a directory link, awkward file names), runs `gdir` on it and compares every tag, name, size, date and the order of the output with what `git status` and `git ls-files` report. It also covers colors, options, messages and exit codes, file lists, `--install` (in a throw-away `HOME`) and, on Linux and WSL, the automatic colors and the `--wide` columns on a pseudo terminal. On Windows with PowerShell 7 the output is also compared with the one of `gdir.ps1`.

```
python tools/gdir/test/test_gdir_sh.py             all tests (about 1 minute)
python tools/gdir/test/test_gdir_sh.py -k colors   tests whose name contains "colors"
python tools/gdir/test/test_gdir_sh.py --keep      keep test/.sandbox afterwards
```

- Needs Python 3.8+, `git` and bash 4.4+. On Windows the test finds Git Bash next to `git`; `GDIR_TEST_BASH` selects another bash.
- The sandbox lives in `test/.sandbox` (not tracked by git, removed afterwards). `GDIR_TEST_SANDBOX` moves it, for example to a Linux file system that is case-sensitive and has permissions; the test only deletes a folder that it made itself or that is empty.
- Nothing outside the repository is written (unless `GDIR_TEST_SANDBOX` says so). `--install` is only run with a folder of the sandbox, never with its default folder.
- On Windows five tests are skipped: three need a pseudo terminal, one needs Unix file permissions (and a user who is not root), and one would install into the default folder of Linux. Run the suite in WSL to cover them: `python3 tools/gdir/test/test_gdir_sh.py` (as root the permissions test is skipped; `wsl -u nobody` runs it).
