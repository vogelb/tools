#!/usr/bin/env python3
# Tests gupdate and its shared installer with local repositories and mocked PATH persistence.
# This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent
GIT = shutil.which("git.exe" if os.name == "nt" else "git")
SHELLS = [shutil.which(name) for name in
          (("powershell.exe", "pwsh.exe") if os.name == "nt" else ("pwsh",))]
SHELLS = list(dict.fromkeys(shell for shell in SHELLS if shell))


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(GIT and SHELLS, "Needs Git and PowerShell")
class GupdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gupdate-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repos = self.root / "repos"
        self.repos.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.env = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG", "PSModulePath"):
            self.env.pop(key, None)
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
        })
        if os.name == "nt":
            self.env["PSModulePath"] = str(pathlib.Path(os.environ["SystemRoot"]) /
                                          "System32" / "WindowsPowerShell" / "v1.0" / "Modules")

    def git(self, *args):
        result = subprocess.run(
            [GIT, *map(str, args)], env=self.env, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def run_ps(self, shell, *args, cwd=None, env=None):
        return subprocess.run(
            [shell, "-NoProfile", *args], cwd=cwd or self.repos,
            env=env or self.env, capture_output=True, text=True, timeout=60
        )

    def make_remote(self):
        remote = self.root / "remote.git"
        seed = self.root / "seed"
        self.git("init", "--quiet", "--bare", "--initial-branch=main", remote)
        self.git("init", "--quiet", "--initial-branch=main", seed)
        self.git("-C", seed, "commit", "--quiet", "--allow-empty", "-m", "initial")
        self.git("-C", seed, "remote", "add", "origin", remote)
        self.git("-C", seed, "push", "--quiet", "-u", "origin", "main")
        return remote, seed

    def advance(self, seed):
        self.git("-C", seed, "commit", "--quiet", "--allow-empty", "-m", "update")
        self.git("-C", seed, "push", "--quiet")
        return self.git("-C", seed, "rev-parse", "HEAD")

    def test_pulls_continue_after_failure_and_support_git_files(self):
        remote, seed = self.make_remote()
        failed = self.repos / "a-no-upstream"
        clone = self.repos / "b space ! [repo]"
        self.git("init", "--quiet", "--initial-branch=main", failed)
        self.git("clone", "--quiet", "--separate-git-dir", self.root / "metadata", remote, clone)
        # A repository below an ordinary folder must not be updated.
        nested = self.repos / "ordinary" / "nested"
        nested.parent.mkdir()
        self.git("clone", "--quiet", remote, nested)
        original = self.git("-C", nested, "rev-parse", "HEAD")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                expected = self.advance(seed)
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("Pull failed", result.stderr)
                self.assertEqual(self.git("-C", clone, "rev-parse", "HEAD"), expected)
                self.assertEqual(self.git("-C", nested, "rev-parse", "HEAD"), original)

    def test_explicit_repository_list_updates_only_selected_repositories(self):
        remote, seed = self.make_remote()
        first = self.repos / "first repo [x]"
        second = self.root / "outside cwd"
        skipped = self.repos / "not selected"
        self.git("clone", "--quiet", remote, first)
        self.git("clone", "--quiet", "--separate-git-dir", self.root / "metadata", remote, second)
        self.git("clone", "--quiet", remote, skipped)
        original = self.git("-C", skipped, "rev-parse", "HEAD")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                expected = self.advance(seed)
                result = self.run_ps(
                    shell, "-File", str(TOOLS / "gupdate.ps1"), first.name, str(second)
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for repo in (first, second):
                    self.assertEqual(self.git("-C", repo, "rev-parse", "HEAD"), expected)
                self.assertEqual(self.git("-C", skipped, "rev-parse", "HEAD"), original)

    def test_explicit_paths_are_validated_before_force_updates(self):
        remote, seed = self.make_remote()
        tracked = seed / "tracked.txt"
        tracked.write_text("original\n", encoding="ascii")
        self.git("-C", seed, "add", "tracked.txt")
        self.git("-C", seed, "commit", "--quiet", "-m", "tracked")
        self.git("-C", seed, "push", "--quiet")
        repo = self.repos / "selected"
        self.git("clone", "--quiet", remote, repo)
        local = repo / "tracked.txt"
        local.write_text("keep local changes\n", encoding="ascii")
        file = self.repos / "file.txt"
        file.write_text("not a directory\n", encoding="ascii")
        for shell in SHELLS:
            for invalid in ("missing", file.name):
                with self.subTest(shell=shell, invalid=invalid):
                    result = self.run_ps(
                        shell, "-File", str(TOOLS / "gupdate.ps1"), "--force", repo.name, invalid
                    )
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertNotIn("Updating", result.stdout)
                    self.assertTrue(result.stderr)
                    self.assertEqual(local.read_text(encoding="ascii"), "keep local changes\n")

    def test_folder_arguments_expand_children_without_recursing_or_duplicates(self):
        remote, seed = self.make_remote()
        group = self.repos / "group ! [x]"
        group.mkdir()
        child = group / "child"
        nested = group / "ordinary" / "nested"
        nested.parent.mkdir()
        direct = self.repos / "direct"
        skipped = self.repos / "not selected"
        empty = self.repos / "empty"
        empty.mkdir()
        for repo in (child, nested, direct, skipped):
            self.git("clone", "--quiet", remote, repo)
        original = self.git("-C", skipped, "rev-parse", "HEAD")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                expected = self.advance(seed)
                result = self.run_ps(
                    shell, "-File", str(TOOLS / "gupdate.ps1"),
                    group.name, direct.name, str(child), empty.name
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count('Updating "child"'), 1)
                for repo in (child, direct):
                    self.assertEqual(self.git("-C", repo, "rev-parse", "HEAD"), expected)
                for repo in (nested, skipped):
                    self.assertEqual(self.git("-C", repo, "rev-parse", "HEAD"), original)

    @unittest.skipUnless(os.name == "nt", "cmd.exe wrapper is Windows-only")
    def test_cmd_wrapper_success_and_divergence(self):
        remote, seed = self.make_remote()
        clone = self.repos / "repo"
        self.git("clone", "--quiet", remote, clone)
        expected = self.advance(seed)
        result = subprocess.run(
            [os.environ["ComSpec"], "/d", "/c", "call", str(TOOLS / "gupdate.cmd")], cwd=self.repos,
            env=self.env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("-C", clone, "rev-parse", "HEAD"), expected)
        self.git("-C", clone, "commit", "--quiet", "--allow-empty", "-m", "local")
        local = self.git("-C", clone, "rev-parse", "HEAD")
        self.advance(seed)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(self.git("-C", clone, "rev-parse", "HEAD"), local)
        result = subprocess.run(
            [os.environ["ComSpec"], "/d", "/c", "call", str(TOOLS / "gupdate.cmd"), "--force"],
            cwd=self.repos, env=self.env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("discard", result.stdout)
        self.assertEqual(self.git("-C", clone, "rev-parse", "HEAD"), local)

    @unittest.skipUnless(os.name == "nt", "Git batch wrappers are Windows-only")
    def test_batch_git_wrapper_preserves_control_and_exit_codes(self):
        wrappers = self.root / "wrappers"
        wrappers.mkdir()
        # A deterministic wrapper tests invocation through PATH without depending on the DevPack.
        (wrappers / "git.cmd").write_text(
            "@echo off\n"
            "echo wrapper-invoked\n"
            "if \"%~2\"==\"%GUPDATE_FAIL_REPO%\" exit /b 7\n"
            "exit /b 0\n", encoding="ascii"
        )
        failed = self.repos / "a failed"
        success = self.repos / "b success"
        for repo in (failed, success):
            (repo / ".git").mkdir(parents=True)
        env = dict(self.env, PATH=str(wrappers) + os.pathsep + self.env["PATH"],
                   GUPDATE_FAIL_REPO=str(failed))
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"), env=env)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count("wrapper-invoked"), 2)
                self.assertIn('Updating "b success"', result.stdout)
                self.assertIn('Pull failed for "a failed"', result.stderr)

    def test_force_discards_tracked_changes_but_keeps_untracked_files(self):
        remote, seed = self.make_remote()
        tracked = seed / "tracked.txt"
        tracked.write_text("initial\n", encoding="ascii")
        self.git("-C", seed, "add", "tracked.txt")
        self.git("-C", seed, "commit", "--quiet", "-m", "tracked")
        self.git("-C", seed, "push", "--quiet")
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                clone = self.repos / f"repo {index}"
                self.git("clone", "--quiet", remote, clone)
                tracked.write_text(f"remote {index}\n", encoding="ascii")
                self.git("-C", seed, "commit", "--quiet", "-am", "remote edit")
                self.git("-C", seed, "push", "--quiet")
                local = clone / "tracked.txt"
                local.write_text("staged\n", encoding="ascii")
                self.git("-C", clone, "add", "tracked.txt")
                local.write_text("unstaged\n", encoding="ascii")
                untracked = clone / "untracked.txt"
                untracked.write_text("keep\n", encoding="ascii")
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(local.read_text(encoding="ascii"), "unstaged\n")
                flag = "--force" if index == 0 else "-Force"
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"), clone.name, flag)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("discard", result.stdout)
                self.assertLess(result.stdout.index("discard"), result.stdout.index("Updating"))
                self.assertEqual(local.read_text(encoding="ascii"), f"remote {index}\n")
                self.assertEqual(untracked.read_text(encoding="ascii"), "keep\n")
                self.assertEqual(self.git("-C", clone, "diff", "--cached"), "")

    @unittest.skipUnless(os.name == "nt", "Git batch wrapper is Windows-only")
    def test_failed_force_reset_skips_pull_and_continues(self):
        wrappers = self.root / "wrappers"
        wrappers.mkdir()
        (wrappers / "git.cmd").write_text(
            "@echo off\n"
            "echo %~nx2:%~3\n"
            "if \"%~2\"==\"%GUPDATE_FAIL_REPO%\" exit /b 9\n"
            "exit /b 0\n", encoding="ascii"
        )
        failed = self.repos / "a-failed"
        success = self.repos / "b-success"
        for repo in (failed, success):
            (repo / ".git").mkdir(parents=True)
        env = dict(self.env, PATH=str(wrappers) + os.pathsep + self.env["PATH"],
                   GUPDATE_FAIL_REPO=str(failed))
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_ps(
                    shell, "-File", str(TOOLS / "gupdate.ps1"), "--force", env=env
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("a-failed:reset", result.stdout)
                self.assertNotIn("a-failed:pull", result.stdout)
                self.assertIn("b-success:reset", result.stdout)
                self.assertIn("b-success:pull", result.stdout)
                self.assertIn("Reset failed", result.stderr)

    def test_empty_directory_help_invalid_arguments_and_missing_git(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("No Git repositories", result.stdout)
                result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"), str(self.repos))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("No Git repositories", result.stdout)
                for flag in ("--help", "-Help", "/?"):
                    result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"), flag)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("-Install", result.stdout)
                for args in (["unexpected"], ["-Unknown"], ["-Install", "bad" + os.pathsep + "path"],
                             ["-Install", "--force"]):
                    result = self.run_ps(shell, "-File", str(TOOLS / "gupdate.ps1"), *args)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                result = self.run_ps(
                    shell, "-File", str(TOOLS / "gupdate.ps1"),
                    env=dict(self.env, PATH=str(self.root))
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Git is not available", result.stderr)

    @unittest.skipUnless(os.name == "nt", "Registry PATH persistence is Windows-only")
    def test_shared_installer_without_changing_user_environment(self):
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                target = self.root / f"installed {index}"
                # Only PATH persistence and the Windows broadcast are mocked; copying, hashing,
                # validation and session PATH updates use the real implementation.
                command = f"""
$ErrorActionPreference = 'Stop'
. {ps_quote(TOOLS / 'git-tools-install.ps1')}
$script:storedPath = '%USERPROFILE%\\existing'
$script:writes = 0
$script:broadcasts = 0
function Get-UserPath {{ $script:storedPath }}
function Get-MachinePath {{ '' }}
function Set-UserPath([string]$Value) {{
    $script:storedPath = $Value
    $script:writes++
}}
function Send-EnvironmentChange {{ $script:broadcasts++ }}
$target = {ps_quote(target)}
foreach ($name in 'gdir', 'gupdate') {{
    Install-GitTool -Name $name -SourceFolder {ps_quote(TOOLS)} -Target $target
    $scriptFile = Join-Path $target "$name.ps1"
    $before = (Get-Item -LiteralPath $scriptFile).LastWriteTimeUtc
    Install-GitTool -Name $name -SourceFolder {ps_quote(TOOLS)} -Target $target
    if ((Get-Item -LiteralPath $scriptFile).LastWriteTimeUtc -ne $before) {{
        throw 'Idempotent installation rewrote an unchanged script'
    }}
}}
if ($script:writes -ne 1 -or $script:broadcasts -ne 1) {{ throw 'PATH added more than once' }}
if ($script:storedPath -ne ('%USERPROFILE%\\existing;' + $target)) {{
    throw 'Existing PATH variables were not preserved'
}}
if (-not (Test-OnPath $env:Path $target)) {{ throw 'Session PATH not updated' }}
if (-not (Test-OnPath ('"' + $target.ToUpper() + '\\\\"') $target)) {{
    throw 'Equivalent PATH entry not recognized'
}}
$script:storedPath = ''
function Get-MachinePath {{ $target }}
Install-GitTool -Name gupdate -SourceFolder {ps_quote(TOOLS)} -Target $target
if ($script:writes -ne 1) {{ throw 'Machine PATH entry duplicated' }}
$rejected = $false
try {{ Install-GitTool -Name gupdate -SourceFolder $target -Target 'bad%path' }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'Invalid folder was accepted' }}
Remove-Item -LiteralPath (Join-Path $target 'gupdate.cmd')
$rejected = $false
try {{ Install-GitTool -Name gupdate -SourceFolder $target -Target (Join-Path $target 'missing') }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'Missing source was accepted' }}
Install-GitTool -Name gupdate -SourceFolder {ps_quote(TOOLS)} -Target $target
"""
                result = self.run_ps(shell, "-Command", command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ("gdir", "gupdate"):
                    result = self.run_ps(shell, "-File", str(target / f"{name}.ps1"), "--help")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("-Install", result.stdout)


if __name__ == "__main__":
    unittest.main()
