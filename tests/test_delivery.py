import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeliveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load(
            (ROOT / ".github/workflows/delivery-pipeline.yml").read_text(),
            Loader=yaml.BaseLoader,
        )

    def test_delivery_is_reusable_and_stages_are_ordered(self):
        self.assertIn("workflow_call", self.workflow["on"])
        jobs = self.workflow["jobs"]
        self.assertEqual(jobs["simulated-integrations"]["needs"], "build")
        self.assertEqual(jobs["dev"]["needs"], "simulated-integrations")
        self.assertEqual(jobs["test"]["needs"], "dev")
        self.assertEqual(jobs["prod"]["needs"], "test")
        for stage in ("dev", "test", "prod"):
            self.assertEqual(jobs[stage]["environment"], stage)
            self.assertTrue(any("sha256sum --check" in step.get("run", "")
                                for step in jobs[stage]["steps"]))

    def test_all_integrations_are_simulated_and_mode_is_required(self):
        job = self.workflow["jobs"]["simulated-integrations"]
        self.assertEqual(set(job["strategy"]["matrix"]["adapter"]), {
            "veracode-sast", "veracode-sca", "sonarqube", "jfrog",
            "test-case-management", "change-request",
        })
        script = job["steps"][0]["run"]
        self.assertIn('test "$DEMO_MODE" = simulation', script)
        self.assertIn("SIMULATION ONLY", script)


if __name__ == "__main__":
    unittest.main()
