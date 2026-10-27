from ir.generator import Instr, BINOPS

# Passes (repeated until nothing changes):
#   * constant propagation   LOAD x  ->  PUSH <known value>   (per basic block)
#   * constant folding       PUSH a; PUSH b; ADD  ->  PUSH a+b
#   * dead code elimination  constant branches, code after JUMP, unused labels,
#                            JUMP to the next instruction


def eliminate_unreachable(code):
    """Prune instructions unreachable from the program entry point (index 0)."""
    if not code:
        return []
    label_idx = {ins.arg: k for k, ins in enumerate(code) if ins.op == "LABEL"}
    reachable = set()
    queue = [0]
    while queue:
        idx = queue.pop()
        if idx < 0 or idx >= len(code) or idx in reachable:
            continue
        reachable.add(idx)
        ins = code[idx]
        if ins.op == "JUMP":
            if ins.arg in label_idx:
                queue.append(label_idx[ins.arg])
        elif ins.op in ("JUMP_IF_FALSE", "SETUP_RECOVER"):
            if ins.arg in label_idx:
                queue.append(label_idx[ins.arg])
            queue.append(idx + 1)
        else:
            queue.append(idx + 1)
    return [ins for k, ins in enumerate(code) if k in reachable]


def _pass(code):
    code = eliminate_unreachable(code)
    out, known, dead = [], {}, False
    for ins in code:
        if ins.op == "LABEL":
            dead, known = False, {}
            out.append(ins); continue
        if dead:
            continue
        if ins.op == "LOAD" and ins.arg in known:
            ins = Instr("PUSH", known[ins.arg], ins.line)
        if ins.op == "CHECK_REPEAT_COUNT" and out and out[-1].op == "PUSH":
            val = out[-1].arg
            if isinstance(val, bool) or not isinstance(val, (int, float)) or (isinstance(val, float) and not val.is_integer()) or val < 0:
                out.append(ins); continue
            out[-1] = Instr("PUSH", int(val), ins.line)
            continue
        if ins.op == "NOT" and out and out[-1].op == "PUSH":
            val = out[-1].arg
            out[-1] = Instr("PUSH", 0 if val else 1, ins.line)
            continue
        if ins.op in BINOPS and len(out) >= 2 and out[-1].op == "PUSH" == out[-2].op:
            try:
                val = BINOPS[ins.op](out[-2].arg, out[-1].arg)
            except (ZeroDivisionError, TypeError):
                out.append(ins); continue            # leave for the runtime to report
            del out[-2:]
            out.append(Instr("PUSH", val, ins.line)); continue
        if ins.op == "STORE":
            if out and out[-1].op == "PUSH":
                known[ins.arg] = out[-1].arg
            else:
                known.pop(ins.arg, None)
        elif ins.op == "JUMP_IF_FALSE" and out and out[-1].op == "PUSH":
            cond = out.pop().arg
            if cond:
                continue                              # never jumps
            ins = Instr("JUMP", ins.arg, ins.line)    # always jumps
        if ins.op == "JUMP":
            dead = True
        out.append(ins)

    out = eliminate_unreachable(out)
    refs = {i.arg for i in out if i.op in ("JUMP", "JUMP_IF_FALSE", "SETUP_RECOVER")}
    final = []
    for k, i in enumerate(out):
        if i.op == "LABEL" and i.arg not in refs:
            continue
        nxt = out[k + 1] if k + 1 < len(out) else None
        if i.op == "JUMP" and nxt and nxt.op == "LABEL" and nxt.arg == i.arg:
            continue
        final.append(i)
    return eliminate_unreachable(final)


def optimize(code):
    while True:
        new = _pass(code)
        if [(i.op, i.arg) for i in new] == [(i.op, i.arg) for i in code]:
            return new
        code = new
