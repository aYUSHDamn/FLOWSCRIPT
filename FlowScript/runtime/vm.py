import time
from errors import FlowScriptError, InvariantViolation
from ir.generator import BINOPS, Temp


def fmt(v):
    if isinstance(v, bool): return str(int(v))
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v)


class VM:
    """Stack machine that runs IR. Devices and WAIT are simulated."""

    def __init__(self, code, realtime=False, out=print, max_instructions=None, timeout_sec=None, fault_injector=None):
        self.code, self.realtime, self.out = code, realtime, out
        self.max_instructions = max_instructions
        self.timeout_sec = timeout_sec
        self.fault_injector = fault_injector
        self.instruction_count = 0
        self.vars, self.temps, self.devices, self.simulated_time = {}, {}, {}, 0
        self.handlers, self.recovery_records = [], []

    @property
    def execution_events(self):
        return self.fault_injector.events if self.fault_injector else []

    @property
    def fault_summary(self):
        return self.fault_injector.get_summary() if self.fault_injector else {}

    def run(self):
        t0 = time.perf_counter()
        code = self.code
        labels = {i.arg: k for k, i in enumerate(code) if i.op == "LABEL"}
        stack, pc = [], 0
        self.handlers, self.recovery_records = [], []
        self.instruction_count = 0
        while pc < len(code):
            ins = code[pc]; pc += 1; op = ins.op
            if self.max_instructions is not None:
                self.instruction_count += 1
                if self.instruction_count > self.max_instructions:
                    raise FlowScriptError("Runtime", f"Instruction limit ({self.max_instructions}) exceeded", ins.line)
            if self.timeout_sec is not None and (self.instruction_count % 500 == 0):
                if (time.perf_counter() - t0) > self.timeout_sec:
                    raise FlowScriptError("Runtime", f"Execution timeout ({self.timeout_sec:.1f}s) exceeded", ins.line)
            try:
                if op == "PUSH": stack.append(ins.arg)
                elif op == "LOAD":
                    if isinstance(ins.arg, Temp):
                        stack.append(self.temps[ins.arg.id])
                    else:
                        if ins.arg not in self.vars:
                            raise FlowScriptError("Runtime", f"Variable '{ins.arg}' is not defined", ins.line)
                        stack.append(self.vars[ins.arg])
                elif op == "STORE":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    val = stack.pop()
                    if isinstance(ins.arg, Temp):
                        self.temps[ins.arg.id] = val
                    else:
                        self.vars[ins.arg] = val
                elif op == "CHECK_REPEAT_COUNT":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    count = stack[-1]
                    if isinstance(count, bool) or not isinstance(count, (int, float)) or (isinstance(count, float) and not count.is_integer()):
                        raise FlowScriptError("Runtime", "REPEAT count must be an integer", ins.line)
                    if count < 0:
                        raise FlowScriptError("Runtime", "REPEAT count cannot be negative", ins.line)
                    stack[-1] = int(count)
                elif op in BINOPS:
                    if len(stack) < 2:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    b, a = stack.pop(), stack.pop()
                    try:
                        stack.append(BINOPS[op](a, b))
                    except ZeroDivisionError:
                        raise FlowScriptError("Runtime", "Division by zero", ins.line)
                    except TypeError as e:
                        raise FlowScriptError("Runtime", f"Type error in operation '{op}': {e}", ins.line)
                elif op == "PRINT":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    self.out(fmt(stack.pop()))
                elif op == "JUMP":
                    if ins.arg not in labels:
                        raise FlowScriptError("Runtime", f"Unknown jump target '{ins.arg}'", ins.line)
                    pc = labels[ins.arg]
                elif op == "JUMP_IF_FALSE":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    if not stack.pop():
                        if ins.arg not in labels:
                            raise FlowScriptError("Runtime", f"Unknown jump target '{ins.arg}'", ins.line)
                        pc = labels[ins.arg]
                elif op in ("TURN_ON", "TURN_OFF"):
                    device = ins.arg
                    cur_st = self.devices.get(device, "OFF")
                    if self.fault_injector is not None and self.fault_injector.enabled:
                        res = self.fault_injector.evaluate_actuation(
                            device=device,
                            action=op,
                            current_state=cur_st,
                            line=ins.line,
                            simulated_time=self.simulated_time
                        )
                        if res["delay_seconds"] > 0:
                            self.simulated_time += res["delay_seconds"]
                            if self.realtime:
                                time.sleep(res["delay_seconds"])
                        if res["error_message"] is not None:
                            raise FlowScriptError("Runtime", res["error_message"], ins.line)
                        eff_state = res["effective_state"]
                        self.devices[device] = eff_state
                        self.out(f"{device} → {eff_state}")
                    else:
                        state = "ON" if op == "TURN_ON" else "OFF"
                        self.devices[device] = state
                        self.out(f"{device} → {state}")
                elif op == "DECLARE_DEVICE":
                    dev_name, dev_type = ins.arg
                    initial = "READY" if dev_type == "sensor" else "OFF"
                    self.devices[dev_name] = initial
                elif op == "READ_DEVICE_PROP":
                    dev, prop = ins.arg
                    if dev not in self.devices:
                        raise FlowScriptError("Runtime", f"Device '{dev}' has not been declared", ins.line)
                    if prop not in ("status", "state"):
                        raise FlowScriptError("Runtime", f"Unknown property '{prop}' on device '{dev}'", ins.line)
                    stack.append(self.devices[dev])
                elif op == "NOT":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    val = stack.pop()
                    stack.append(0 if val else 1)
                elif op == "ASSERT_REQUIRE":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    if not stack.pop():
                        raise FlowScriptError("Runtime", f"REQUIRE contract violated [line {ins.arg}]", ins.line)
                elif op == "ASSERT_ENSURE":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    if not stack.pop():
                        raise FlowScriptError("Runtime", f"ENSURE contract violated [line {ins.arg}]", ins.line)
                elif op == "ASSERT_INVARIANT":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    if not stack.pop():
                        raise InvariantViolation(f"INVARIANT contract violated [line {ins.arg}]", ins.line)
                elif op == "WAIT":
                    if not stack:
                        raise FlowScriptError("Runtime", "Stack underflow", ins.line)
                    secs = stack.pop()
                    if not isinstance(secs, (int, float)) or isinstance(secs, bool):
                        raise FlowScriptError("Runtime", "WAIT requires a numeric value", ins.line)
                    if secs < 0:
                        raise FlowScriptError("Runtime", "WAIT with negative time", ins.line)
                    self.simulated_time += secs
                    if self.realtime: time.sleep(secs)
                elif op == "SETUP_RECOVER":
                    self.handlers.append({"target": ins.arg, "depth": len(stack), "line": ins.line})
                elif op == "POP_RECOVER":
                    if self.handlers:
                        self.handlers.pop()
                elif op == "CLEAR_TRY_ERROR":
                    if self.recovery_records:
                        self.recovery_records.pop()
                    if self.fault_injector is not None and self.fault_injector.enabled:
                        self.fault_injector.record_recovery_exit(ins.line, self.simulated_time)
                elif op == "LABEL":
                    pass
                else:
                    raise FlowScriptError("Runtime", f"Unknown instruction '{op}'", ins.line)
            except FlowScriptError as e:
                if isinstance(e, InvariantViolation) or getattr(e, "is_invariant", False):
                    raise e
                if self.recovery_records and len(self.handlers) <= self.recovery_records[-1]["depth"]:
                    rec = self.recovery_records.pop()
                    orig = rec["error"]
                    e = FlowScriptError(
                        "Runtime",
                        f"Recovery failed [line {e.line}]: {e.message} (original error in TRY [line {orig.line}]: {orig.message})",
                        e.line
                    )
                if self.handlers:
                    handler = self.handlers.pop()
                    del stack[handler["depth"]:]
                    self.recovery_records.append({"depth": len(self.handlers), "error": e})
                    if self.fault_injector is not None and self.fault_injector.enabled:
                        self.fault_injector.record_recovery_entry(handler["target"], e, ins.line, self.simulated_time)
                    if handler["target"] not in labels:
                        raise FlowScriptError("Runtime", f"Unknown jump target '{handler['target']}'", ins.line)
                    pc = labels[handler["target"]]
                    continue
                else:
                    raise e
        return 0
