import dataclasses
import unittest

from krx_research.policies import DEFAULT_ENGINEERING_POLICY


class EngineeringPolicyTests(unittest.TestCase):
    def test_all_required_principle_areas_are_objectified(self):
        expected = {
            "ARCH-1", "ARCH-2", "LEAN-1", "DATA-1", "SEC-1", "DB-1", "RUN-1",
            "UI-1", "CHART-1", "CLOUD-1", "DELETE-1", "TEST-1", "GIT-1",
        }
        self.assertEqual({item.code for item in DEFAULT_ENGINEERING_POLICY.principles}, expected)

    def test_policy_is_immutable_and_rejects_unknown_principles(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            DEFAULT_ENGINEERING_POLICY.principles = ()
        with self.assertRaises(KeyError):
            DEFAULT_ENGINEERING_POLICY.require("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
