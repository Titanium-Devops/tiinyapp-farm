import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from farm.farm import Farm, main


class DeviceImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "farm"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def invoke(self, args, stdin=""):
        output, errors = io.StringIO(), io.StringIO()
        with patch("farm.farm.Farm", return_value=Farm(self.home)), \
                patch("sys.stdin", io.StringIO(stdin)), \
                patch("getpass.getpass", side_effect=AssertionError("Unexpected prompt")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = main(["device", *args])
        return result, output.getvalue(), errors.getvalue()

    def settings(self):
        config = self.home / "device.json"
        if os.name != "nt":
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        return json.loads(config.read_text())

    def test_key_pipe_and_base_argument(self):
        result, output, errors = self.invoke(
            ["--base", "http://localhost:8800/v1", "--key-stdin"], "private-key\n")
        self.assertEqual(result, 0, errors)
        self.assertEqual(self.settings(), {"base": "http://localhost:8800/v1", "key": "private-key"})
        self.assertNotIn("private-key", output + errors)

    def test_environment_import_persists_after_environment_disappears(self):
        with patch.dict(os.environ, TIINY_BASE="https://device.test/v1", TIINY_KEY="env-secret"):
            result, _, errors = self.invoke([])
        self.assertEqual(result, 0, errors)
        self.assertEqual(self.settings(), {"base": "https://device.test/v1", "key": "env-secret"})

    def test_explicit_values_override_environment(self):
        with patch.dict(os.environ, TIINY_BASE="https://old.test", TIINY_KEY="old-key"):
            result, _, errors = self.invoke(["--base", "http://new.test", "--key-stdin"], "new-key\n")
        self.assertEqual(result, 0, errors)
        self.assertEqual(self.settings(), {"base": "http://new.test", "key": "new-key"})

    def test_scripted_missing_or_invalid_values_do_not_prompt_or_save(self):
        for args, stdin in [(["--base", "http://device.test"], ""),
                            (["--key-stdin"], "secret\n"),
                            (["--base", "http://device.test", "--key-stdin"], "\n"),
                            (["--base", "http://user:pass@device.test", "--key-stdin"], "secret\n")]:
            with self.subTest(args=args):
                result, output, errors = self.invoke(args, stdin)
                self.assertEqual(result, 1)
                self.assertNotIn("secret", output + errors)
                self.assertFalse((self.home / "device.json").exists())

    def test_default_remains_interactive(self):
        with patch("getpass.getpass", side_effect=["http://device.test", "interactive-key"]) as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            Farm(self.home).device()
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(self.settings()["key"], "interactive-key")

    def test_real_cli_accepts_pipe_without_terminal(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            "import sys\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
            "from farm.farm import Farm, main\n"
            "instance = Farm(Path(sys.argv.pop(1)))\n"
            "with patch('farm.farm.Farm', return_value=instance):\n"
            "    sys.exit(main())\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.home), "device", "--base", "http://device.test", "--key-stdin"],
            input="pipe-secret\n", capture_output=True, text=True,
            cwd=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("GetPassWarning", result.stderr)
        self.assertEqual(self.settings()["key"], "pipe-secret")
