from ast_nodes.nodes import (Assign, Print, If, Repeat, Wait, Device,
                             DeviceDecl, DeviceProperty, StateLiteral,
                             Invariant, Require, Ensure, Try, Synthesize, UnaryOp,
                             Number, String, Var, BinOp)
from errors import FlowScriptError

NUM, STR, STATE = "number", "string", "state"
VALID_PROPERTIES = {"status", "state"}
VALID_STATES = {"ON", "OFF", "READY", "ERROR"}


class SemanticAnalyzer:
    """Symbol table + type checking + definite assignment analysis."""

    def __init__(self):
        self.symbols = {}          # variable -> type
        self.devices = set()       # all devices referenced in workflow
        self.declared_devices = {} # device_name -> dev_type
        self.invariants = []       # list of global invariants

    def err(self, msg, node):
        raise FlowScriptError("Semantic", msg, getattr(node, "line", 0))

    def analyze(self, program):
        self.block(program.body, set())
        return self.symbols

    def block(self, stmts, assigned):
        for s in stmts:
            assigned = self.stmt(s, assigned)
        return assigned

    def stmt(self, s, assigned):
        if isinstance(s, DeviceDecl):
            if s.name in self.declared_devices:
                self.err(f"Duplicate device declaration '{s.name}'.", s)
            if s.name in self.symbols:
                self.err(f"Device name '{s.name}' collides with an existing variable.", s)
            self.declared_devices[s.name] = s.dev_type
            self.devices.add(s.name)
            return assigned
        elif isinstance(s, Assign):
            if s.name in self.declared_devices:
                self.err(f"Cannot assign to '{s.name}': '{s.name}' is a declared device.", s)
            t = self.type_of(s.value, assigned)
            old = self.symbols.get(s.name)
            if old and old != t:
                self.err(f"Cannot assign {t} to {old} variable '{s.name}'.", s)
            self.symbols[s.name] = t
            return assigned | {s.name}
        elif isinstance(s, Print):
            self.type_of(s.expr, assigned)
            return assigned
        elif isinstance(s, Wait):
            if self.type_of(s.expr, assigned) != NUM:
                self.err("WAIT requires a numeric value.", s)
            return assigned
        elif isinstance(s, Invariant):
            if self.type_of(s.expr, assigned) != NUM:
                self.err("INVARIANT condition must be a boolean or numeric expression.", s)
            self.invariants.append(s)
            return assigned
        elif isinstance(s, Require):
            if self.type_of(s.expr, assigned) != NUM:
                self.err("REQUIRE condition must be a boolean or numeric expression.", s)
            return assigned
        elif isinstance(s, Ensure):
            if self.type_of(s.expr, assigned) != NUM:
                self.err("ENSURE condition must be a boolean or numeric expression.", s)
            return assigned
        elif isinstance(s, If):
            if self.type_of(s.cond, assigned) != NUM:
                self.err("IF condition must be a comparison or number.", s)
            then_assigned = self.block(s.then, set(assigned))
            if s.otherwise:
                else_assigned = self.block(s.otherwise, set(assigned))
                return then_assigned & else_assigned
            return assigned
        elif isinstance(s, Repeat):
            if self.type_of(s.count, assigned) != NUM:
                self.err("REPEAT requires a numeric count.", s)
            c_val = self._const_number(s.count)
            if c_val is not None:
                if isinstance(c_val, bool) or not isinstance(c_val, (int, float)) or (isinstance(c_val, float) and not c_val.is_integer()):
                    self.err("REPEAT count must be an integer.", s)
                if c_val < 0:
                    self.err("REPEAT count cannot be negative.", s)
            self.block(s.body, set(assigned))
            return assigned
        elif isinstance(s, Device):
            if s.name in self.symbols:
                self.err(f"Cannot use variable '{s.name}' as a device in {s.action}.", s)
            self.devices.add(s.name)
            return assigned
        elif isinstance(s, Try):
            try_assigned = self.block(s.body, set(assigned))
            rec_assigned = self.block(s.recover, set(assigned))
            return try_assigned & rec_assigned
        elif isinstance(s, Synthesize):
            if self.type_of(s.target, assigned) != NUM:
                self.err("SYNTHESIZE target condition must be a boolean or numeric expression.", s)
            if s.from_state is not None:
                if self.type_of(s.from_state, assigned) != NUM:
                    self.err("SYNTHESIZE FROM condition must be a boolean or numeric expression.", s)
            if s.using is not None:
                for act, dev in s.using:
                    if dev not in self.declared_devices:
                        self.err(f"Device '{dev}' in USING clause is not declared.", s)
                    if self.declared_devices[dev] == "sensor":
                        self.err(f"Cannot actuate sensor '{dev}' in USING clause.", s)
                    self.devices.add(dev)
            if s.max_steps is not None:
                if self.type_of(s.max_steps, assigned) != NUM:
                    self.err("SYNTHESIZE MAX_STEPS must be a numeric value.", s)
                val = self._const_number(s.max_steps)
                if val is not None:
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or (isinstance(val, float) and not val.is_integer()):
                        self.err("SYNTHESIZE MAX_STEPS must be an integer.", s)
                    if val < 0:
                        self.err("SYNTHESIZE MAX_STEPS cannot be negative.", s)
            return assigned
        return assigned

    def _const_number(self, e):
        if isinstance(e, Number):
            return e.value
        if isinstance(e, BinOp) and e.op == "-" and isinstance(e.left, Number) and e.left.value == 0:
            r = self._const_number(e.right)
            if r is not None:
                return -r
        return None

    def type_of(self, e, assigned):
        if isinstance(e, Number): return NUM
        if isinstance(e, String): return STR
        if isinstance(e, StateLiteral):
            if e.value not in VALID_STATES:
                self.err(f"Invalid device state '{e.value}'. Valid states: {', '.join(sorted(VALID_STATES))}.", e)
            return STATE
        if isinstance(e, DeviceProperty):
            if e.device not in self.declared_devices:
                self.err(f"Device '{e.device}' is not declared.", e)
            if e.prop not in VALID_PROPERTIES:
                self.err(f"Unknown property '{e.prop}' on device '{e.device}'. Supported properties: status.", e)
            return STATE
        if isinstance(e, Var):
            if e.name in self.declared_devices:
                self.err(f"Cannot use declared device '{e.name}' as a variable; use '{e.name}.status' to query state.", e)
            if e.name not in assigned:
                if e.name not in self.symbols:
                    self.err(f"Variable '{e.name}' is not defined.", e)
                else:
                    self.err(f"Variable '{e.name}' is not definitely assigned.", e)
            return self.symbols[e.name]
        if isinstance(e, UnaryOp):
            if e.op == "NOT":
                t = self.type_of(e.expr, assigned)
                if t != NUM:
                    self.err("Operator 'NOT' requires a boolean or numeric expression.", e)
                return NUM
            self.err(f"Unknown unary operator '{e.op}'", e)
        if isinstance(e, BinOp):
            if e.op in ("AND", "OR"):
                l = self.type_of(e.left, assigned)
                r = self.type_of(e.right, assigned)
                if l != NUM or r != NUM:
                    self.err(f"Operator '{e.op}' requires boolean or numeric expressions.", e)
                return NUM
            l, r = self.type_of(e.left, assigned), self.type_of(e.right, assigned)
            if e.op == "+":
                if l != r: self.err(f"Cannot add {l} and {r}.", e)
                if l == STATE: self.err("Cannot perform arithmetic on state values.", e)
                return l
            if e.op in ("==", "!="):
                if l != r: self.err(f"Cannot compare {l} with {r}.", e)
                return NUM
            if l == STATE or r == STATE:
                self.err(f"Operator '{e.op}' cannot be applied to state values.", e)
            if l != NUM or r != NUM:
                self.err(f"Operator '{e.op}' requires numbers.", e)
            return NUM
        self.err("Unknown expression", e)
