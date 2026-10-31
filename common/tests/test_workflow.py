import unittest
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build.yml"


class BuildWorkflowTests(unittest.TestCase):
    def test_build_workflow_is_valid_yaml_and_has_expected_jobs(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))

        self.assertIn("push", triggers)
        self.assertIn("pull_request", triggers)
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual({"plan", "build", "publish", "pages"}, set(workflow["jobs"]))
        self.assertEqual("true", workflow["jobs"]["build"]["if"].split("==")[-1].strip().strip("'"))
        self.assertEqual("write", workflow["jobs"]["publish"]["permissions"]["contents"])

    def test_discovery_workflow_has_weekly_schedule_and_pr_permissions(self):
        path = WORKFLOW.with_name("discover.yml")
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))

        self.assertIn("schedule", triggers)
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual("write", workflow["permissions"]["contents"])
        self.assertEqual("write", workflow["permissions"]["pull-requests"])


if __name__ == "__main__":
    unittest.main()