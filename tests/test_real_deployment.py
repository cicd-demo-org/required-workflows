import os
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy-container.sh"


class RealDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = pathlib.Path(self.temp.name)
        self.trace = self.directory / "trace"
        self.executable("gh", """#!/bin/bash
echo "gh $*" >> "$TRACE"
if [ "$1" = api ]; then echo "${FAKE_PROTECTED:-true}"; exit 0; fi
if [ "$1" = attestation ]; then exit "${FAKE_ATTEST_STATUS:-0}"; fi
exit 2
""")
        self.executable("curl", """#!/bin/bash
exit "${FAKE_CURL_STATUS:-0}"
""")
        self.executable("sleep", "#!/bin/bash\nexit 0\n")
        self.executable("docker", """#!/bin/bash
echo "$*" >> "$TRACE"
case "$1" in
  login) cat >/dev/null; echo '{}' > "$DOCKER_CONFIG/config.json";;
  pull|stop|start|rename|rm) exit 0;;
  container) printf '%s\\n' "${FAKE_NAMES:-}";;
  inspect) case "$3" in
    *demo.repository*) echo "${FAKE_OWNER:-$GITHUB_REPOSITORY}";;
    *) echo true;;
  esac;;
  run)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --cidfile ]; then printf '%064d\\n' 0 > "$2"; break; fi
      shift
    done;;
  *) exit 2;;
esac
""")
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{self.directory}:{self.env['PATH']}",
            "TRACE": str(self.trace), "GH_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "example/nodejs-demo-app",
            "GITHUB_ACTOR": "reviewer", "DEFAULT_BRANCH": "main",
            "IMAGE_DIGEST": "sha256:" + "a" * 64, "SOURCE_SHA": "b" * 40,
            "ENABLED": "true",
        })

    def executable(self, name, text):
        path = self.directory / name
        path.write_text(text)
        path.chmod(0o755)

    def run_deploy(self, **overrides):
        env = self.env.copy()
        env.update(overrides)
        result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True,
                                text=True, timeout=15, check=False)
        trace = self.trace.read_text() if self.trace.exists() else ""
        return result, trace

    def test_missing_opt_in_or_environment_prevents_docker_access(self):
        for overrides in ({"ENABLED": ""}, {"FAKE_PROTECTED": "false"}):
            with self.subTest(overrides=overrides):
                result, trace = self.run_deploy(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("login ", trace)
                self.assertNotIn("run ", trace)

    def test_bad_digest_rejected_without_registry_or_host_changes(self):
        result, trace = self.run_deploy(IMAGE_DIGEST="sha256:not-a-digest")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, "")

    def test_bad_attestation_cannot_start_container(self):
        result, trace = self.run_deploy(FAKE_ATTEST_STATUS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("run ", trace)
        self.assertNotIn("stop ", trace)

    def test_failed_smoke_restores_existing_container(self):
        result, trace = self.run_deploy(FAKE_NAMES="nodejs-demo-app", FAKE_CURL_STATUS="22")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("rename nodejs-demo-app nodejs-demo-app-previous", trace)
        self.assertIn("rm -f " + "0" * 64, trace)
        self.assertIn("start nodejs-demo-app-previous", trace)
        self.assertIn("rename nodejs-demo-app-previous nodejs-demo-app", trace)

    def test_valid_image_starts_without_an_existing_container(self):
        result, trace = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run -d", trace)
        self.assertNotIn("rm -f", trace)
        self.assertIn("--signer-workflow example/nodejs-demo-app/.github/workflows/publish-image.yml", trace)
        self.assertIn("--source-ref refs/heads/main", trace)
        self.assertIn("--source-digest " + "b" * 40, trace)
        self.assertIn("--deny-self-hosted-runners", trace)

    def test_unrelated_container_is_never_replaced(self):
        result, trace = self.run_deploy(FAKE_NAMES="nodejs-demo-app", FAKE_OWNER="other/repo")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("stop ", trace)
        self.assertNotIn("run ", trace)

    def test_deployment_requires_manual_call_and_environment(self):
        workflow = yaml.load(
            (ROOT / ".github/workflows/real-deployment.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(set(workflow["on"]), {"workflow_call"})
        self.assertEqual(workflow["jobs"]["deploy"]["environment"], "real-prod")
        self.assertEqual(workflow["jobs"]["deploy"]["needs"], "preflight")
        self.assertEqual(workflow["jobs"]["deploy"]["runs-on"]["group"], "demo-real-deploy")


if __name__ == "__main__":
    unittest.main()
