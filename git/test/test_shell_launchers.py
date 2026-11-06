#!/usr/bin/env python3
# Tests the Linux launchers and their configurable installation without changing the real HOME.
# This file was created with the help of AI — model: GPT-6.1 Sol (model ID: gpt-6.1-sol)

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")
GIT = shutil.which("git")


@unittest.skipUnless(os.name == "posix" and BASH, "Needs Linux and bash")
class ShellLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="launchers-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.launchers = self.root / "tools with spaces"
        self.launchers.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("gdir", "gupdate"):
            shutil.copyfile(TOOLS / name, self.launchers / name)
            (self.launchers / f"{name}.ps1").write_text("# companion\n")
        self.env = dict(os.environ, PATH=str(self.bin))

    def stub(self, name, content="exit 0\n"):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + content)
        path.chmod(0o755)
        return path

    def run_launcher(self, name, *args, env=None, source=None):
        return subprocess.run(
            [BASH, str((source or self.launchers) / name), *map(str, args)],
            cwd=self.root, env=env or self.env, capture_output=True, timeout=60
        )

    def test_dependency_checks(self):
        for name in ("gdir", "gupdate"):
            with self.subTest(name=name):
                result = self.run_launcher(name)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b'"pwsh" is missing', result.stderr)
                self.stub("pwsh")
                result = self.run_launcher(name)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b'"git" is missing', result.stderr)
                (self.bin / "pwsh").unlink()

    def test_missing_companion_script(self):
        self.stub("pwsh")
        self.stub("git")
        for name in ("gdir", "gupdate"):
            (self.launchers / f"{name}.ps1").unlink()
            result = self.run_launcher(name)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"{name}.ps1 is missing".encode(), result.stderr)

    def test_argument_boundaries_working_directory_and_exit_code(self):
        self.stub("pwsh", 'printf "%s\\0" "$PWD" "$@"\nexit 17\n')
        self.stub("git")
        cases = [
            ("gdir", ["-ra", "--color=never", "a space", "it's.txt", "$(touch injected)"],
             ["-Recurse", "-All", "-Color", "never", "a space", "it's.txt", "$(touch injected)"]),
            ("gdir", ["--", "-leading"], ["./-leading"]),
            ("gdir", ["--install", "custom bin"], ["-Install", "custom bin"]),
            ("gupdate", ["--force"], ["--force"]),
            ("gupdate", ["--install", "custom bin"], ["-Install", "custom bin"]),
        ]
        for name, args, expected in cases:
            with self.subTest(name=name, args=args):
                result = self.run_launcher(name, *args)
                self.assertEqual(result.returncode, 17)
                fields = result.stdout.decode().split("\0")[:-1]
                self.assertEqual(fields, [
                    str(self.root), "-NoLogo", "-NoProfile", "-File",
                    str(self.launchers / f"{name}.ps1"), *expected,
                ])
                self.assertFalse((self.root / "injected").exists())

    @unittest.skipUnless(PWSH and GIT, "Needs PowerShell 7 and Git")
    def test_install_configurable_folder_and_default(self):
        home = self.root / "home"
        home.mkdir()
        clean_path = os.pathsep.join(dict.fromkeys(
            str(pathlib.Path(tool).parent) for tool in (PWSH, GIT, BASH)
        ))
        env = dict(os.environ, HOME=str(home), PATH=clean_path)
        custom = self.root / "custom bin with ' quote"
        for name in ("gdir", "gupdate"):
            with self.subTest(name=name):
                folder = custom if name == "gdir" else home / ".local" / "bin"
                args = ["--install", str(custom)] if name == "gdir" else ["--install"]
                result = self.run_launcher(name, *args, env=env, source=TOOLS)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                for file in (name, f"{name}.ps1", "git-tools-install.ps1"):
                    self.assertEqual((folder / file).read_bytes(), (TOOLS / file).read_bytes())
                self.assertTrue(os.access(folder / name, os.X_OK))
                bashrc = (home / ".bashrc").read_bytes()
                before = (folder / f"{name}.ps1").stat().st_mtime_ns
                result = self.run_launcher(name, *args, env=env, source=TOOLS)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual((home / ".bashrc").read_bytes(), bashrc)
                self.assertEqual((folder / f"{name}.ps1").stat().st_mtime_ns, before)
                result = subprocess.run(
                    [BASH, "-c", f'source "$HOME/.bashrc"; command -v {name}; {name} --help'],
                    cwd=self.root, env=env, capture_output=True, timeout=60
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn(str(folder / name).encode(), result.stdout)
                self.assertIn(b"-Install", result.stdout)

    @unittest.skipUnless(PWSH and GIT, "Needs PowerShell 7 and Git")
    def test_gdir_linux_case_sensitive_names(self):
        repo = self.root / "repo"
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        subprocess.run([GIT, "init", "--quiet", str(repo)], check=True, env=env)
        (repo / "Upper.txt").write_text("tracked\n")
        (repo / "upper.txt").write_text("untracked\n")
        if (repo / "Upper.txt").samefile(repo / "upper.txt"):
            self.skipTest("Needs a case-sensitive filesystem")
        subprocess.run([GIT, "-C", str(repo), "add", "Upper.txt"], check=True, env=env)
        result = self.run_launcher(
            "gdir", "--color=never", repo / "Upper.txt", repo / "upper.txt",
            env=env, source=TOOLS
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        lines = result.stdout.decode().splitlines()
        self.assertTrue(any(line.startswith("+ ") and line.endswith("Upper.txt") for line in lines))
        self.assertTrue(any(line.startswith("? ") and line.endswith("upper.txt") for line in lines))

    def test_launchers_have_unix_line_endings(self):
        for name in ("gdir", "gupdate"):
            data = (TOOLS / name).read_bytes()
            self.assertTrue(data.startswith(b"#!/usr/bin/env bash\n"))
            self.assertNotIn(b"\r", data)


if __name__ == "__main__":
    unittest.main()
