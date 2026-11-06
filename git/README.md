# Git tools

## AI disclaimer
This document was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)

This folder contains `gdir` for Git-aware directory listings and `gupdate` for updating repositories.

## gupdate - Update Git repositories with fast-forward-only pulls
Run `gupdate` with repository paths to update those repositories using `git pull --ff-only`. If a path is a folder without its own `.git` directory or file, its immediate child repositories are updated instead. With no paths, it updates the immediate child repositories in the current working directory. It does not recurse further.

From the repository root in PowerShell:

```powershell
.\git\gupdate.ps1
```

`gupdate.ps1` runs in Windows PowerShell 5.1 and PowerShell 7. `gupdate.cmd` starts it from `cmd.exe`, like `gdir.cmd`; the Linux `gupdate` launcher starts it with `pwsh`. These replace the old `gupdate.bat`. Use `call gupdate.cmd` when invoking it from another batch script.

Git must be on `PATH`. Git batch wrappers are supported; PowerShell resumes after the wrapper and checks its exit code. The script continues after failed resets or pulls and returns `1` if any reset or pull fails or Git is unavailable, otherwise `0` (including when no repositories are found). Invalid arguments, directory access errors and installation failures return `2`. It does not switch branches, stash changes, or create merge commits; divergent branches require manual resolution.

### Usage
```
gupdate [path...] [--force]
gupdate -Install [folder]
gupdate --help
```

Paths may be relative or absolute; quote paths containing spaces. For example, `gupdate repo-one "folder with repos"` updates `repo-one` and the immediate child repositories of the folder. In PowerShell, `-Path repo-one,repo-two` also works. All explicit paths must be directories and are validated before any reset or pull; missing paths and files return `2`. Overlapping arguments update each repository only once. Folders without repositories are skipped successfully. `gupdate .` updates the current directory itself if it is a repository, otherwise its immediate child repositories.

`--force` (also `-Force` in PowerShell) prints a warning before running `git reset --hard HEAD` in each repository, then pulling. **This discards all staged and unstaged tracked changes and may remove untracked paths obstructing tracked files.** Other untracked files and local commits are kept; this is not a reset to the remote branch. A failed reset skips that repository's pull and the other repositories are still processed. `--force` cannot be combined with `-Install`.

### Install
From the folder containing the scripts:

```powershell
.\gupdate.ps1 -Install          # into c:\tools
.\gupdate.ps1 -Install D:\bin   # into another folder
```

From `cmd.exe`: `gupdate.cmd -Install [folder]`. The installer copies `gupdate.ps1`, `gupdate.cmd` and `git-tools-install.ps1`, creating the target folder if necessary. Running it again updates changed files and leaves unchanged files alone.

Like `gdir -Install`, it adds the folder to the user `PATH` unless already present in the user or machine `PATH`, preserves existing `%VARIABLES%` and the registry value kind, notifies Windows of the change, and updates the current PowerShell session's `PATH`. No administrator rights are needed. A child process launched by the cmd wrapper cannot change its parent terminal's `PATH`; open a new terminal after installation from cmd.exe.

Keep the shared installer next to the scripts to use `-Install`. On Windows the install folder must not contain `;` or `%`. PowerShell must allow local scripts. For configurable Linux installation, see [Linux launchers](#linux-launchers). To update repositories, change to their parent directory and run `gupdate`.

### Tests
From the repository root:

```
python git\test\test_gupdate.py
```

Runs against available PowerShell versions on Windows and Linux; Windows-only wrapper and registry tests are skipped on Linux. Covers local pulls, continuation after failure, `.git` files, nonrecursive behavior, force resets and warnings, help and missing Git. On Windows it also covers divergent branches, Git batch wrappers, the cmd wrapper and installation. Installation tests mock Windows PATH persistence and notifications; they do not modify the real user environment. Temporary files stay under `git\test` and are removed afterwards.

## gdir - DIR listing colored by git state

### What it does
`gdir` lists a directory like `DIR` (a directory header, tag, date, size, name) and colors every entry by its state in git.  
A file that was deleted is gone from the disk, so `gdir` lists it from git as well.
Outside a git work tree the listing is plain, with a note on stderr.
There is one PowerShell implementation: `gdir.ps1`. The `gdir.cmd` and Linux `gdir` launchers execute it from their respective shells. Colors, Git queries and listing behavior are shared across platforms.

Above each branch status, `Repository <name>` shows the repository root folder's name, including when listing a subdirectory. Recursive listings also show the repository name and branch status when entering a nested repository or linked worktree. Ordinary subfolders do not repeat them.

```
M 2026-09-03 15:03   8.175 build_articles.py
D -                      - company-product.schema.json
? 9/11/2026 1:12:00 PM 741.494 consolidated-articles.json
  2026-09-02 13:17  34.003 asyncapi.bundle.yaml
```

### Files
| File | Purpose |
|---|---|
| `gdir.ps1` | The PowerShell implementation, including the installer (`-Install`). Runs in Windows PowerShell 5.1 and PowerShell 7. |
| `gdir.cmd` | Starts `gdir.ps1` from `cmd.exe` (via Windows PowerShell, about 0.25 s start-up). |
| `gdir`, `gupdate` | Linux bash launchers for the corresponding PowerShell scripts, with dependency checks. |
| `git-tools-install.ps1` | Shared Windows and Linux installer used by `gdir.ps1` and `gupdate.ps1`. |
| `.gitattributes` | Keeps cmd wrappers on CRLF line endings and Linux launchers on LF. |
| `test/test_gdir_sh.py` | Tests of the bash script `gdir` against a git oracle. See Tests. |

### Usage (gdir.ps1)
```
gdir [path...] [-Recurse] [-Wide] [-All] [-Color when] [-Legend]
gdir -Install [folder]
gdir --help
```
`gdir --help` prints a summary of the arguments; `gdir -?` shows the PowerShell help of the script.

### Arguments
| Argument | Short | Default | Description |
|---|---|---|---|
| `path...` (or `-Path path,...`) | | current directory | Files and directories to show, separated by spaces or commas. A directory is listed (with `-Recurse`: with its subdirectories). A file shows just its own entry, even when it is hidden, and so does a file that git has deleted, even when its directory is gone too. A top-level block in a Git work tree starts with `Repository <name>`, then `Branch <name> [<upstream>]: up to date`, above its localized `DIR`-style directory header. The local branch is green and its upstream is blue when color is enabled. Branches ahead or behind show only the relevant counts, such as `+2`, `-1`, or `+2 -1`. A branch without an upstream shows `Branch <name>: no upstream`. The files of one directory are shown together in `DIR` order, the blocks follow the order of the arguments, and a path given twice is shown once. A path must exist, otherwise the exit code is 2; the other paths are still shown. Quote a path that contains spaces. Wildcards are not expanded. With `-Install`: the folder to install into. |
| `-Recurse` | `-r` | off | Also list the subdirectories, like `DIR /S`: every directory gets a localized directory-header line, and the subdirectories follow depth first in `DIR` order. Repository and branch headers appear for each top-level argument and when entering a nested repository or linked worktree, but not ordinary subfolders. A subdirectory that is its own git repository (submodule, nested clone) is colored by that repository. The `.git` directory and directory links (junctions, symbolic links) are listed but not entered, and a directory that git reports as deleted is listed, not entered. Subdirectories that cannot be read are reported on stderr and skipped. |
| `-Wide` | `-w` | off | Names only, in columns like `DIR /W`; directories in `[brackets]`. One name per line when the output is not a terminal. |
| `-All` | `-a` | off | Also list entries with the Hidden or System attribute, such as `.git`. Without it they are left out, like `DIR` does. Deleted files are always listed. |
| `-Color when` | | `auto` | `auto`: color only on a terminal and only if the `NO_COLOR` environment variable is not set. `always`: color even when the output is redirected. `never`: plain text. |
| `-Legend` | | off | Print the color key and exit. |
| `-Install` | | off | Copy the PowerShell script, platform launcher and shared installer to a folder and put it on the user `PATH`. The folder is the `path` argument, default `c:\tools` on Windows or `~/.local/bin` on Linux. See Install. |
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

### States
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

### Configuration (gdir.ps1)
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

### How it works
For the listed directory `gdir` runs three git queries in parallel:
`git rev-parse --show-prefix`, `git status --porcelain=v1 -z --no-renames --ignored=matching --untracked-files=normal`
and `git ls-files -z`. With `-Recurse` the same three queries cover the whole subtree, and a subdirectory that is
its own repository gets its own queries. They only read: `--no-optional-locks` keeps `gdir` from taking the index lock,
so it does not disturb an IDE that runs git in the background. `git.exe` is started directly, not a `git.bat` wrapper,
because a wrapper may swallow git's exit code.

Because renames are not detected, the old name of a renamed file is listed as *deleted* and the new name as *staged*.

### Install (gdir.ps1)
`gdir -Install` copies `gdir.ps1`, `gdir.cmd` and `git-tools-install.ps1` to a folder and puts that folder on the user `PATH`. Run it from the folder that holds these files:

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

## Linux launchers
`gdir` and `gupdate` are thin bash wrappers around their sibling `.ps1` files, not separate implementations. They require bash, PowerShell 7 (`pwsh`) and Git on `PATH`. Each wrapper checks for `pwsh`, Git and a readable companion script, reports missing dependencies on stderr and exits with code `2`. GNU `find` and `sort` are no longer required.

### Usage
```bash
./git/gdir --color=never
./git/gdir -ra
./git/gupdate
./git/gupdate --force
```

`gdir` translates GNU-style options (`--recurse`, `--wide`, `--all`, `--legend`, `--color=when`, `--install`) to PowerShell parameters, including combined `-rwa`. `--` allows paths starting with `-`. Other arguments are passed through without losing quoting. Both wrappers use `exec`, preserving the PowerShell exit code and current working directory. Color configuration lives only in `gdir.ps1`.

### Configurable installation folder
```bash
./git/gdir --install                    # default: ~/.local/bin
./git/gupdate --install "$HOME/my-bin"  # custom folder
./git/gdir --install "$HOME/my-bin"     # share the same custom folder
```

The same folder argument works with `pwsh -File ... -Install [folder]`. Linux installation copies the launcher, `.ps1` file and shared installer, marks the launcher executable (`chmod` is required), and adds a safely quoted PATH entry to `~/.bashrc` once unless already on `PATH`. Open a new bash shell or run `source ~/.bashrc`. The launched child process cannot change its parent shell's environment. Reinstalling updates changed files without rewriting unchanged ones. Linux install folders must not contain `:`, the PATH separator.

### Tests
```bash
python3 git/test/test_shell_launchers.py
python3 git/test/test_gupdate.py
python3 git/test/test_gdir_sh.py
```

The launcher tests cover dependencies, missing companion files, argument forwarding, exit codes, configurable and default Linux installation, idempotency, quoting and case-sensitive file names. Installation uses temporary HOME directories under `git/test`, never the real shell configuration. `test_gdir_sh.py` provides Git-oracle listing tests.
