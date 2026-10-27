import json
import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from benchmarks.run_benchmarks import (
    run_no_recovery_trial, run_fixed_retry_trial, run_synthesized_recovery_trial,
    run_scalability_benchmark
)


class TestBenchmarkSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg_path = os.path.join(ROOT_DIR, "benchmarks", "benchmark_config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cls.config = json.load(f)

    def test_benchmark_config_schema(self):
        self.assertIn("comparison_methods", self.config)
        self.assertIn("scenarios", self.config)
        self.assertIn("metrics", self.config)
        scen_ids = [s["id"] for s in self.config["scenarios"]]
        for req in ("S1_transient", "S2_persistent_backup", "S3_state_mismatch", "S4_multi_device_inv", "S5_fail_closed", "S6_scalability", "S7_probabilistic"):
            self.assertIn(req, scen_ids)

    def test_s1_transient_fault_comparison(self):
        s1 = next(s for s in self.config["scenarios"] if s["id"] == "S1_transient")
        rec_no = run_no_recovery_trial(s1, trial_idx=0, seed=None, opt=True)
        rec_retry = run_fixed_retry_trial(s1, trial_idx=0, seed=None, opt=True, max_retries=3)
        rec_synth = run_synthesized_recovery_trial(s1, trial_idx=0, seed=None, opt=True)

        self.assertFalse(rec_no.task_success)
        self.assertTrue(rec_retry.task_success)
        self.assertTrue(rec_synth.task_success)
        self.assertEqual(rec_synth.invariant_violations, 0)

    def test_s2_persistent_fault_backup_recovery(self):
        s2 = next(s for s in self.config["scenarios"] if s["id"] == "S2_persistent_backup")
        rec_no = run_no_recovery_trial(s2, trial_idx=0, seed=None, opt=True)
        rec_retry = run_fixed_retry_trial(s2, trial_idx=0, seed=None, opt=True, max_retries=3)
        rec_synth = run_synthesized_recovery_trial(s2, trial_idx=0, seed=None, opt=True)

        self.assertFalse(rec_no.task_success)
        self.assertFalse(rec_retry.task_success)
        self.assertTrue(rec_retry.budget_exhausted)
        self.assertTrue(rec_synth.task_success)
        self.assertTrue(rec_synth.recovery_success)
        self.assertEqual(rec_synth.invariant_violations, 0)

    def test_s4_multi_device_invariant_coordination(self):
        s4 = next(s for s in self.config["scenarios"] if s["id"] == "S4_multi_device_inv")
        rec_synth = run_synthesized_recovery_trial(s4, trial_idx=0, seed=None, opt=True)

        self.assertTrue(rec_synth.task_success)
        self.assertEqual(rec_synth.invariant_violations, 0)
        self.assertEqual(rec_synth.plan_length, 2)  # TURN_OFF heater, TURN_ON backup_cooler

    def test_s5_fail_closed_guarantee(self):
        s5 = next(s for s in self.config["scenarios"] if s["id"] == "S5_fail_closed")
        rec_synth = run_synthesized_recovery_trial(s5, trial_idx=0, seed=None, opt=True)

        self.assertFalse(rec_synth.task_success)
        self.assertEqual(rec_synth.invariant_violations, 0)
        self.assertTrue(rec_synth.budget_exhausted)

    def test_scalability_execution(self):
        # Smoke test scalability on D in {2, 4}
        scale = run_scalability_benchmark()
        self.assertEqual(len(scale), 20)  # 4 device counts x 5 budgets
        for row in scale:
            self.assertGreater(row["state_space_size"], 0)
            self.assertGreaterEqual(row["synthesis_time_ms_mean"], 0.0)


if __name__ == "__main__":
    unittest.main()
