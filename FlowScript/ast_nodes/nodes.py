from dataclasses import dataclass, fields


class Node:
    pass

@dataclass
class Program(Node):  body: list
@dataclass
class Assign(Node):   name: str; value: Node; line: int = 0
@dataclass
class Print(Node):    expr: Node; line: int = 0
@dataclass
class If(Node):       cond: Node; then: list; otherwise: list; line: int = 0
@dataclass
class Repeat(Node):   count: Node; body: list; line: int = 0
@dataclass
class Wait(Node):     expr: Node; line: int = 0
@dataclass
class Device(Node):   action: str; name: str; line: int = 0      # TURN_ON / TURN_OFF
@dataclass
class Try(Node):      body: list; recover: list; line: int = 0
@dataclass
class Synthesize(Node): target: Node; from_state: Node = None; using: list = None; max_steps: Node = None; line: int = 0
@dataclass
class DeviceDecl(Node): name: str; dev_type: str; line: int = 0
@dataclass
class DeviceProperty(Node): device: str; prop: str; line: int = 0
@dataclass
class StateLiteral(Node): value: str; line: int = 0
@dataclass
class Invariant(Node): expr: Node; line: int = 0
@dataclass
class Require(Node):   expr: Node; line: int = 0
@dataclass
class Ensure(Node):    expr: Node; line: int = 0
@dataclass
class Number(Node):   value: float; line: int = 0
@dataclass
class String(Node):   value: str; line: int = 0
@dataclass
class Var(Node):      name: str; line: int = 0
@dataclass
class UnaryOp(Node):  op: str; expr: Node; line: int = 0
@dataclass
class BinOp(Node):    op: str; left: Node; right: Node; line: int = 0


def dump(n, ind=0):
    """Pretty-print an AST (used by `main.py --ast`)."""
    pad = "  " * ind
    if isinstance(n, list):
        return "".join(dump(x, ind) for x in n)
    if not isinstance(n, Node):
        return f"{pad}{n!r}\n"
    names = [f.name for f in fields(n) if f.name != "line"]
    simple = ", ".join(f"{k}={getattr(n, k)!r}" for k in names
                       if not isinstance(getattr(n, k), (Node, list)))
    out = f"{pad}{type(n).__name__}({simple})\n"
    for k in names:
        v = getattr(n, k)
        if isinstance(v, (Node, list)):
            out += f"{pad}  .{k}\n" + dump(v, ind + 2)
    return out
