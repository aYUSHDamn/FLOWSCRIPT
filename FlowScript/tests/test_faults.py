import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from main import compile_source, execute
from errors import FlowScriptError, InvariantViolation
from runtime.faults import FaultConfig, FaultRule, FaultType, FaultInjector


def run_with_faults(body: str, fault_config: FaultConfig, opt: bool = True):
    out = []
    injector = FaultInjector(fault_config)
    vm = execute(f"START\n{body}\nEND\n", opt=opt, out=out.append, fault_injector=injector)
    return out, vm


class TestFaultInjection(unittest.TestCase):
    def test_fault_injection_disabled_by_default(self):
        # When fault injection is disabled, behavior is identical to normal execution
        src = ("DEVICE fan TYPE ventilation\n"
               "TURN_ON fan\n"
               "REQUIRE fan.status == ON\n"
               "PRINT \"ok\"")
        cfg = FaultConfig(enabled=False, rules=[
            FaultRule(device="fan", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE)
        ])
        out, vm = run_with_faults(src, cfg)
        self.assertEqual(out, ["fan → ON", "ok"])
        self.assertEqual(vm.devices["fan"], "ON")
        self.assertEqual(len(vm.execution_events), 0)

    def test_action_failure_successful_recovery(self):
        # TURN_ON heater fails at runtime, triggering TRY -> RECOVER
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE backup_heater TYPE heating\n"
               "TRY\n"
               "    TURN_ON heater\n"
               "    ENSURE heater.status == ON\n"
               "RECOVER\n"
               "    TURN_ON backup_heater\n"
               "    ENSURE backup_heater.status == ON\n"
               "END_TRY\n"
               "PRINT \"recovered\"")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="heater", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ])
        out, vm = run_with_faults(src, cfg)
        self.assertEqual(out, ["backup_heater → ON", "recovered"])
        self.assertEqual(vm.devices["heater"], "OFF")  # Never reached ON
        self.assertEqual(vm.devices["backup_heater"], "ON")

        # Verify execution events telemetry
        evts = vm.execution_events
        fault_evts = [e for e in evts if e.event_type == "FAULT"]
        self.assertEqual(len(fault_evts), 1)
        self.assertEqual(fault_evts[0].fault_type, FaultType.ACTION_FAILURE)
        self.assertEqual(fault_evts[0].requested_state, "ON")
        self.assertEqual(fault_evts[0].observed_state, "OFF")

        rec_entries = [e for e in evts if e.event_type == "RECOVERY_ENTERED"]
        self.assertEqual(len(rec_entries), 1)
        self.assertEqual(rec_entries[0].final_outcome, "RECOVERED")

        summary = vm.fault_summary
        self.assertEqual(summary["faults_injected"], 1)
        self.assertEqual(summary["recoveries_triggered"], 1)
        self.assertEqual(summary["recoveries_succeeded"], 1)
        self.assertEqual(summary["unrecovered_faults"], 0)

    def test_state_mismatch_evaluates_against_observed_state(self):
        # Action appears to run, but physical device state remains OFF!
        # Recovery must sense actual observed state, NOT assume success.
        src = ("DEVICE cooler TYPE cooling\n"
               "DEVICE backup_cooler TYPE cooling\n"
               "TRY\n"
               "    TURN_ON cooler\n"
               "    # Contract senses observed state; if mismatch occurred, this fails!\n"
               "    ENSURE cooler.status == ON\n"
               "RECOVER\n"
               "    PRINT \"mismatch detected\"\n"
               "    TURN_ON backup_cooler\n"
               "    ENSURE backup_cooler.status == ON\n"
               "END_TRY")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="cooler", action="TURN_ON", fault_type=FaultType.STATE_MISMATCH, mismatch_state="OFF", trigger_step=1)
        ])
        out, vm = run_with_faults(src, cfg)
        self.assertEqual(out, ["cooler → OFF", "mismatch detected", "backup_cooler → ON"])
        self.assertEqual(vm.devices["cooler"], "OFF")  # Observed state is OFF
        self.assertEqual(vm.devices["backup_cooler"], "ON")

        # Telemetry verification
        fault_evts = [e for e in vm.execution_events if e.event_type == "FAULT"]
        self.assertEqual(len(fault_evts), 1)
        self.assertEqual(fault_evts[0].fault_type, FaultType.STATE_MISMATCH)
        self.assertEqual(fault_evts[0].requested_state, "ON")
        self.assertEqual(fault_evts[0].observed_state, "OFF")

    def test_delayed_completion_simulated_time(self):
        # Delayed completion injects unexpected simulated latency
        src = ("DEVICE pump TYPE cooling\n"
               "WAIT 1\n"
               "TURN_ON pump\n"
               "WAIT 2\n")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="pump", action="TURN_ON", fault_type=FaultType.DELAYED_COMPLETION, delay_seconds=4.5)
        ])
        out, vm = run_with_faults(src, cfg)
        self.assertEqual(out, ["pump → ON"])
        # Expected simulated time: 1 + 4.5 (incurred delay) + 2 = 7.5 seconds
        self.assertAlmostEqual(vm.simulated_time, 7.5, places=2)

        fault_evts = [e for e in vm.execution_events if e.event_type == "FAULT"]
        self.assertEqual(len(fault_evts), 1)
        self.assertEqual(fault_evts[0].fault_type, FaultType.DELAYED_COMPLETION)

    def test_exhausted_retries_and_unhandled_failure(self):
        # TRY fails due to fault, and RECOVER also fails (chained error reporting)
        src = ("DEVICE heater TYPE heating\n"
               "TRY\n"
               "    TURN_ON heater\n"
               "RECOVER\n"
               "    REQUIRE 1 == 0\n"
               "END_TRY")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="heater", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ])
        with self.assertRaises(FlowScriptError) as ctx:
            run_with_faults(src, cfg)
        self.assertIn("Recovery failed", ctx.exception.message)
        self.assertIn("original error in TRY", ctx.exception.message)

    def test_unavailable_fallback_action(self):
        # TRY fails due to fault, but RECOVER attempts an undeclared device in a contract check
        src = ("DEVICE heater TYPE heating\n"
               "TRY\n"
               "    TURN_ON heater\n"
               "RECOVER\n"
               "    REQUIRE undeclared_cooler.status == ON\n"
               "END_TRY")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="heater", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ])
        with self.assertRaises(FlowScriptError) as ctx:
            run_with_faults(src, cfg)
        self.assertEqual(ctx.exception.kind, "Semantic")
        self.assertIn("undeclared_cooler", ctx.exception.message)

    def test_invariant_violation_never_bypassed_by_fault_or_recovery(self):
        # Global INVARIANT: heater and cooler cannot both be ON
        # Even during recovery or after a fault, global invariants must NEVER be violated!
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    # Attempting to turn ON cooler while heater is ON violates invariant!\n"
               "    TURN_ON cooler\n"
               "END_TRY")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="heater", action="TURN_ON", fault_type=FaultType.DELAYED_COMPLETION, delay_seconds=1.0)
        ])
        with self.assertRaises(InvariantViolation) as ctx:
            run_with_faults(src, cfg)
        self.assertIn("INVARIANT contract violated", ctx.exception.message)

    def test_deterministic_reproducibility_with_seed(self):
        # Fixed seed guarantees identical deterministic fault behavior across multiple runs
        src = ("DEVICE d1 TYPE heating\n"
               "DEVICE d2 TYPE cooling\n"
               "TRY\n"
               "    TURN_ON d1\n"
               "RECOVER\n"
               "    TURN_ON d2\n"
               "END_TRY")
        # Rule targeting only d1 with seed
        cfg1 = FaultConfig(enabled=True, rules=[
            FaultRule(device="d1", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ], seed=12345)
        out1, vm1 = run_with_faults(src, cfg1)

        cfg2 = FaultConfig(enabled=True, rules=[
            FaultRule(device="d1", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ], seed=12345)
        out2, vm2 = run_with_faults(src, cfg2)

        self.assertEqual(out1, out2)
        self.assertEqual(out1, ["d2 → ON"])
        self.assertEqual([e.to_dict() for e in vm1.execution_events], [e.to_dict() for e in vm2.execution_events])
        self.assertEqual(vm1.fault_summary, vm2.fault_summary)

    def test_optimized_and_unoptimized_equivalence_under_faults(self):
        # Optimized and unoptimized execution produce identical device states and output under faults
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE backup TYPE heating\n"
               "TRY\n"
               "    TURN_ON heater\n"
               "    ENSURE heater.status == ON\n"
               "RECOVER\n"
               "    TURN_ON backup\n"
               "    ENSURE backup.status == ON\n"
               "END_TRY\n"
               "PRINT \"done\"")
        cfg = FaultConfig(enabled=True, rules=[
            FaultRule(device="heater", action="TURN_ON", fault_type=FaultType.ACTION_FAILURE, trigger_step=1)
        ])
        out_opt, vm_opt = run_with_faults(src, cfg, opt=True)
        out_no_opt, vm_no_opt = run_with_faults(src, cfg, opt=False)

        self.assertEqual(out_opt, out_no_opt)
        self.assertEqual(vm_opt.devices, vm_no_opt.devices)
        self.assertEqual(vm_opt.fault_summary, vm_no_opt.fault_summary)
        self.assertEqual(
            [e.event_type for e in vm_opt.execution_events],
            [e.event_type for e in vm_no_opt.execution_events]
        )


if __name__ == "__main__":
    unittest.main()
