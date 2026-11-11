#!/usr/bin/env python3
# Regression tests for Git subprocess input on Windows PowerShell and PowerShell 7.
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
SHELLS = list(dict.fromkeys(filter(None, (
    shutil.which(name) for name in
    (("powershell.exe", "pwsh.exe") if os.name == "nt" else ("pwsh",))
))))


@unittest.skipUnless(GIT and SHELLS, "Needs Git and PowerShell")
class GitignoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gitignore-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        home = self.root / "home"
        home.mkdir()
        self.env = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG", "PSModulePath"):
            self.env.pop(key, None)
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(home),
        })
        if os.name == "nt":
            self.env["PSModulePath"] = str(pathlib.Path(os.environ["SystemRoot"]) /
                                          "System32" / "WindowsPowerShell" / "v1.0" / "Modules")

    def git(self, repo, *args):
        result = subprocess.run(
            [GIT, "-C", str(repo), *args], env=self.env, capture_output=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result.stdout

    def make_repo(self, index):
        repo = self.root / f"repo with spaces {index}"
        repo.mkdir()
        self.git(repo, "init", "--quiet")
        return repo

    def run_tool(self, shell, cwd, *patterns, ignore_file=None):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        command = (
            "[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); & " +
            " ".join(quote(arg) for arg in (TOOLS / "gitignore.ps1", *patterns))
        )
        if ignore_file is not None:
            command += " -IgnoreFile " + quote(ignore_file)
        return subprocess.run(
            [shell, "-NoProfile", "-Command", command], cwd=cwd, env=self.env,
            capture_output=True, text=True, encoding="utf-8", timeout=60
        )

    def test_literal_pattern_from_subdirectory_and_duplicate(self):
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                repo = self.make_repo(index)
                sub = repo / "sub"
                sub.mkdir()
                for _ in range(2):
                    result = self.run_tool(shell, sub, "Hello")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Already present: Hello", result.stdout)
                self.assertEqual((repo / ".gitignore").read_text(encoding="utf-8"), "Hello\n")
                self.assertFalse((sub / ".gitignore").exists())

    def test_utf8_nul_delimited_paths_are_untracked_without_deleting_files(self):
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                repo = self.make_repo(index)
                names = ["caf\u00e9 [x].log", "\u65e5\u672c space.log", "keep.txt"]
                for name in names:
                    (repo / name).write_bytes(b"keep working contents\n")
                self.git(repo, "add", "--", *names)
                result = self.run_tool(shell, repo, "*.log")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.git(repo, "ls-files", "-z"), b"keep.txt\0")
                self.assertEqual((repo / ".gitignore").read_text(encoding="utf-8"), "*.log\n")
                for name in names:
                    self.assertEqual((repo / name).read_bytes(), b"keep working contents\n")
                for name in names[:2]:
                    self.assertIn("Removed from index: " + name, result.stdout)
                self.assertEqual(list(repo.glob(".gitignore-*.tmp")), [])

    def test_windows_file_path_is_normalized_before_duplicate_check_and_matching(self):
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                repo = self.make_repo(index)
                sub = repo / "subfolder" / "nested space"
                sub.mkdir(parents=True)
                file = sub / "Hello"
                file.write_bytes(b"keep working contents\n")
                self.git(repo, "add", "--", "subfolder/nested space/Hello")
                ignore = repo / ".gitignore"
                ignore.write_text("subfolder/nested space/Hello\n", encoding="utf-8")
                result = self.run_tool(shell, sub, r"subfolder\nested space\Hello")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Already present: subfolder/nested space/Hello", result.stdout)
                self.assertIn("Removed from index: subfolder/nested space/Hello", result.stdout)
                self.assertEqual(ignore.read_text(encoding="utf-8"), "subfolder/nested space/Hello\n")
                self.assertEqual(self.git(repo, "ls-files", "-z"), b"")
                self.assertEqual(file.read_bytes(), b"keep working contents\n")

    def test_windows_wildcards_and_directory_paths_use_selected_ignore_file_scope(self):
        for index, shell in enumerate(SHELLS):
            with self.subTest(shell=shell):
                repo = self.make_repo(index)
                names = ["selected/logs/one.log", "selected/cache/item.bin", "logs/outside.log"]
                for name in names:
                    file = repo / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"keep working contents\n")
                self.git(repo, "add", "--", *names)
                ignore = repo / "selected" / ".gitignore"
                result = self.run_tool(
                    shell, repo, r"logs\*.log", "cache\\", "logs/*.log", ignore_file=ignore
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(ignore.read_text(encoding="utf-8"), "logs/*.log\ncache/\n")
                self.assertIn("Already present: logs/*.log", result.stdout)
                self.assertEqual(self.git(repo, "ls-files", "-z"), b"logs/outside.log\0")
                for name in names:
                    self.assertEqual((repo / name).read_bytes(), b"keep working contents\n")
                self.assertFalse((repo / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()
