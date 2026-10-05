#!/usr/bin/env python3
# test_gdir_sh.py - tests of the bash script gdir against an independent git oracle
#
# What it does
#   Builds a sandbox repository with something in every git state (modified, staged, untracked,
#   ignored, deleted, conflicted, a nested repository, a linked worktree, a directory link, awkward
#   file names, ...), runs gdir on it and checks every tag, name, size, date and the order of
#   the output against what "git status" and "git ls-files" report. It also checks the colors, the
#   options, the messages and exit codes, --install (in a throw-away HOME) and, where a pseudo
#   terminal exists (Linux, WSL), the automatic colors and the columns of --wide. On Windows with
#   PowerShell 7 the output is also compared with the one of gdir.ps1.
#
# Run (from anywhere)
#   python tools/gdir/test/test_gdir_sh.py              all tests
#   python tools/gdir/test/test_gdir_sh.py --keep       keep test/.sandbox afterwards, for a look
#   python tools/gdir/test/test_gdir_sh.py -k colors    only tests whose name contains "colors"
#   python -m unittest discover -s tools/gdir/test      the same through unittest (no --keep; use
#                                                       GDIR_TEST_KEEP=1)
#   GDIR_TEST_BASH=/path/to/bash selects the bash; default: Git Bash on Windows, else "bash".
#   GDIR_TEST_SANDBOX=/dir puts the sandbox elsewhere, e.g. on a case-sensitive file system with
#   permissions (Linux). It is only deleted if it is empty or was made by this test.
#
# Needs Python 3.8+, git and bash 4.4+ (Git Bash, Linux, WSL). Everything is created below
# test/.sandbox and removed afterwards; nothing outside the repository is written. --install is
# never run without a folder, because its default folder (c:\tools in Git Bash) is outside it.
#
# This file was created with the help of AI — model: Claude Sonnet 5.5 (model ID: claude-sonnet-5.5)

import datetime
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "gdir"
PS1 = HERE.parent / "gdir.ps1"
SANDBOX_MARKER = ".gdir-test-sandbox"
SANDBOX = pathlib.Path(os.environ["GDIR_TEST_SANDBOX"]).resolve() if os.environ.get("GDIR_TEST_SANDBOX") else HERE / ".sandbox"
REPO = SANDBOX / "repo"        # the repository with something in every state
PLAIN = SANDBOX / "plain"      # a directory that is in no repository
WORK = SANDBOX / "work"        # HOME and install folders of the --install tests

IS_WINDOWS = os.name == "nt"
# file systems that ignore case: gdir then compares names ignoring case, too
FOLD = IS_WINDOWS or sys.platform == "darwin"
KEEP = os.environ.get("GDIR_TEST_KEEP") == "1"

GIT = shutil.which("git.exe" if IS_WINDOWS else "git")
PWSH = shutil.which("pwsh") if IS_WINDOWS else None


def find_bash():
    given = os.environ.get("GDIR_TEST_BASH")
    if given:
        return given
    if IS_WINDOWS and GIT:
        # "bash" on the PATH may be the WSL launcher; Git Bash sits next to git
        exec_path = subprocess.run([GIT, "--exec-path"], capture_output=True, text=True).stdout.strip()
        candidate = pathlib.Path(exec_path).parents[2] / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("bash")


BASH = find_bash()


def to_posix(path):
    """C:\\dir\\x -> /c/dir/x for Git Bash; other systems keep the path"""
    s = str(path)
    if IS_WINDOWS:
        m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
        if m:
            return "/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
        return s.replace("\\", "/")
    return s


def win_header(header):
    """/c/dir/x as gdir prints it in Git Bash -> C:\\dir\\x"""
    if IS_WINDOWS and header:
        m = re.match(r"^/([A-Za-z])(/.*)?$", header)
        if m:
            return (m.group(1).upper() + ":" + (m.group(2) or "/")).replace("/", "\\")
    return header


def canon(path):
    """the same spelling for a directory however it was reached: the parent resolved (so that a
    drive substitution or a link above does not matter), the last name as it is"""
    p = pathlib.Path(path)
    s = str(p.parent.resolve() / p.name)
    return s.lower() if FOLD else s


# ---------------------------------------------------------------------------------------------
# running programs

def base_env(extra=None):
    env = dict(os.environ)
    # git refuses repositories owned by somebody else (a Windows drive seen from WSL): accept them, for
    # the processes of this run only
    env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": "*"})
    for name in ("NO_COLOR", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CEILING_DIRECTORIES", "COLUMNS"):
        env.pop(name, None)
    env.update(extra or {})
    return env


class Result:
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    def __repr__(self):
        return "Result(rc=%r, err=%r, out=%r)" % (self.rc, self.err, self.out[:400])


def run(argv, cwd=None, env=None, timeout=180):
    r = subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, env=base_env(env), timeout=timeout)
    return Result(r.returncode,
                  r.stdout.decode("utf-8", "replace").replace("\r\n", "\n"),
                  r.stderr.decode("utf-8", "replace").replace("\r\n", "\n").strip())


def gdir(*args, cwd=None, env=None):
    """runs gdir the way a user would: bash gdir args"""
    return run([BASH, to_posix(SCRIPT), *args], cwd=cwd or REPO, env=env)


def gdir_with_path(path_value, *args, cwd=None):
    """runs gdir with PATH=path_value; bash itself is started by its full name"""
    return run([BASH, "-c", 'PATH=%s exec "$BASH" "$@"' % shlex.quote(path_value), "x", to_posix(SCRIPT), *args], cwd=cwd or REPO)


def git(cwd, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(cwd), capture_output=True, env=base_env())
    if check and r.returncode:
        raise RuntimeError("git %s failed in %s: %s" % (" ".join(args), cwd, r.stderr.decode("utf-8", "replace")))
    return r


def rmtree_force(path):
    path = pathlib.Path(path)

    def onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=onerror)


def is_link(path):
    if IS_WINDOWS:
        try:
            return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return False
    return os.path.islink(path)


# ---------------------------------------------------------------------------------------------
# the sandbox

# names that break careless quoting; all untracked, except the ones in TRACKED_SPECIAL
SPECIAL_UNTRACKED = ["we[ir]d.txt", "$dollar.txt", "it's.txt", "semi;colon.txt", "a&b.txt", "(paren).txt",
                     "{brace}.txt", "#hash.txt", "~tilde.txt", "!bang.txt", "100%.txt", "x^y.txt",
                     "eq=ual.txt", "comma,name.txt", "two  spaces.txt", "back`tick.txt", "日本語.txt",
                     "$(touch pwned_marker).txt"]
TRACKED_SPECIAL = ["we[ir]d tracked.txt", "$(touch pwned_marker) tracked.txt", "dir [x] $y/inner.txt"]
# two directories that differ only in case: their files must not get mixed up (case-sensitive systems only)
CASE_VARIANTS = [] if FOLD else ["Casedir/a.txt", "Casedir/c.txt", "casedir/b.txt"]


def build_sandbox():
    REPO.mkdir(parents=True)
    (SANDBOX / SANDBOX_MARKER).write_text("made by test_gdir_sh.py, which may delete this directory\n")
    PLAIN.mkdir()
    WORK.mkdir()

    def w(rel, text="x\n"):
        p = REPO / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def configure(where):
        for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false"), ("commit.gpgsign", "false")):
            git(where, "config", key, value)

    git(REPO, "init", "-q")
    configure(REPO)
    w(".gitignore", "*.log\nbuild/\n__pycache__/\n")
    base = {
        ".hidden": "h\n", "current.txt": "c\n", "changed.txt": "c\n", "staged.txt": "s\n", "both.txt": "b\n",
        "deleted.txt": "d\n", "deleted_staged.txt": "d\n", "rmcached.txt": "r\n", "renamed_old.txt": "r\n",
        "name with spaces.txt": "n\n", "ünïcode.txt": "u\n", "Case.TXT": "c\n", "conflict.txt": "base\n",
        "dir_clean/a.txt": "a\n", "dir_changed/b.txt": "b\n", "dir_deleted/a.txt": "a\n",
        "dir_deleted_partial/a.txt": "a\n", "dir_deleted_partial/b.txt": "b\n", "dir_ignored_mix/keep.txt": "k\n",
        "sub/inner.txt": "i\n", "sub/deeper/x.txt": "x\n", "sub/deeper/z.txt": "z\n",
        "sub/gone_dir/f.txt": "f\n", "sub/newdir/deep/q.txt": "q\n",
    }
    for name in TRACKED_SPECIAL:
        base[name] = "t\n"
    for name, text in base.items():
        w(name, text)
    git(REPO, "add", "-A")
    git(REPO, "commit", "-qm", "base")
    main_branch = git(REPO, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
    git(REPO, "checkout", "-q", "-b", "other")
    w("conflict.txt", "other\n")
    git(REPO, "commit", "-qam", "other")
    git(REPO, "checkout", "-q", main_branch)
    w("conflict.txt", "main\n")
    git(REPO, "commit", "-qam", "main")
    # a linked worktree (its .git is a file) with a change, a new and a deleted file
    git(REPO, "worktree", "add", "-q", "wt", "-b", "wtbranch")
    (REPO / "wt" / "current.txt").write_bytes(b"changed in wt\n")
    (REPO / "wt" / "wt_untracked.txt").write_bytes(b"u\n")
    os.remove(REPO / "wt" / "deleted.txt")
    git(REPO, "merge", "other", check=False)          # conflict.txt becomes UU
    w("changed.txt", "changed\n")
    w("staged.txt", "staged\n")
    git(REPO, "add", "staged.txt")
    w("both.txt", "b1\n")
    git(REPO, "add", "both.txt")
    w("both.txt", "b2\n")                              # staged and changed again
    w("staged_new.txt", "n\n")
    git(REPO, "add", "staged_new.txt")
    os.remove(REPO / "deleted.txt")
    git(REPO, "rm", "-q", "deleted_staged.txt")
    git(REPO, "rm", "-q", "--cached", "rmcached.txt")  # staged deletion, file still there
    git(REPO, "mv", "renamed_old.txt", "renamed_new.txt")
    if FOLD:                                           # a rename that only changes the case: git sees no change
        os.rename(REPO / "Case.TXT", REPO / "case_tmp")
        os.rename(REPO / "case_tmp", REPO / "case.txt")
    w("dir_changed/b.txt", "changed\n")
    w("dir [x] $y/inner.txt", "changed\n")
    w("dir [x] $y/new.txt")
    w("we[ir]d tracked.txt", "changed\n")
    w("$(touch pwned_marker) tracked.txt", "changed\n")
    rmtree_force(REPO / "dir_deleted")
    os.remove(REPO / "dir_deleted_partial" / "a.txt")
    rmtree_force(REPO / "sub" / "gone_dir")
    rmtree_force(REPO / "sub" / "newdir")
    w("sub/deeper/z.txt", "zz\n")
    for name in ("untracked.txt", "new with spaces.txt", "ignored.log", "build/inner/z.txt", "build/inner/deeper/w.txt",
                 "dir_ignored_mix/__pycache__/x.pyc", "dir_untracked/x.txt", "dir_untracked/deep/y.txt",
                 "sub/untracked_in_sub.txt", "hidden_file.txt", *SPECIAL_UNTRACKED, *CASE_VARIANTS):
        w(name)
    (REPO / "empty_dir").mkdir()
    if IS_WINDOWS:
        subprocess.run(["attrib", "+h", str(REPO / "hidden_file.txt")], check=True, capture_output=True)
    # a nested repository
    nested = REPO / "nested_repo"
    (nested / "sub").mkdir(parents=True)
    git(nested, "init", "-q")
    configure(nested)
    (nested / ".gitignore").write_bytes(b"*.tmp\n")
    (nested / "n1.txt").write_bytes(b"1\n")
    (nested / "n2.txt").write_bytes(b"2\n")
    (nested / "sub" / "s.txt").write_bytes(b"s\n")
    git(nested, "add", "-A")
    git(nested, "commit", "-qm", "n")
    (nested / "n1.txt").write_bytes(b"changed\n")
    (nested / "n3.txt").write_bytes(b"u\n")
    (nested / "n.tmp").write_bytes(b"i\n")
    # a link to a directory: listed, never entered
    if IS_WINDOWS:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(REPO / "link_to_sub"), str(REPO / "sub")], check=True, capture_output=True)
    else:
        os.symlink(REPO / "sub", REPO / "link_to_sub", target_is_directory=True)
    (PLAIN / "p1.txt").write_bytes(b"1\n")
    (PLAIN / "p2.txt").write_bytes(b"22\n")
    (PLAIN / "dirp").mkdir()


def remove_sandbox():
    """deletes the sandbox, but only an empty directory or one this test made (it holds a marker file)"""
    if SANDBOX.exists() and not (SANDBOX / SANDBOX_MARKER).exists() and any(SANDBOX.iterdir()):
        raise RuntimeError("%s exists and is not a gdir test sandbox: not deleting it" % SANDBOX)
    link = REPO / "link_to_sub"
    if is_link(link):
        try:
            os.rmdir(link)
        except OSError:
            os.remove(link)
    rmtree_force(SANDBOX)


def setUpModule():
    if not GIT:
        raise unittest.SkipTest("git not found on the PATH")
    if not BASH:
        raise unittest.SkipTest("bash not found (set GDIR_TEST_BASH)")
    if not SCRIPT.exists():
        raise unittest.SkipTest("%s does not exist" % SCRIPT)
    if SANDBOX.exists():
        remove_sandbox()
    build_sandbox()


def tearDownModule():
    if KEEP:
        print("\nsandbox kept: %s" % SANDBOX)
    elif SANDBOX.exists():
        remove_sandbox()


# ---------------------------------------------------------------------------------------------
# the git oracle: what the listing of a directory must show, worked out from git alone

SEVERITY = {"!": 0, "✓": 1, "?": 2, "+": 3, "M": 4, "D": 5, "U": 6}
TAG_OF_SEVERITY = {v: k for k, v in SEVERITY.items()}


def key(name):
    return name.lower() if FOLD else name


def tag_of(xy):
    x, y = xy[0], xy[1]
    if x == "?":
        return "?"
    if x == "!":
        return "!"
    if "U" in (x, y) or xy in ("AA", "DD"):
        return "U"
    if "D" in (x, y):
        return "D"
    if y != " ":
        return "M"
    return "+"


class Oracle:
    """the states git reports for one repository"""

    def __init__(self, top):
        self.status = {}        # key(path) -> (tag, whole directory?)
        self.spelling = {}      # key(path) -> path as git spells it
        records = git(top, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--no-renames",
                      "--ignored=matching", "--untracked-files=normal").stdout.split(b"\0")
        for record in records:
            if len(record) < 4:
                continue
            path = record[3:].decode("utf-8")
            self.status[key(path.rstrip("/"))] = (tag_of(record[:2].decode()), path.endswith("/"))
            self.spelling[key(path.rstrip("/"))] = path.rstrip("/")
        tracked = [f.decode("utf-8") for f in git(top, "ls-files", "-z").stdout.split(b"\0") if f]
        self.tracked = {key(f) for f in tracked}
        self.tracked_dirs = set()
        for f in self.tracked:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.tracked_dirs.add("/".join(parts[:i]))

    def state(self, rel, is_dir):
        k = key(rel)
        parts = k.split("/")
        for i in range(1, len(parts)):                       # inside an untracked or ignored directory
            rec = self.status.get("/".join(parts[:i]))
            if rec and rec[1]:
                return rec[0]
        rec = self.status.get(k)
        if not is_dir:
            if rec:
                return rec[0]
            return "✓" if k in self.tracked else "?"
        if rec and rec[1]:
            return rec[0]
        tags = {t for p, (t, _) in self.status.items() if p.startswith(k + "/")}
        if k in self.tracked_dirs:
            tags.add("✓")
        if "D" in tags:                                      # a directory that exists is changed, not deleted
            tags.discard("D")
            tags.add("M")
        if not tags:
            return "?"                                       # git knows nothing about it, e.g. an empty directory
        return TAG_OF_SEVERITY[max(SEVERITY[t] for t in tags)]

    def deleted_below(self, rel_dir):
        """(name as git spells it, is a directory) of the deleted entries directly below rel_dir"""
        found = {}
        prefix = key(rel_dir) + "/" if rel_dir else ""
        for p, (tag, whole) in self.status.items():
            if tag != "D" or whole or not p.startswith(prefix):
                continue
            rest = self.spelling[p][len(prefix):]
            name = rest.split("/")[0]
            is_dir = "/" in rest or found.get(key(name), (name, False))[1]
            found[key(name)] = (name, is_dir)
        return list(found.values())


_ORACLES = {}


def oracle_for(top):
    if str(top) not in _ORACLES:
        _ORACLES[str(top)] = Oracle(top)
    return _ORACLES[str(top)]


_TOPS = {}


def repo_top(path):
    if str(path) not in _TOPS:
        r = git(path, "rev-parse", "--show-toplevel", check=False)
        _TOPS[str(path)] = pathlib.Path(r.stdout.decode("utf-8").strip()) if r.returncode == 0 else None
    return _TOPS[str(path)]


def expected_dir(path, show_dot=False, use_git=True):
    """[(tag, name, is_dir, size, when)] the listing of the directory must show, in order; size and
    when are None for a deleted entry. The directory may be gone: only deleted files can be there."""
    path = pathlib.Path(path)
    existing = path
    while not existing.exists():
        existing = existing.parent
    real = existing.resolve()
    tail = path.relative_to(existing).as_posix() if path != existing else ""
    top = repo_top(real) if use_git else None
    oracle = oracle_for(top) if top else None
    rel_dir = ""
    if top:
        rel_dir = os.path.relpath(str(real), str(top)).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        if tail not in ("", "."):
            rel_dir = rel_dir + "/" + tail if rel_dir else tail
    entries = []
    names = set()
    if tail in ("", "."):
        for e in os.scandir(real):
            if not show_dot and e.name.startswith("."):
                continue
            names.add(key(e.name))
            is_dir = e.is_dir()
            st = e.stat(follow_symlinks=False)
            when = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%x %X")
            if oracle is None:
                tag = " "
            elif e.name == ".git":
                tag = "!"                                    # git never reports its own directory
            else:
                tag = oracle.state(rel_dir + "/" + e.name if rel_dir else e.name, is_dir)
            entries.append((tag, e.name, is_dir, None if is_dir else str(st.st_size), when))
    if oracle is not None:
        for name, is_dir in oracle.deleted_below(rel_dir):
            if key(name) not in names:
                entries.append(("D", name, is_dir, None, None))
    entries.sort(key=lambda e: e[1].upper())
    return entries


def expected_block(path, names=None):
    """the entries of one block: the whole listing of a directory (names is None), or the named
    entries of it in the order of a listing"""
    if names is None:
        return expected_dir(path)
    wanted = {key(n) for n in names}
    return [e for e in expected_dir(path, show_dot=True) if key(e[1]) in wanted]


def walk_expected(path, show_dot):
    """DIR /S order: the directory, then every subdirectory (not a link, not .git) in listing order"""
    path = pathlib.Path(path).resolve()
    here = expected_dir(path, show_dot)
    blocks = [(path, here)]
    for tag, name, is_dir, size, when in here:
        child = path / name
        if is_dir and when is not None and name != ".git" and not is_link(child):
            blocks.extend(walk_expected(child, show_dot))
    return blocks


# ---------------------------------------------------------------------------------------------
# reading what gdir prints

ENTRY = re.compile(r"^(.) (.*?) +(<DIR>|-|[0-9.,']+) (.*)$")
HEADER_PREFIXES = ("Directory of ", "Verzeichnis von ")
BRANCH_PREFIX = "Branch "


def header_path(line):
    for prefix in HEADER_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def parse_blocks(out):
    """-> [(header or None, [(tag, when, size, name)])]; the thousands separators of sizes are dropped"""
    blocks = []
    current = None
    for line in out.split("\n"):
        if line == "":
            continue
        if line.startswith(BRANCH_PREFIX):
            continue
        header = header_path(line)
        if header is not None:
            current = (header, [])
            blocks.append(current)
            continue
        if current is None:
            current = (None, [])
            blocks.append(current)
        m = ENTRY.match(line)
        if not m:
            raise ValueError("cannot read this line of the listing: %r" % line)
        current[1].append((m.group(1), m.group(2).strip(), re.sub(r"[.,']", "", m.group(3)), m.group(4)))
    return blocks


def listing_diff(entries, expected):
    """None when the parsed entries are what the oracle expects, else the first difference"""
    if len(entries) != len(expected):
        got = [e[3] for e in entries]
        want = [e[1] for e in expected]
        return "%d entries instead of %d; unexpected=%s missing=%s" % (len(entries), len(expected), sorted(set(got) - set(want)), sorted(set(want) - set(got)))
    for (tag, when, size, name), (e_tag, e_name, e_dir, e_size, e_when) in zip(entries, expected):
        if name != e_name:
            return "%r where %r belongs" % (name, e_name)
        if tag != e_tag:
            return "%s: tag %r instead of %r" % (name, tag, e_tag)
        if e_dir and size != "<DIR>":
            return "%s: size %r for a directory" % (name, size)
        if e_size is None and not e_dir and size != "-":
            return "%s: size %r for a deleted file" % (name, size)
        if e_size is not None and size != e_size:
            return "%s: size %r instead of %r" % (name, size, e_size)
        if e_when is not None and when != e_when:
            return "%s: time %r instead of %r" % (name, when, e_when)
        if e_when is None and when != "-":
            return "%s: time %r for a deleted entry" % (name, when)
    return None


def run_in_terminal(args, cols=80, env=None, cwd=None):
    """runs gdir with a pseudo terminal as its standard output (Linux, WSL, macOS)"""
    import fcntl
    import pty
    import select
    import struct
    import termios
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, cols, 0, 0))
    e = base_env({"TERM": "xterm"})
    e.update(env or {})
    proc = subprocess.Popen([BASH, to_posix(SCRIPT), *args], cwd=str(cwd or REPO), stdin=subprocess.DEVNULL,
                            stdout=slave, stderr=subprocess.PIPE, env=e)
    os.close(slave)
    chunks = []
    deadline = time.time() + 120
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError:                                  # the child closed the terminal
                break
            if not data:
                break
            chunks.append(data)
        elif proc.poll() is not None:
            break
    err = proc.stderr.read().decode("utf-8", "replace").strip()
    proc.stderr.close()
    proc.wait()
    os.close(master)
    return Result(proc.returncode, b"".join(chunks).decode("utf-8", "replace").replace("\r\n", "\n"), err)


# ---------------------------------------------------------------------------------------------
# the tests

DIRECTORIES = [".", "sub", "sub/deeper", "build", "build/inner", "dir_untracked", "dir_untracked/deep",
               "dir_ignored_mix", "dir_ignored_mix/__pycache__", "dir_changed", "dir_deleted_partial",
               "dir_clean", "empty_dir", "nested_repo", "nested_repo/sub", "wt", "link_to_sub", "dir [x] $y"]

# a single quote does not survive the Windows command line on its way into an msys program
QUOTE = [] if IS_WINDOWS else ["it's.txt"]

# label, arguments, blocks [(directory, names or None for the whole directory)], the paths that
# cannot be shown, directory-header lines expected
FILE_CASES = [
    ("files of one directory", ["current.txt", "changed.txt", "untracked.txt", "deleted.txt", "ignored.log"],
     [(".", ["current.txt", "changed.txt", "untracked.txt", "deleted.txt", "ignored.log"])], [], False),
    ("a directory and a file", ["sub", "changed.txt"], [("sub", None), (".", ["changed.txt"])], [], True),
    ("deleted files in directories that are gone", ["dir_deleted/a.txt", "sub/gone_dir/f.txt"],
     [("dir_deleted", ["a.txt"]), ("sub/gone_dir", ["f.txt"])], [], True),
    ("a missing file between existing ones", ["nope.txt", "current.txt"], [(".", ["current.txt"])], ["nope.txt"], False),
    ("dot files named explicitly", ["sub/inner.txt", ".gitignore", ".hidden"],
     [("sub", ["inner.txt"]), (".", [".gitignore", ".hidden"])], [], True),
    ("files of a nested repository", ["nested_repo/n1.txt", "nested_repo/n3.txt", "nested_repo/n.tmp"],
     [("nested_repo", ["n1.txt", "n3.txt", "n.tmp"])], [], False),
    ("files of a linked worktree", ["wt/current.txt", "wt/deleted.txt", "wt/wt_untracked.txt"],
     [("wt", ["current.txt", "deleted.txt", "wt_untracked.txt"])], [], False),
    ("spaces and umlauts", ["name with spaces.txt", "new with spaces.txt", "ünïcode.txt"],
     [(".", ["name with spaces.txt", "new with spaces.txt", "ünïcode.txt"])], [], False),
    ("awkward names", ["we[ir]d.txt", "$dollar.txt", *QUOTE, "we[ir]d tracked.txt", "$(touch pwned_marker) tracked.txt", "dir [x] $y/inner.txt"],
     [(".", ["we[ir]d.txt", "$dollar.txt", *QUOTE, "we[ir]d tracked.txt", "$(touch pwned_marker) tracked.txt"]),
      ("dir [x] $y", ["inner.txt"])], [], True),
    ("the same file spelled three ways", ["current.txt", "./current.txt"] + (["CURRENT.TXT"] if FOLD else []),
     [(".", ["current.txt"])], [], False),
    ("a directory, a file of it, and another file", ["sub/deeper", "sub/deeper/x.txt", "sub/inner.txt"],
     [("sub/deeper", None), ("sub/deeper", ["x.txt"]), ("sub", ["inner.txt"])], [], True),
    ("a gone directory next to one that never existed", ["dir_deleted/a.txt", "nope/b.txt"],
     [("dir_deleted", ["a.txt"])], ["nope/b.txt"], True),
    ("files in ignored and untracked directories", ["build/inner/z.txt", "dir_untracked/deep/y.txt"],
     [("build/inner", ["z.txt"]), ("dir_untracked/deep", ["y.txt"])], [], True),
    ("deleted, renamed and removed from the index", ["renamed_old.txt", "deleted_staged.txt", "rmcached.txt"],
     [(".", ["renamed_old.txt", "deleted_staged.txt", "rmcached.txt"])], [], False),
    ("a file reached through a directory link", ["link_to_sub/inner.txt"], [("link_to_sub", ["inner.txt"])], [], False),
    ("a deleted directory as the path", ["dir_deleted"], [(".", ["dir_deleted"])], [], False),
    ("an empty path", [""], [], [""], False),
    ("two directories", ["sub", "build"], [("sub", None), ("build", None)], [], True),
    ("the same directory spelled several ways", ["sub", "./sub/"] + (["SUB"] if FOLD else []), [("sub", None)], [], False),
]


class GdirShTest(unittest.TestCase):

    # --- the listing of one directory ------------------------------------------------------

    def check_listing(self, args, cwd, listed, show_dot):
        res = gdir("--color=never", *args, cwd=cwd)
        self.assertEqual((res.rc, res.err), (0, ""), res)
        blocks = parse_blocks(res.out)
        entries = blocks[0][1] if blocks else []
        self.assertLessEqual(len(blocks), 1, res.out)
        self.assertIsNone(listing_diff(entries, expected_dir(listed, show_dot)), res.out)

    def test_listing_of_every_directory_matches_git(self):
        for show_dot in (False, True):
            for d in DIRECTORIES:
                with self.subTest(directory=d, all=show_dot):
                    self.check_listing(["-a"] if show_dot else [], REPO / d, REPO / d, show_dot)

    def test_directory_as_argument_matches_git(self):
        for d in DIRECTORIES:
            with self.subTest(directory=d):
                self.check_listing([d], REPO, REPO / d, False)

    def test_branch_is_shown_only_for_the_top_level_block(self):
        branch = git(REPO, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        self.assertEqual([line for line in gdir("--color=never").out.split("\n") if line.startswith(BRANCH_PREFIX)],
                         [BRANCH_PREFIX + branch + ": no upstream"])
        self.assertEqual([line for line in gdir("--color=never", "-r").out.split("\n") if line.startswith(BRANCH_PREFIX)],
                         [BRANCH_PREFIX + branch + ": no upstream"])

    def test_nothing_gets_executed_for_awkward_names(self):
        res = gdir("--color=never", "-r")
        self.assertEqual(res.rc, 0, res)
        names = {e[3] for _, entries in parse_blocks(res.out) for e in entries}
        for name in SPECIAL_UNTRACKED + [n.split("/")[-1] for n in TRACKED_SPECIAL]:
            self.assertIn(name, names)
        self.assertEqual([p.name for p in REPO.iterdir() if p.name.startswith("pwned")], [])

    def test_paths_are_resolved_like_a_shell_would(self):
        deeper = REPO / "sub" / "deeper"
        absolute = to_posix(REPO / "sub")
        spellings = [("..", REPO / "sub"), ("../..", REPO), ("../../sub/", REPO / "sub"), ("./../deeper/..", REPO / "sub"),
                     (absolute, REPO / "sub"), (absolute + "//deeper/", REPO / "sub" / "deeper"), (".", deeper)]
        if IS_WINDOWS:
            spellings += [(str(REPO / "sub"), REPO / "sub"), (str(REPO / "sub").replace("\\", "/"), REPO / "sub")]
        for spelling, target in spellings:
            with self.subTest(path=spelling):
                self.check_listing([spelling], deeper, target, False)

    # --- recursion -------------------------------------------------------------------------

    def check_recursive(self, args, cwd, show_dot):
        res = gdir("--color=never", "-r", *args, cwd=cwd)
        self.assertEqual((res.rc, res.err), (0, ""), res)
        blocks = parse_blocks(res.out)
        expected = walk_expected(cwd, show_dot)
        self.assertEqual([canon(win_header(h)) for h, _ in blocks], [canon(d) for d, _ in expected])
        for (header, entries), (path, wanted) in zip(blocks, expected):
            self.assertIsNone(listing_diff(entries, wanted), header)

    def test_recursive_listings_match_git(self):
        for d in (".", "sub", "nested_repo", "wt", "build", "dir_untracked"):
            with self.subTest(directory=d):
                self.check_recursive([], REPO / d, False)
        with self.subTest(directory=".", all=True):
            self.check_recursive(["-a"], REPO, True)

    def test_recursion_does_not_enter_links_or_dot_git(self):
        res = gdir("--color=never", "-ra")
        headers = [canon(win_header(h)) for h, _ in parse_blocks(res.out)]
        self.assertNotIn(canon(REPO / "link_to_sub"), headers)
        self.assertFalse([h for h in headers if "/.git" in h.replace("\\", "/")])
        self.assertIn(canon(REPO / "sub"), headers)

    # --- file arguments --------------------------------------------------------------------

    def test_file_arguments(self):
        for label, args, blocks, missing, headers in FILE_CASES:
            with self.subTest(label):
                res = gdir("--color=never", *args)
                wanted_errors = ["gdir: cannot access '%s': no such file or directory" % m for m in missing]
                self.assertEqual(res.err.split("\n") if res.err else [], wanted_errors)
                self.assertEqual(res.rc, 2 if missing else 0)
                got = parse_blocks(res.out)
                self.assertEqual(len(got), len(blocks), res.out)
                for (header, entries), (rel, names) in zip(got, blocks):
                    target = REPO / rel
                    self.assertIsNotNone(header, res.out)
                    self.assertEqual(canon(win_header(header)), canon(target))
                    self.assertIsNone(listing_diff(entries, expected_block(target, names)), res.out)

    # --- --wide ----------------------------------------------------------------------------

    def test_wide_output_without_a_terminal_is_one_name_per_line(self):
        res = gdir("--color=never", "-w")
        self.assertEqual((res.rc, res.err), (0, ""), res)
        wanted = ["[%s]" % e[1] if e[2] else e[1] for e in expected_dir(REPO)]
        lines = res.out.split("\n")
        self.assertEqual(lines[0], "")
        self.assertTrue(lines[1].startswith(BRANCH_PREFIX))
        self.assertEqual(canon(win_header(header_path(lines[2]))), canon(REPO))
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4:-1], wanted)

    def test_wide_recursive_output_has_a_block_per_directory(self):
        res = gdir("--color=never", "-wr", cwd=REPO / "sub")
        blocks = []
        for line in res.out.split("\n"):
            header = header_path(line)
            if header is not None:
                blocks.append((header, []))
            elif line and not line.startswith(BRANCH_PREFIX) and blocks:
                blocks[-1][1].append(line)
        expected = walk_expected(REPO / "sub", False)
        self.assertEqual(len(blocks), len(expected), res.out)
        for (header, lines), (path, entries) in zip(blocks, expected):
            self.assertEqual(canon(win_header(header)), canon(path))
            self.assertEqual(lines, ["[%s]" % e[1] if e[2] else e[1] for e in entries])

    @staticmethod
    def wide_layout(names, nrows):
        """the lines DIR /W would print for these names in nrows rows: the cells run down the
        columns, every column as wide as its longest name plus two spaces"""
        count = len(names)
        columns = -(-count // nrows)
        widths = [max(len(n) for n in names[c * nrows:(c + 1) * nrows]) for c in range(columns)]
        lines = []
        for r in range(nrows):
            line = ""
            for c in range(columns):
                i = c * nrows + r
                if i >= count:
                    break
                line += names[i]
                if i + nrows < count:
                    line += " " * (widths[c] - len(names[i]) + 2)
            lines.append(line)
        return lines

    @unittest.skipIf(IS_WINDOWS, "needs a pseudo terminal: run the tests in WSL or Linux")
    def test_wide_columns_fit_the_terminal(self):
        names = ["[%s]" % e[1] if e[2] else e[1] for e in expected_dir(REPO)]
        columns_used = []
        for cols in (40, 80, 132, 200):
            with self.subTest(columns=cols):
                res = run_in_terminal(["--color=never", "-w"], cols=cols)
                self.assertEqual((res.rc, res.err), (0, ""), res)
                lines = res.out.split("\n")[:-1]
                self.assertTrue(all(len(line) <= cols for line in lines), "a line is wider than %d" % cols)
                self.assertEqual(lines, self.wide_layout(names, len(lines)))
                columns_used.append(-(-len(names) // len(lines)))
        self.assertEqual(columns_used, sorted(columns_used), "a wider terminal must not get fewer columns")
        self.assertGreater(columns_used[-1], columns_used[0])

    @unittest.skipIf(IS_WINDOWS, "needs a pseudo terminal: run the tests in WSL or Linux")
    def test_columns_variable_overrides_the_terminal_size(self):
        res = run_in_terminal(["--color=never", "-w"], cols=200, env={"COLUMNS": "50"})
        self.assertTrue(all(len(line) <= 50 for line in res.out.split("\n")), res.out)

    # --- colors ----------------------------------------------------------------------------

    def test_every_state_has_its_color(self):
        res = gdir("--color=always")
        self.assertEqual((res.rc, res.err), (0, ""), res)
        lines = res.out.split("\n")
        expected = {"current.txt": "32", "changed.txt": "33", "staged.txt": "94", "untracked.txt": "97", "deleted.txt": "31;9",
                    "conflict.txt": "1;97;41", "ignored.log": "90", "dir_changed": "33", "dir_untracked": "97", "dir_clean": "32"}
        for name, codes in expected.items():
            with self.subTest(name):
                line = [l for l in lines if l.endswith("\x1b[0m") and re.search(r"\x1b\[[0-9;]+m%s\x1b\[0m$" % re.escape(name), l)]
                self.assertEqual(len(line), 1, res.out)
                self.assertTrue(line[0].endswith("\x1b[%sm%s\x1b[0m" % (codes, name)), line[0])
                self.assertTrue(line[0].startswith("\x1b[%sm" % codes), line[0])

    def test_color_modes(self):
        self.assertNotIn("\x1b", gdir().out, "auto: plain when redirected")
        self.assertNotIn("\x1b", gdir("--color=never").out)
        self.assertIn("\x1b[32m", gdir("--color=always").out)
        self.assertIn("\x1b[32m", gdir("--color").out, "a bare --color means always")
        self.assertNotIn("\x1b", gdir("--color=auto", env={"NO_COLOR": "1"}).out)
        self.assertIn("\x1b", gdir("--color=always", env={"NO_COLOR": "1"}).out, "always wins over NO_COLOR")
        res = gdir("--color=blue")
        self.assertEqual((res.rc, res.out, res.err), (2, "", "gdir: invalid --color value 'blue': use auto, always or never"))

    @unittest.skipIf(IS_WINDOWS, "needs a pseudo terminal: run the tests in WSL or Linux")
    def test_automatic_colors_on_a_terminal(self):
        self.assertIn("\x1b[32m", run_in_terminal(["-a"]).out)
        self.assertNotIn("\x1b", run_in_terminal([], env={"NO_COLOR": "1"}).out)
        self.assertNotIn("\x1b", run_in_terminal([], env={"TERM": "dumb"}).out)
        self.assertNotIn("\x1b", run_in_terminal(["--color=never"]).out)

    def test_legend(self):
        res = gdir("--legend", "--color=never")
        self.assertEqual((res.rc, res.err), (0, ""))
        self.assertEqual([l[:11] for l in res.out.split("\n")[:7]],
                         ["✓ current  ", "M changed  ", "+ staged   ", "? unmanaged", "D deleted  ", "U conflict ", "! ignored  "])
        colored = gdir("--legend", "--color=always").out
        self.assertIn("\x1b[1;97;41mconflict \x1b[0m", colored)
        self.assertIn("\x1b[31;9mdeleted  \x1b[0m", colored)

    # --- options, help, errors ---------------------------------------------------------------

    def test_help(self):
        res = gdir("--help")
        self.assertEqual((res.rc, res.err), (0, ""))
        self.assertTrue(res.out.startswith("gdir - lists a directory like DIR"))
        self.assertLessEqual(max(len(l) for l in res.out.split("\n")), 79)
        for args in (["-h"], ["-rh"], ["--bogus", "--help"], ["-x", "-h"], ["a", "--help", "b"]):
            with self.subTest(args):
                again = gdir(*args)
                self.assertEqual((again.rc, again.out), (res.rc, res.out))
        after_dashes = gdir("--", "--help")
        self.assertEqual(after_dashes.rc, 2)
        self.assertIn("cannot access '--help'", after_dashes.err)

    def test_invalid_options(self):
        for args, message in ((["--bogus"], "gdir: unknown option '--bogus'; try: gdir --help"),
                              (["-rx"], "gdir: unknown option '-x'; try: gdir --help"),
                              (["--install", "a", "b"], "gdir: --install takes one folder, not 2")):
            with self.subTest(args):
                res = gdir(*args, cwd=WORK)
                self.assertEqual((res.rc, res.out, res.err), (2, "", message))

    def test_a_lone_dash_and_a_leading_dash_are_paths(self):
        res = gdir("-")
        self.assertEqual((res.rc, res.err), (2, "gdir: cannot access '-': no such file or directory"))
        folder = WORK / "dashes"
        folder.mkdir()
        (folder / "-dash.txt").write_bytes(b"d\n")
        res = gdir("--color=never", "--", "-dash.txt", cwd=folder, env={"GIT_CEILING_DIRECTORIES": str(WORK)})
        self.assertEqual(res.rc, 0, res)
        self.assertTrue(res.out.rstrip().endswith(" -dash.txt"), res.out)

    def test_short_options_combine(self):
        self.assertEqual(gdir("-ra", "--color=never", cwd=REPO / "sub").out, gdir("--recurse", "--all", "--color=never", cwd=REPO / "sub").out)
        self.assertEqual(gdir("-w", "--color=never").out, gdir("--wide", "--color=never").out)

    def test_runs_directly_through_its_shebang(self):
        res = run([BASH, "-c", 'exec "$@"', "x", to_posix(SCRIPT), "--legend", "--color=never"])
        self.assertEqual(res.rc, 0, res)
        self.assertTrue(res.out.startswith("✓ current"))

    def test_script_has_unix_line_endings(self):
        data = SCRIPT.read_bytes()
        self.assertTrue(data.startswith(b"#!/usr/bin/env bash\n"))
        self.assertNotIn(b"\r", data, "bash does not run a script with CRLF line endings: see .gitattributes")

    # --- without git ---------------------------------------------------------------------------

    def no_git_path(self):
        if IS_WINDOWS:
            return "/usr/bin"                    # git lives in /mingw64/bin
        folder = WORK / "no-git"
        folder.mkdir(exist_ok=True)
        for tool in ("find", "sort", "tr", "stty"):
            link = folder / tool
            if not link.exists():
                os.symlink(shutil.which(tool), link)
        return str(folder)

    def test_without_git_on_the_path_the_listing_is_plain(self):
        res = gdir_with_path(self.no_git_path(), "--color=never")
        self.assertEqual((res.rc, res.err), (0, "gdir: git not found on PATH; showing a plain listing"))
        self.assertIsNone(listing_diff(parse_blocks(res.out)[0][1], expected_dir(REPO, use_git=False)), res.out)

    def test_without_git_the_note_comes_once_with_recursion(self):
        res = gdir_with_path(self.no_git_path(), "--color=never", "-r")
        self.assertEqual((res.rc, res.err), (0, "gdir: git not found on PATH; showing a plain listing"))
        self.assertEqual([canon(win_header(h)) for h, _ in parse_blocks(res.out)],
                         [canon(p) for p, _ in walk_expected(REPO, False)])

    def test_without_git_a_deleted_file_cannot_be_found(self):
        res = gdir_with_path(self.no_git_path(), "--color=never", "current.txt", "dir_deleted/a.txt")
        self.assertEqual(res.rc, 2)
        self.assertIn("cannot access 'dir_deleted/a.txt': no such file or directory", res.err)

    def test_outside_a_repository_the_listing_is_plain(self):
        env = {"GIT_CEILING_DIRECTORIES": str(SANDBOX)}
        res = gdir("--color=never", cwd=PLAIN, env=env)
        self.assertEqual(res.rc, 0, res)
        self.assertIn("not a git repository", res.err)
        self.assertTrue(res.err.endswith("showing a plain listing"), res.err)
        self.assertEqual([(e[0], e[3]) for e in parse_blocks(res.out)[0][1]], [(" ", "dirp"), (" ", "p1.txt"), (" ", "p2.txt")])
        res = gdir("--color=never", "-r", cwd=PLAIN, env=env)
        self.assertEqual(res.err.count("\n"), 0, "one note, however many directories")
        self.assertEqual(len(parse_blocks(res.out)), 2)

    @unittest.skipIf(IS_WINDOWS or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "needs a file system with permissions and a user who is not root")
    def test_unreadable_directories_are_reported_and_skipped(self):
        root = WORK / "lockroot"
        locked = root / "locked"
        (root / "ok").mkdir(parents=True)
        (root / "ok" / "a.txt").write_bytes(b"a\n")
        locked.mkdir()
        (locked / "f.txt").write_bytes(b"f\n")
        os.chmod(locked, 0)
        try:
            env = {"GIT_CEILING_DIRECTORIES": str(SANDBOX)}
            res = gdir("--color=never", "-r", cwd=root, env=env)
            self.assertEqual(res.rc, 2, res)
            self.assertIn("gdir: cannot read '%s': Permission denied" % to_posix(locked), res.err)
            self.assertEqual([canon(win_header(h)) for h, _ in parse_blocks(res.out)], [canon(root), canon(root / "ok")])
            res = gdir("--color=never", to_posix(locked), cwd=root, env=env)
            self.assertEqual(res.rc, 2, res)
            self.assertIn("cannot read", res.err)
            self.assertEqual(res.out, "")
        finally:
            os.chmod(locked, 0o755)

    # --- install -------------------------------------------------------------------------------

    def install(self, home, *folders, env=None, cwd=None):
        self.assertTrue(folders, "never run --install without a folder: its default folder is outside the repository")
        home.mkdir(parents=True, exist_ok=True)
        e = {"HOME": to_posix(home)}
        e.update(env or {})
        return gdir("--install", *folders, cwd=cwd or WORK, env=e)

    def shell_with(self, home, command):
        """runs the command in a new shell that reads the .bashrc of home, from a PATH of system folders
        only: a gdir that is installed on the PATH of the user must not win over the one under test"""
        return run([BASH, "-c", 'export HOME=%s PATH=/usr/bin:/bin; source ~/.bashrc; %s' % (shlex.quote(to_posix(home)), command)])

    def test_install_copies_the_script_and_extends_the_path(self):
        home = WORK / "home-install"
        folder = WORK / "bin one"
        rmtree_force(home)
        quoted = to_posix(folder).replace(" ", "\\ ")             # what printf %q makes of it
        res = self.install(home, to_posix(folder))
        lines = res.out.strip().split("\n")
        self.assertEqual(res.rc, 0, res)
        self.assertEqual(lines[0], "created folder: " + to_posix(folder))
        self.assertEqual(lines[1], "copied: " + to_posix(folder) + "/gdir")
        self.assertEqual(lines[2], "added to %s/.bashrc: export PATH=\"$PATH\":%s" % (to_posix(home), quoted))
        self.assertEqual(lines[3], "Done. New shells can run: gdir --help")
        self.assertEqual((folder / "gdir").read_bytes(), SCRIPT.read_bytes())
        bashrc = (home / ".bashrc").read_text()
        self.assertEqual(bashrc, "\n# added by gdir --install\nexport PATH=\"$PATH\":%s\n" % quoted)
        # a new shell finds it, also with a space in the folder name; the installed copy runs
        found = self.shell_with(home, "command -v gdir")
        self.assertEqual(found.out.strip(), to_posix(folder) + "/gdir")
        self.assertTrue(self.shell_with(home, "gdir --legend --color=never").out.startswith("✓ current"))
        # running it again changes nothing
        again = self.install(home, to_posix(folder))
        self.assertEqual(again.rc, 0, again)
        self.assertIn("up to date: " + to_posix(folder) + "/gdir", again.out)
        self.assertIn("already in %s/.bashrc" % to_posix(home), again.out)
        self.assertEqual((home / ".bashrc").read_text(), bashrc)

    def test_install_leaves_the_bashrc_alone_when_the_folder_is_on_the_path(self):
        home = WORK / "home-onpath"
        folder = WORK / "bin-onpath"
        rmtree_force(home)
        res = self.install(home, to_posix(folder), env={"PATH": to_posix(folder) + ":/usr/bin:/bin"})
        self.assertEqual(res.rc, 0, res)
        self.assertIn("already on the PATH: " + to_posix(folder), res.out)
        self.assertFalse((home / ".bashrc").exists())

    def test_install_folder_spellings(self):
        home = WORK / "home-spellings"
        rmtree_force(home)
        res = self.install(home, "rel/one/../two", cwd=WORK)
        self.assertEqual(res.rc, 0, res)
        self.assertTrue((WORK / "rel" / "two" / "gdir").exists())
        self.assertIn(to_posix(WORK / "rel" / "two"), res.out)
        self.assertNotIn("rel/one", res.out)
        if IS_WINDOWS:
            res = self.install(home, str(WORK / "bin-win"))
            self.assertEqual(res.rc, 0, res)
            self.assertTrue((WORK / "bin-win" / "gdir").exists())
            self.assertIn("copied: " + to_posix(WORK / "bin-win") + "/gdir", res.out)

    def test_install_refuses_bad_folders(self):
        home = WORK / "home-errors"
        (WORK / "a-file").write_text("x")
        res = self.install(home, to_posix(WORK / "a-file"))
        self.assertEqual(res.rc, 2)
        self.assertIn("is a file, not a folder", res.err)
        res = self.install(home, to_posix(WORK) + "/we:ird")
        self.assertEqual(res.rc, 2)
        self.assertIn("must not contain ':'", res.err)
        (WORK / "has-gdir-folder" / "gdir").mkdir(parents=True)
        res = self.install(home, to_posix(WORK / "has-gdir-folder"))
        self.assertEqual(res.rc, 2)
        self.assertIn("is a folder, not a file", res.err)

    @unittest.skipIf(IS_WINDOWS, "the default folder in Git Bash is c:\\tools, outside the repository")
    def test_install_default_folder_is_below_home(self):
        home = WORK / "home-default"
        home.mkdir(parents=True, exist_ok=True)
        res = gdir("--install", cwd=WORK, env={"HOME": str(home)})
        self.assertEqual(res.rc, 0, res)
        self.assertTrue((home / ".local" / "bin" / "gdir").exists())

    # --- the same output as gdir.ps1 --------------------------------------------------------------

    def ps1(self, args, cwd):
        r = subprocess.run([PWSH, "-NoProfile", "-File", str(PS1), *args], cwd=str(cwd), capture_output=True, env=base_env(), timeout=180)
        return Result(r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n"), r.stderr.decode("utf-8", "replace").replace("\r\n", "\n").strip())

    @unittest.skipUnless(PWSH and PS1.exists(), "needs PowerShell 7 and gdir.ps1")
    def test_same_output_as_gdir_ps1(self):
        never, ps_never = ["--color=never"], ["-Color", "never"]
        # label, arguments of gdir, arguments of gdir.ps1, directory, compare as text (else as parsed listings)
        cases = [("-a in " + d, never + ["-a"], ps_never + ["-All"], d, False)
                 for d in (".", "sub", "build", "dir_untracked/deep", "nested_repo", "wt", "empty_dir")]
        cases += [("-ra", never + ["-ra"], ps_never + ["-r", "-All"], ".", False),
                  ("-wa", never + ["-wa"], ps_never + ["-Wide", "-All"], ".", True),
                  ("-rwa", never + ["-rwa"], ps_never + ["-r", "-Wide", "-All"], ".", True),
                  ("colors", ["--color=always", "-ra"], ["-Color", "always", "-r", "-All"], ".", True)]
        cases += [(f[0], never + f[1], ps_never + f[1], ".", False) for f in FILE_CASES
                  if f[0] in ("files of one directory", "a directory and a file", "deleted files in directories that are gone",
                              "a missing file between existing ones", "dot files named explicitly")]

        def with_windows_headers(out):
            return "\n".join(
                "Directory of " + win_header(header) if (header := header_path(l)) is not None else l
                for l in out.split("\n"))

        def without_times(blocks):
            return [(header, [(tag, size, name) for tag, when, size, name in entries]) for header, entries in blocks]

        for label, sh_args, ps_args, d, as_text in cases:
            with self.subTest(label):
                mine = gdir(*sh_args, cwd=REPO / d)
                theirs = self.ps1(ps_args, REPO / d)
                self.assertEqual((mine.rc, mine.err), (theirs.rc, theirs.err))
                if as_text:
                    if label == "colors":
                        mine_blocks = parse_blocks(re.sub(r"\x1b\[[0-9;]*m", "", mine.out))
                        theirs_blocks = parse_blocks(re.sub(r"\x1b\[[0-9;]*m", "", theirs.out))
                        self.assertEqual(
                            without_times([(win_header(h), e) for h, e in mine_blocks]),
                            without_times(theirs_blocks))
                    else:
                        self.assertEqual(with_windows_headers(mine.out), with_windows_headers(theirs.out))
                else:
                    self.assertEqual(
                        without_times([(win_header(h), e) for h, e in parse_blocks(mine.out)]),
                        without_times(parse_blocks(theirs.out)))


if __name__ == "__main__":
    if "--keep" in sys.argv:
        sys.argv.remove("--keep")
        KEEP = True
    unittest.main(verbosity=2)
