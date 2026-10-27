class FlowScriptError(Exception):
    """Raised by every compiler phase. `kind` is Lexical/Syntax/Semantic/Runtime."""
    def __init__(self, kind, message, line, is_invariant=False):
        super().__init__(message)
        self.kind, self.message, self.line = kind, message, line
        self.is_invariant = is_invariant

    def __str__(self):
        return f"{self.kind} Error [line {self.line}]: {self.message}"


class InvariantViolation(FlowScriptError):
    """Raised when a global safety INVARIANT contract is violated."""
    def __init__(self, message, line):
        super().__init__("Runtime", message, line, is_invariant=True)

