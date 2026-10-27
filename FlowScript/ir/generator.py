from dataclasses import dataclass
from ast_nodes.nodes import (Assign, Print, If, Repeat, Wait, Device,
                             DeviceDecl, DeviceProperty, StateLiteral,
                             Invariant, Require, Ensure, Try, UnaryOp,
                             Number, String, Var, BinOp)

BINOPS = {
    "ADD": lambda a, b: a + b, "SUB": lambda a, b: a - b,
    "MUL": lambda a, b: a * b, "DIV": lambda a, b: a / b,
    "GT": lambda a, b: 1 if a > b else 0,   "LT": lambda a, b: 1 if a < b else 0,
    "GE": lambda a, b: 1 if a >= b else 0,  "LE": lambda a, b: 1 if a <= b else 0,
    "EQ": lambda a, b: 1 if a == b else 0,  "NE": lambda a, b: 1 if a != b else 0,
    "AND": lambda a, b: 1 if (a and b) else 0,
    "OR": lambda a, b: 1 if (a or b) else 0,
}
OPMAP = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", ">": "GT", "<": "LT",
         ">=": "GE", "<=": "LE", "==": "EQ", "!=": "NE", "AND": "AND", "OR": "OR"}


@dataclass(frozen=True)
class Temp:
    """Compiler-internal temporary variable / register operand."""
    id: int

    def __str__(self):
        return f"$t{self.id}"


class Instr:
    __slots__ = ("op", "arg", "line")

    def __init__(self, op, arg=None, line=0):
        self.op, self.arg, self.line = op, arg, line

    def __str__(self):
        if self.op == "LABEL": return f"{self.arg}:"
        if self.arg is None: return self.op
        if self.op == "PUSH" and isinstance(self.arg, str): return f'PUSH "{self.arg}"'
        if self.op == "PUSH" and isinstance(self.arg, bool): return f"PUSH {int(self.arg)}"
        if isinstance(self.arg, tuple): return f"{self.op} {' '.join(str(x) for x in self.arg)}"
        return f"{self.op} {self.arg}"


class IRGenerator:
    """AST -> flat stack-machine instructions with labels and jumps."""

    def __init__(self):
        self.code, self.labels, self.tmp = [], 0, 0
        self.invariants = []

    def label(self):
        self.labels += 1
        return f"L{self.labels}"

    def emit(self, op, arg=None, line=0):
        self.code.append(Instr(op, arg, line))

    def generate(self, program):
        self.invariants = [s for s in program.body if isinstance(s, Invariant)]
        self.block(program.body)
        return self.code

    def _emit_invariants(self, ln):
        for inv in self.invariants:
            self.expr(inv.expr)
            self.emit("ASSERT_INVARIANT", inv.line, ln)

    def block(self, stmts):
        for s in stmts:
            self.stmt(s)

    def stmt(self, s):
        ln = s.line
        if isinstance(s, DeviceDecl):
            self.emit("DECLARE_DEVICE", (s.name, s.dev_type), ln)
        elif isinstance(s, Assign):
            self.expr(s.value); self.emit("STORE", s.name, ln)
        elif isinstance(s, Print):
            self.expr(s.expr); self.emit("PRINT", None, ln)
        elif isinstance(s, Wait):
            self.expr(s.expr); self.emit("WAIT", None, ln)
        elif isinstance(s, Invariant):
            self.expr(s.expr); self.emit("ASSERT_INVARIANT", s.line, ln)
        elif isinstance(s, Require):
            self.expr(s.expr); self.emit("ASSERT_REQUIRE", s.line, ln)
        elif isinstance(s, Ensure):
            self.expr(s.expr); self.emit("ASSERT_ENSURE", s.line, ln)
        elif isinstance(s, Device):
            self.emit(s.action, s.name, ln)
            self._emit_invariants(ln)
        elif isinstance(s, If):
            self.expr(s.cond)
            l_else = self.label()
            self.emit("JUMP_IF_FALSE", l_else, ln)
            self.block(s.then)
            if s.otherwise:
                l_end = self.label()
                self.emit("JUMP", l_end, ln)
                self.emit("LABEL", l_else)
                self.block(s.otherwise)
                self.emit("LABEL", l_end)
            else:
                self.emit("LABEL", l_else)
        elif isinstance(s, Repeat):
            ctr = Temp(self.tmp); self.tmp += 1
            top, end = self.label(), self.label()
            self.expr(s.count)
            self.emit("CHECK_REPEAT_COUNT", None, ln)
            self.emit("STORE", ctr, ln)      # count evaluated once
            self.emit("LABEL", top)
            self.emit("LOAD", ctr, ln); self.emit("PUSH", 0, ln); self.emit("GT", None, ln)
            self.emit("JUMP_IF_FALSE", end, ln)
            self.block(s.body)
            self.emit("LOAD", ctr, ln); self.emit("PUSH", 1, ln)
            self.emit("SUB", None, ln); self.emit("STORE", ctr, ln)
            self.emit("JUMP", top, ln)
            self.emit("LABEL", end)
        elif isinstance(s, Try):
            l_recover, l_end = self.label(), self.label()
            self.emit("SETUP_RECOVER", l_recover, ln)
            self.block(s.body)
            self.emit("POP_RECOVER", None, ln)
            self.emit("JUMP", l_end, ln)
            self.emit("LABEL", l_recover)
            self.block(s.recover)
            self.emit("CLEAR_TRY_ERROR", None, ln)
            self.emit("LABEL", l_end)

    def expr(self, e):
        if isinstance(e, (Number, String)): self.emit("PUSH", e.value, e.line)
        elif isinstance(e, StateLiteral):   self.emit("PUSH", e.value, e.line)
        elif isinstance(e, DeviceProperty): self.emit("READ_DEVICE_PROP", (e.device, e.prop), e.line)
        elif isinstance(e, Var):            self.emit("LOAD", e.name, e.line)
        elif isinstance(e, UnaryOp):
            if e.op == "NOT":
                self.expr(e.expr)
                self.emit("NOT", None, e.line)
        elif isinstance(e, BinOp):
            self.expr(e.left); self.expr(e.right); self.emit(OPMAP[e.op], None, e.line)
