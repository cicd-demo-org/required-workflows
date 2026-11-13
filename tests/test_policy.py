import os
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PolicyScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.load(
            (ROOT / ".github/workflows/organization-policy.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        cls.scan = next(step["run"] for step in workflow["jobs"]["secret-scan"]["steps"]
                        if step.get("id") == "scan")

    def run_scan(self, repo, env=None):
        output = repo / "output"
        variables = os.environ.copy()
        variables["GITHUB_OUTPUT"] = str(output)
        if env:
            variables.update(env)
        result = subprocess.run(["bash", "-c", self.scan], cwd=repo, env=variables,
                                capture_output=True, text=True, check=False)
        return result, output.read_text() if output.exists() else ""

    def test_findings_record_paths_without_printing_key_material(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            header = "-----BEGIN " + "PRIVATE KEY-----"
            (repo / "fixture.txt").write_text(header + "\n")
            subprocess.run(["git", "-C", str(repo), "add", "fixture.txt"], check=True)
            result, output = self.run_scan(repo)
            self.assertEqual(result.returncode, 0)
            self.assertIn("found=true", output)
            self.assertIn("fixture.txt", result.stdout)
            self.assertNotIn(header, result.stdout)

    def test_git_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            fake = repo / "git"
            fake.write_text("#!/bin/sh\nexit 2\n")
            fake.chmod(0o755)
            result, output = self.run_scan(repo, {"PATH": f"{repo}:{os.environ['PATH']}"})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("found=false", output)

    def test_listing_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = pathlib.Path(directory)
            fake = repo / "git"
            fake.write_text("#!/bin/sh\n[ \"$1\" = grep ] && exit 1\nexit 2\n")
            fake.chmod(0o755)
            result, output = self.run_scan(repo, {"PATH": f"{repo}:{os.environ['PATH']}"})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("found=false", output)


if __name__ == "__main__":
    unittest.main()
