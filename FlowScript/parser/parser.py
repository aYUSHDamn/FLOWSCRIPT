from ast_nodes.nodes import (Program, Assign, Print, If, Repeat, Wait, Device,
                             DeviceDecl, DeviceProperty, StateLiteral,
                             Invariant, Require, Ensure, Try, Synthesize, UnaryOp,
                             Number, String, Var, BinOp)
from errors import FlowScriptError

BLOCK_WORDS = ("END", "ELSE", "END_IF", "END_REPEAT", "RECOVER", "END_TRY")
CMP = (">", "<", ">=", "<=", "==", "!=")

# Grammar
#   program    -> START NL block(END) END
#   statement  -> SET ID = expr | PRINT expr | WAIT expr | TURN_ON ID | TURN_OFF ID
#               | IF expr NL block [ELSE NL block] END_IF
#               | REPEAT expr NL block END_REPEAT
#   expr       -> additive [cmp additive]
#   additive   -> term (('+'|'-') term)*
#   term       -> factor (('*'|'/') factor)*
#   factor     -> NUMBER | STRING | ID | '(' expr ')' | '-' factor


class Parser:
    def __init__(self, tokens):
        self.toks, self.pos = tokens, 0

    # -- helpers -----------------------------------------------------------
    @property
    def cur(self):
        return self.toks[self.pos]

    def advance(self):
        t = self.cur
        if t.type != "EOF":
            self.pos += 1
        return t

    def desc(self, t):
        return {"EOF": "end of file", "NEWLINE": "end of line"}.get(t.type, f"'{t.value}'")

    def err(self, msg):
        raise FlowScriptError("Syntax", msg, self.cur.line)

    def is_kw(self, *names):
        return self.cur.type == "KEYWORD" and self.cur.value in names

    def expect(self, type_):
        if self.cur.type != type_:
            self.err(f"Expected {type_}, found {self.desc(self.cur)}")
        return self.advance()

    def skip_nl(self):
        while self.cur.type == "NEWLINE":
            self.advance()

    def end_stmt(self):
        if self.cur.type == "NEWLINE":
            self.skip_nl()
        elif self.cur.type != "EOF":
            self.err(f"Unexpected {self.desc(self.cur)} after statement")

    # -- structure ---------------------------------------------------------
    def parse(self):
        self.skip_nl()
        if not self.is_kw("START"):
            self.err("Program must begin with START")
        self.advance(); self.end_stmt()
        body = self.block(("END",))
        self.advance()
        self.skip_nl()
        if self.cur.type != "EOF":
            self.err("Unexpected content after END")
        return Program(body)

    def block(self, terms):
        stmts = []
        while True:
            if self.cur.type == "EOF" or (self.is_kw(*BLOCK_WORDS) and not self.is_kw(*terms)):
                self.err(f"Missing {terms[-1]}")
            if self.is_kw(*terms):
                return stmts
            stmts.append(self.statement())

    def statement(self):
        t = self.cur
        if t.type != "KEYWORD":
            self.err(f"Unexpected {self.desc(t)}; expected a statement")
        k, line = t.value, t.line
        self.advance()
        if k == "SET":
            name = self.expect("IDENTIFIER").value
            self.expect("EQUALS")
            node = Assign(name, self.expr(), line)
        elif k == "DEVICE":
            name = self.expect("IDENTIFIER").value
            if not self.is_kw("TYPE") and self.cur.value != "TYPE":
                self.err(f"Expected TYPE after device name, found {self.desc(self.cur)}")
            self.advance()
            dev_type = self.expect("IDENTIFIER").value
            node = DeviceDecl(name, dev_type, line)
        elif k == "PRINT":
            node = Print(self.expr(), line)
        elif k == "WAIT":
            node = Wait(self.expr(), line)
        elif k in ("TURN_ON", "TURN_OFF"):
            node = Device(k, self.expect("IDENTIFIER").value, line)
        elif k == "INVARIANT":
            node = Invariant(self.expr(), line)
        elif k == "REQUIRE":
            node = Require(self.expr(), line)
        elif k == "ENSURE":
            node = Ensure(self.expr(), line)
        elif k == "IF":
            cond = self.expr(); self.end_stmt()
            then, other = self.block(("ELSE", "END_IF")), []
            if self.is_kw("ELSE"):
                self.advance(); self.end_stmt()
                other = self.block(("END_IF",))
            self.advance()
            node = If(cond, then, other, line)
        elif k == "REPEAT":
            count = self.expr(); self.end_stmt()
            body = self.block(("END_REPEAT",))
            self.advance()
            node = Repeat(count, body, line)
        elif k == "TRY":
            self.end_stmt()
            body = self.block(("RECOVER",))
            self.advance()
            if self.is_kw("SYNTHESIZE"):
                synth_node = self.statement()
                recover = [synth_node]
                self.skip_nl()
                if not self.is_kw("END_TRY"):
                    self.err(f"Expected END_TRY after RECOVER SYNTHESIZE, found {self.desc(self.cur)}")
                self.advance()
                node = Try(body, recover, line)
            else:
                self.end_stmt()
                recover = self.block(("END_TRY",))
                self.advance()
                node = Try(body, recover, line)
        elif k == "SYNTHESIZE":
            target = self.expr()
            from_state = None
            if self.is_kw("FROM"):
                self.advance()
                from_state = self.expr()
            using = None
            if self.is_kw("USING"):
                self.advance()
                using = []
                while True:
                    if not self.is_kw("TURN_ON", "TURN_OFF"):
                        self.err(f"Expected TURN_ON or TURN_OFF action in USING clause, found {self.desc(self.cur)}")
                    act = self.advance().value
                    dev = self.expect("IDENTIFIER").value
                    using.append((act, dev))
                    if self.cur.type == "COMMA":
                        self.advance()
                        continue
                    break
            max_steps = None
            if self.is_kw("MAX_STEPS"):
                self.advance()
                max_steps = self.expr()
            node = Synthesize(target, from_state, using, max_steps, line)
        else:
            self.pos -= 1
            self.err(f"Unexpected keyword '{k}'")
        self.end_stmt()
        return node

    # -- expressions -------------------------------------------------------
    def expr(self):
        return self.logic_or()

    def logic_or(self):
        left = self.logic_and()
        while self.is_kw("OR"):
            op = self.advance()
            left = BinOp("OR", left, self.logic_and(), op.line)
        return left

    def logic_and(self):
        left = self.logic_not()
        while self.is_kw("AND"):
            op = self.advance()
            left = BinOp("AND", left, self.logic_not(), op.line)
        return left

    def logic_not(self):
        if self.is_kw("NOT"):
            op = self.advance()
            return UnaryOp("NOT", self.logic_not(), op.line)
        return self.comparison()

    def comparison(self):
        left = self.additive()
        if self.cur.type == "OP" and self.cur.value in CMP:
            op = self.advance()
            left = BinOp(op.value, left, self.additive(), op.line)
        return left

    def additive(self):
        left = self.term()
        while self.cur.type == "OP" and self.cur.value in "+-":
            op = self.advance()
            left = BinOp(op.value, left, self.term(), op.line)
        return left

    def term(self):
        left = self.factor()
        while self.cur.type == "OP" and self.cur.value in "*/":
            op = self.advance()
            left = BinOp(op.value, left, self.factor(), op.line)
        return left

    def factor(self):
        t = self.cur
        if t.type == "NUMBER":
            self.advance(); return Number(t.value, t.line)
        if t.type == "STRING":
            self.advance(); return String(t.value, t.line)
        if self.is_kw("ON", "OFF", "READY", "ERROR"):
            self.advance(); return StateLiteral(t.value, t.line)
        if t.type == "IDENTIFIER":
            self.advance()
            if self.cur.type == "DOT":
                self.advance()
                prop_tok = self.advance()
                if prop_tok.type not in ("IDENTIFIER", "KEYWORD"):
                    self.err(f"Expected property name after '.', found {self.desc(prop_tok)}")
                return DeviceProperty(t.value, prop_tok.value, t.line)
            return Var(t.value, t.line)
        if t.type == "LPAREN":
            self.advance(); e = self.expr(); self.expect("RPAREN"); return e
        if t.type == "OP" and t.value == "-":
            self.advance(); return BinOp("-", Number(0, t.line), self.factor(), t.line)
        self.err(f"Expected a value, found {self.desc(t)}")
