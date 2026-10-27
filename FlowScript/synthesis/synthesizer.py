import time
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from ast_nodes.nodes import (
    Program, Device, DeviceDecl, DeviceProperty, StateLiteral,
    Invariant, Try, Synthesize, BinOp, UnaryOp, Number, String, Node
)
from errors import FlowScriptError


@dataclass(frozen=True)
class Action:
    """An approved discrete actuation action."""
    action: str  # "TURN_ON" or "TURN_OFF"
    device: str

    def to_ast(self, line: int = 0) -> Device:
        return Device(self.action, self.device, line)

    def __str__(self) -> str:
        return f"{self.action} {self.device}"


@dataclass
class SynthesisTelemetry:
    """Structured telemetry record of a recovery synthesis search."""
    initial_state: Dict[str, str]
    target_condition: str
    states_explored: int
    transitions_rejected: int
    plan: List[str]
    search_depth: int
    success: bool
    budget: int
    duration_ms: float

    def to_dict(self) -> dict:
        return {
            "initial_state": self.initial_state,
            "target_condition": self.target_condition,
            "states_explored": self.states_explored,
            "transitions_rejected": self.transitions_rejected,
            "plan": self.plan,
            "search_depth": self.search_depth,
            "success": self.success,
            "budget": self.budget,
            "duration_ms": round(self.duration_ms, 3),
        }

    @staticmethod
    def csv_header() -> str:
        return "initial_state,target_condition,states_explored,transitions_rejected,search_depth,budget,success,plan,duration_ms"

    def to_csv_row(self) -> str:
        init_str = ";".join(f"{k}={v}" for k, v in sorted(self.initial_state.items()))
        plan_str = ";".join(self.plan) if self.plan else "NONE"
        return f'"{init_str}","{self.target_condition}",{self.states_explored},{self.transitions_rejected},{self.search_depth},{self.budget},{int(self.success)},"{plan_str}",{self.duration_ms:.3f}'


@dataclass
class SynthesisResult:
    """Result returned by synthesize_recovery_plan."""
    success: bool
    plan: List[Action]
    telemetry: SynthesisTelemetry


def expr_to_str(e: Node) -> str:
    """Pretty-print an expression for telemetry and error reporting."""
    if isinstance(e, DeviceProperty):
        return f"{e.device}.{e.prop}"
    if isinstance(e, StateLiteral):
        return e.value
    if isinstance(e, Number):
        return str(int(e.value) if isinstance(e.value, float) and e.value.is_integer() else e.value)
    if isinstance(e, String):
        return f'"{e.value}"'
    if isinstance(e, UnaryOp):
        return f"{e.op} {expr_to_str(e.expr)}"
    if isinstance(e, BinOp):
        return f"({expr_to_str(e.left)} {e.op} {expr_to_str(e.right)})"
    return str(e)


def eval_condition(expr: Node, state: Dict[str, str]):
    """Recursively evaluate an AST condition against simulated device states."""
    if isinstance(expr, DeviceProperty):
        return state.get(expr.device, "OFF")
    if isinstance(expr, StateLiteral):
        return expr.value
    if isinstance(expr, Number):
        return expr.value
    if isinstance(expr, String):
        return expr.value
    if isinstance(expr, UnaryOp):
        if expr.op == "NOT":
            return not bool(eval_condition(expr.expr, state))
        raise ValueError(f"Unknown unary operator '{expr.op}'")
    if isinstance(expr, BinOp):
        op = expr.op
        if op == "AND":
            return bool(eval_condition(expr.left, state) and eval_condition(expr.right, state))
        if op == "OR":
            return bool(eval_condition(expr.left, state) or eval_condition(expr.right, state))
        l = eval_condition(expr.left, state)
        r = eval_condition(expr.right, state)
        if op == "==": return l == r
        if op == "!=": return l != r
        if op == "<":  return l < r
        if op == "<=": return l <= r
        if op == ">":  return l > r
        if op == ">=": return l >= r
        raise ValueError(f"Unknown comparison operator '{op}'")
    raise ValueError(f"Unsupported AST node in synthesis condition: {type(expr).__name__}")


def canonical_state(st: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    """Canonical sorted tuple for deterministic state hashing and equality."""
    return tuple(sorted(st.items()))


def is_applicable(state: Dict[str, str], action: Action) -> bool:
    """Precondition check: do not actuate if device is already in target state."""
    cur = state.get(action.device, "OFF")
    if action.action == "TURN_ON":
        return cur != "ON"
    if action.action == "TURN_OFF":
        return cur != "OFF"
    return False


def apply_action(state: Dict[str, str], action: Action) -> Dict[str, str]:
    """Simulated state transition effect."""
    next_st = dict(state)
    next_st[action.device] = "ON" if action.action == "TURN_ON" else "OFF"
    return next_st


def synthesize_recovery_plan(
    initial_state: Dict[str, str],
    approved_actions: List[Action],
    invariants: List[Invariant],
    target_expr: Node,
    max_steps: int = 5
) -> SynthesisResult:
    """Deterministic BFS graph search for shortest safe recovery plan."""
    t0 = time.perf_counter()
    target_desc = expr_to_str(target_expr)

    # Sort actions deterministically: primary key device name, secondary action name
    approved = sorted(approved_actions, key=lambda a: (a.device, a.action))

    # Check if initial state already satisfies target
    if eval_condition(target_expr, initial_state):
        dur = (time.perf_counter() - t0) * 1000
        telemetry = SynthesisTelemetry(
            initial_state=dict(initial_state),
            target_condition=target_desc,
            states_explored=0,
            transitions_rejected=0,
            plan=[],
            search_depth=0,
            success=True,
            budget=max_steps,
            duration_ms=dur
        )
        return SynthesisResult(success=True, plan=[], telemetry=telemetry)

    queue = deque([(dict(initial_state), [])])
    visited = {canonical_state(initial_state)}
    states_explored = 0
    transitions_rejected = 0

    while queue:
        cur_state, plan = queue.popleft()
        states_explored += 1

        if len(plan) >= max_steps:
            continue

        for act in approved:
            if not is_applicable(cur_state, act):
                continue
            next_state = apply_action(cur_state, act)

            # Invariant validation
            inv_failed = False
            for inv in invariants:
                if not eval_condition(inv.expr, next_state):
                    inv_failed = True
                    break
            if inv_failed:
                transitions_rejected += 1
                continue

            next_plan = plan + [act]

            # Goal satisfaction check
            if eval_condition(target_expr, next_state):
                dur = (time.perf_counter() - t0) * 1000
                telemetry = SynthesisTelemetry(
                    initial_state=dict(initial_state),
                    target_condition=target_desc,
                    states_explored=states_explored,
                    transitions_rejected=transitions_rejected,
                    plan=[str(a) for a in next_plan],
                    search_depth=len(next_plan),
                    success=True,
                    budget=max_steps,
                    duration_ms=dur
                )
                return SynthesisResult(success=True, plan=next_plan, telemetry=telemetry)

            c_state = canonical_state(next_state)
            if c_state not in visited:
                visited.add(c_state)
                queue.append((next_state, next_plan))

    dur = (time.perf_counter() - t0) * 1000
    telemetry = SynthesisTelemetry(
        initial_state=dict(initial_state),
        target_condition=target_desc,
        states_explored=states_explored,
        transitions_rejected=transitions_rejected,
        plan=[],
        search_depth=0,
        success=False,
        budget=max_steps,
        duration_ms=dur
    )
    return SynthesisResult(success=False, plan=[], telemetry=telemetry)


def extract_state_from_expr(expr: Node, base_state: Dict[str, str]) -> Dict[str, str]:
    """Extract explicit device assignments from a FROM expression."""
    st = dict(base_state)
    def _walk(e):
        if isinstance(e, BinOp):
            if e.op == "==" and isinstance(e.left, DeviceProperty) and isinstance(e.right, StateLiteral):
                st[e.left.device] = e.right.value
            elif e.op == "==" and isinstance(e.right, DeviceProperty) and isinstance(e.left, StateLiteral):
                st[e.right.device] = e.left.value
            elif e.op == "AND":
                _walk(e.left)
                _walk(e.right)
    _walk(expr)
    return st


class SynthesizerPass:
    """Compiler pass that replaces Synthesize AST nodes with validated plans."""

    def __init__(self):
        self.declared_devices = {}  # name -> dev_type
        self.invariants = []        # list of Invariant nodes
        self.simulated_state = {}   # name -> current state
        self.telemetry_log = []     # list of SynthesisTelemetry

    def transform(self, program: Program) -> Program:
        self.declared_devices.clear()
        self.invariants.clear()
        self.simulated_state.clear()
        self.telemetry_log.clear()

        # Step 1: Collect declarations and invariants
        for s in program.body:
            if isinstance(s, DeviceDecl):
                self.declared_devices[s.name] = s.dev_type
                initial = "READY" if s.dev_type == "sensor" else "OFF"
                self.simulated_state[s.name] = initial
            elif isinstance(s, Invariant):
                self.invariants.append(s)

        # Step 2: Traverse workflow and synthesize recovery blocks
        program.body = self._transform_block(program.body)
        return program

    def _transform_block(self, stmts: list) -> list:
        out = []
        for s in stmts:
            if isinstance(s, Device):
                self.simulated_state[s.name] = "ON" if s.action == "TURN_ON" else "OFF"
                out.append(s)
            elif isinstance(s, Try):
                # Save snapshot of state before TRY body
                state_before_try = dict(self.simulated_state)

                # Process TRY body
                s.body = self._transform_block(s.body)

                # Device state at exit of TRY body represents the failure point state
                state_at_failure = dict(self.simulated_state)

                # Process RECOVER block
                s.recover = self._transform_recover(s.recover, state_at_failure, s.line)
                out.append(s)
            else:
                out.append(s)
        return out

    def _transform_recover(self, recover_stmts: list, failure_state: Dict[str, str], try_line: int) -> list:
        out = []
        for s in recover_stmts:
            if isinstance(s, Synthesize):
                # Determine initial state for synthesis
                if s.from_state is not None:
                    init_st = extract_state_from_expr(s.from_state, failure_state)
                else:
                    init_st = dict(failure_state)

                # Determine approved actions
                if s.using is not None:
                    approved_actions = [Action(act, dev) for act, dev in s.using]
                else:
                    # Default: all declared controllable devices
                    approved_actions = []
                    for dev_name, dev_type in self.declared_devices.items():
                        if dev_type != "sensor":
                            approved_actions.append(Action("TURN_ON", dev_name))
                            approved_actions.append(Action("TURN_OFF", dev_name))

                # Determine search budget (default 5)
                budget = 5
                if s.max_steps is not None:
                    if isinstance(s.max_steps, Number):
                        budget = int(s.max_steps.value)
                    elif hasattr(s.max_steps, "value"):
                        budget = int(s.max_steps.value)

                # Run bounded synthesis
                res = synthesize_recovery_plan(
                    initial_state=init_st,
                    approved_actions=approved_actions,
                    invariants=self.invariants,
                    target_expr=s.target,
                    max_steps=budget
                )
                self.telemetry_log.append(res.telemetry)

                if not res.success:
                    target_str = expr_to_str(s.target)
                    raise FlowScriptError(
                        "Synthesis",
                        f"No safe recovery plan found for target '{target_str}' within {budget} steps",
                        s.line or try_line
                    )

                # Lower synthesized plan into Device AST nodes
                for act in res.plan:
                    out.append(act.to_ast(s.line or try_line))
                    self.simulated_state[act.device] = "ON" if act.action == "TURN_ON" else "OFF"
            elif isinstance(s, Try):
                s.body = self._transform_block(s.body)
                s.recover = self._transform_recover(s.recover, dict(self.simulated_state), s.line)
                out.append(s)
            elif isinstance(s, Device):
                self.simulated_state[s.name] = "ON" if s.action == "TURN_ON" else "OFF"
                out.append(s)
            else:
                out.append(s)
        return out
