from errors import FlowScriptError

KEYWORDS = {
    "START", "END", "SET", "PRINT", "IF", "ELSE", "END_IF",
    "REPEAT", "END_REPEAT", "WAIT", "TURN_ON", "TURN_OFF",
    "DEVICE", "TYPE", "INVARIANT", "REQUIRE", "ENSURE",
    "TRY", "RECOVER", "END_TRY",
    "SYNTHESIZE", "MAX_STEPS", "USING", "FROM",
    "AND", "OR", "NOT",
    "ON", "OFF", "READY", "ERROR",
}


class Token:
    __slots__ = ("type", "value", "line")

    def __init__(self, type_, value, line):
        self.type, self.value, self.line = type_, value, line

    def __repr__(self):
        return f"{self.type}({self.value})" if self.type != "NEWLINE" else "NEWLINE"


class Lexer:
    """Character-by-character scanner with line-number tracking."""

    def __init__(self, source):
        self.src = source

    def tokenize(self):
        src, n, i, line, toks = self.src, len(self.src), 0, 1, []
        while i < n:
            c = src[i]
            if c == "\n":
                toks.append(Token("NEWLINE", "\n", line)); line += 1; i += 1
            elif c in " \t\r":
                i += 1
            elif c == "#":                                   # comment
                while i < n and src[i] != "\n":
                    i += 1
            elif c == '"':                                   # string
                j = i + 1
                while j < n and src[j] not in '"\n':
                    j += 1
                if j >= n or src[j] != '"':
                    raise FlowScriptError("Lexical", "Unterminated string", line)
                toks.append(Token("STRING", src[i + 1:j], line)); i = j + 1
            elif c.isdigit():                                # number
                j = i
                while j < n and (src[j].isdigit() or src[j] == "."):
                    j += 1
                text = src[i:j]
                try:
                    val = float(text) if "." in text else int(text)
                except ValueError:
                    raise FlowScriptError("Lexical", f"Malformed number '{text}'", line)
                toks.append(Token("NUMBER", val, line)); i = j
            elif c.isalpha() or c == "_":                    # keyword / identifier
                j = i
                while j < n and (src[j].isalnum() or src[j] == "_"):
                    j += 1
                word = src[i:j]
                toks.append(Token("KEYWORD" if word in KEYWORDS else "IDENTIFIER", word, line)); i = j
            elif src[i:i + 2] in (">=", "<=", "==", "!="):
                toks.append(Token("OP", src[i:i + 2], line)); i += 2
            elif c in "+-*/><":
                toks.append(Token("OP", c, line)); i += 1
            elif c == "=":
                toks.append(Token("EQUALS", "=", line)); i += 1
            elif c == "(":
                toks.append(Token("LPAREN", c, line)); i += 1
            elif c == ")":
                toks.append(Token("RPAREN", c, line)); i += 1
            elif c == ".":
                toks.append(Token("DOT", ".", line)); i += 1
            elif c == ",":
                toks.append(Token("COMMA", ",", line)); i += 1
            else:
                raise FlowScriptError("Lexical", f"Unknown character '{c}'", line)
        toks.append(Token("EOF", "", line))
        return toks
