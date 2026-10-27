"""FlowScript Deterministic Fault Injection & Runtime Monitoring Engine.

Provides reproducible, configurable fault simulation for device actuations:
1. Action Failure: Actuation fails to execute and raises a runtime fault.
2. State Mismatch: Requested state differs from the physically observed device state.
3. Delayed Completion: Actuation completes but incurs an unexpected simulated delay.

Supports both explicit step-based fault schedules and pseudo-random deterministic
fault generation using a fixed seed.
"""

from dataclasses import dataclass, field
import random
from typing import List, Dict, Optional, Any


class FaultType:
    ACTION_FAILURE = "action_failure"
    STATE_MISMATCH = "state_mismatch"
    DELAYED_COMPLETION = "delayed_completion"
    ALL = (ACTION_FAILURE, STATE_MISMATCH, DELAYED_COMPLETION)


@dataclass
class FaultRule:
    """A deterministic fault injection rule targeting a device actuation."""
    device: str                                # Device identifier or "*" for any device
    action: Optional[str] = None               # "TURN_ON", "TURN_OFF", or None for any
    fault_type: str = FaultType.ACTION_FAILURE # One of FaultType
    trigger_step: Optional[int] = None         # 1-indexed occurrence count for this device/action
    delay_seconds: float = 0.0                 # Incurred simulated delay for DELAYED_COMPLETION
    mismatch_state: str = "OFF"                # Observed state for STATE_MISMATCH (e.g. "OFF" or "ERROR")
    error_message: Optional[str] = None        # Custom error message for ACTION_FAILURE

    def matches(self, device: str, action: str, count: int) -> bool:
        """Check if this rule matches the current device action and occurrence step."""
        if self.device != "*" and self.device != device:
            return False
        if self.action is not None and self.action != action:
            return False
        if self.trigger_step is not None and self.trigger_step != count:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "action": self.action,
            "fault_type": self.fault_type,
            "trigger_step": self.trigger_step,
            "delay_seconds": self.delay_seconds,
            "mismatch_state": self.mismatch_state,
            "error_message": self.error_message
        }


@dataclass
class ExecutionEvent:
    """Structured record of an actuation, sensing event, fault, or recovery decision."""
    step: int
    simulated_time: float
    event_type: str              # "ACTUATION", "FAULT", "RECOVERY_ENTERED", "RECOVERY_COMPLETED", "INVARIANT_CHECK"
    device: Optional[str] = None
    action: Optional[str] = None
    requested_state: Optional[str] = None
    observed_state: Optional[str] = None
    fault_type: Optional[str] = None
    recovery_decision: Optional[str] = None
    final_outcome: str = "SUCCESS"  # "SUCCESS", "FAULT_INJECTED", "RECOVERED", "FAILED", "VIOLATION"
    details: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "simulated_time": round(self.simulated_time, 3),
            "event_type": self.event_type,
            "device": self.device,
            "action": self.action,
            "requested_state": self.requested_state,
            "observed_state": self.observed_state,
            "fault_type": self.fault_type,
            "recovery_decision": self.recovery_decision,
            "final_outcome": self.final_outcome,
            "details": self.details,
            "line": self.line
        }


@dataclass
class FaultConfig:
    """Configuration container for fault injection."""
    enabled: bool = False
    rules: List[FaultRule] = field(default_factory=list)
    seed: Optional[int] = None
    random_fault_rate: float = 0.0  # 0.0 to 1.0 probability if seed is set and no rules match

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "FaultConfig":
        if not data:
            return cls(enabled=False)
        rules = []
        for r in data.get("rules", []):
            rules.append(FaultRule(
                device=r.get("device", "*"),
                action=r.get("action"),
                fault_type=r.get("fault_type", FaultType.ACTION_FAILURE),
                trigger_step=r.get("trigger_step"),
                delay_seconds=float(r.get("delay_seconds", 0.0)),
                mismatch_state=r.get("mismatch_state", "OFF"),
                error_message=r.get("error_message")
            ))
        return cls(
            enabled=bool(data.get("enabled", False)),
            rules=rules,
            seed=data.get("seed"),
            random_fault_rate=float(data.get("random_fault_rate", 0.0))
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "rules": [r.to_dict() for r in self.rules],
            "seed": self.seed,
            "random_fault_rate": self.random_fault_rate
        }


class FaultInjector:
    """Deterministic fault injector and runtime event monitor."""

    def __init__(self, config: Optional[FaultConfig] = None):
        self.config = config or FaultConfig(enabled=False)
        self.action_counts: Dict[str, int] = {}
        self.events: List[ExecutionEvent] = []
        self.step_counter: int = 0
        self.faults_injected: int = 0
        self.recoveries_triggered: int = 0
        self.recoveries_succeeded: int = 0
        self.rng: Optional[random.Random] = None
        if self.config.seed is not None:
            self.rng = random.Random(self.config.seed)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def record_event(self, event: ExecutionEvent):
        self.events.append(event)

    def evaluate_actuation(
        self,
        device: str,
        action: str,
        current_state: str,
        line: int,
        simulated_time: float
    ) -> Dict[str, Any]:
        """Evaluate whether a fault should be injected for this device actuation.

        Returns a dictionary with:
            - "fault": Optional[FaultRule]
            - "requested_state": "ON" or "OFF"
            - "effective_state": state the device actually ends up in
            - "delay_seconds": added simulated delay
            - "error_message": string if an action failure should raise an error
        """
        self.step_counter += 1
        key = f"{device}:{action}"
        self.action_counts[key] = self.action_counts.get(key, 0) + 1
        count = self.action_counts[key]
        requested_state = "ON" if action == "TURN_ON" else "OFF"

        if not self.config.enabled:
            # Normal execution
            evt = ExecutionEvent(
                step=self.step_counter,
                simulated_time=simulated_time,
                event_type="ACTUATION",
                device=device,
                action=action,
                requested_state=requested_state,
                observed_state=requested_state,
                final_outcome="SUCCESS",
                details=f"Normal actuation to {requested_state}",
                line=line
            )
            self.record_event(evt)
            return {
                "fault": None,
                "requested_state": requested_state,
                "effective_state": requested_state,
                "delay_seconds": 0.0,
                "error_message": None
            }

        # Check explicit rules first
        matching_rule: Optional[FaultRule] = None
        for rule in self.config.rules:
            if rule.matches(device, action, count):
                matching_rule = rule
                break

        # Fallback to deterministic pseudo-random rate if configured
        if matching_rule is None and self.rng and self.config.random_fault_rate > 0.0:
            if self.rng.random() < self.config.random_fault_rate:
                matching_rule = FaultRule(
                    device=device,
                    action=action,
                    fault_type=FaultType.ACTION_FAILURE,
                    error_message=f"Pseudo-random actuation failure (seed {self.config.seed})"
                )

        if matching_rule is None:
            # No fault triggered
            evt = ExecutionEvent(
                step=self.step_counter,
                simulated_time=simulated_time,
                event_type="ACTUATION",
                device=device,
                action=action,
                requested_state=requested_state,
                observed_state=requested_state,
                final_outcome="SUCCESS",
                details=f"Actuation to {requested_state} (rule checked, no fault)",
                line=line
            )
            self.record_event(evt)
            return {
                "fault": None,
                "requested_state": requested_state,
                "effective_state": requested_state,
                "delay_seconds": 0.0,
                "error_message": None
            }

        # Fault triggered!
        self.faults_injected += 1
        ft = matching_rule.fault_type

        if ft == FaultType.ACTION_FAILURE:
            msg = matching_rule.error_message or f"Simulated actuation failure: '{action} {device}' failed"
            evt = ExecutionEvent(
                step=self.step_counter,
                simulated_time=simulated_time,
                event_type="FAULT",
                device=device,
                action=action,
                requested_state=requested_state,
                observed_state=current_state,
                fault_type=ft,
                final_outcome="FAULT_INJECTED",
                details=msg,
                line=line
            )
            self.record_event(evt)
            return {
                "fault": matching_rule,
                "requested_state": requested_state,
                "effective_state": current_state,  # Remains in current state
                "delay_seconds": 0.0,
                "error_message": msg
            }

        elif ft == FaultType.STATE_MISMATCH:
            observed_state = matching_rule.mismatch_state
            details = f"State mismatch: requested {requested_state}, observed {observed_state}"
            evt = ExecutionEvent(
                step=self.step_counter,
                simulated_time=simulated_time,
                event_type="FAULT",
                device=device,
                action=action,
                requested_state=requested_state,
                observed_state=observed_state,
                fault_type=ft,
                final_outcome="FAULT_INJECTED",
                details=details,
                line=line
            )
            self.record_event(evt)
            return {
                "fault": matching_rule,
                "requested_state": requested_state,
                "effective_state": observed_state,  # Observed differs from requested!
                "delay_seconds": 0.0,
                "error_message": None
            }

        elif ft == FaultType.DELAYED_COMPLETION:
            delay = matching_rule.delay_seconds
            details = f"Delayed actuation: completed after {delay:.2f}s delay"
            evt = ExecutionEvent(
                step=self.step_counter,
                simulated_time=simulated_time + delay,
                event_type="FAULT",
                device=device,
                action=action,
                requested_state=requested_state,
                observed_state=requested_state,
                fault_type=ft,
                final_outcome="FAULT_INJECTED",
                details=details,
                line=line
            )
            self.record_event(evt)
            return {
                "fault": matching_rule,
                "requested_state": requested_state,
                "effective_state": requested_state,
                "delay_seconds": delay,
                "error_message": None
            }

        raise ValueError(f"Unknown fault type: '{ft}'")

    def record_recovery_entry(self, handler_target: str, error: Exception, line: int, simulated_time: float):
        """Record when execution transfers to a RECOVER block."""
        self.step_counter += 1
        self.recoveries_triggered += 1
        self.record_event(ExecutionEvent(
            step=self.step_counter,
            simulated_time=simulated_time,
            event_type="RECOVERY_ENTERED",
            recovery_decision=f"JUMP {handler_target}",
            final_outcome="RECOVERED",
            details=f"Entering recovery handler due to: {error}",
            line=line
        ))

    def record_recovery_exit(self, line: int, simulated_time: float):
        """Record when a RECOVER block completes successfully."""
        self.step_counter += 1
        self.recoveries_succeeded += 1
        self.record_event(ExecutionEvent(
            step=self.step_counter,
            simulated_time=simulated_time,
            event_type="RECOVERY_COMPLETED",
            recovery_decision="CLEAR_TRY_ERROR",
            final_outcome="SUCCESS",
            details="Recovery sequence completed successfully",
            line=line
        ))

    def get_summary(self) -> Dict[str, Any]:
        """Structured telemetry summary of injected faults and recovery outcomes."""
        return {
            "faults_injected": self.faults_injected,
            "recoveries_triggered": self.recoveries_triggered,
            "recoveries_succeeded": self.recoveries_succeeded,
            "unrecovered_faults": max(0, self.faults_injected - self.recoveries_succeeded),
            "total_monitored_events": len(self.events)
        }
