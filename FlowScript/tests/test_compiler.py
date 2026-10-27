import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import compile_source, execute
from errors import FlowScriptError, InvariantViolation
from ir.generator import Instr
from runtime.vm import VM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(body, opt=True):
    out = []
    execute(f"START\n{body}\nEND\n", opt, out=out.append)
    return out


def kind(body):
    try:
        run(body)
    except FlowScriptError as e:
        return e.kind, e.line, e.message
    raise AssertionError("expected error")


class Tests(unittest.TestCase):
    def test_lexer_tokens(self):
        toks, *_ = compile_source("START\nSET a = 35\nEND\n")
        self.assertIn("NUMBER(35)", [repr(t) for t in toks])

    def test_if_else_and_repeat(self):
        for opt in (True, False):
            self.assertEqual(run('SET t = 35\nIF t > 30\nPRINT "hot"\nELSE\nPRINT "ok"\nEND_IF', opt), ["hot"])
            self.assertEqual(run('REPEAT 3\nPRINT "x"\nEND_REPEAT', opt), ["x"] * 3)

    def test_devices(self):
        self.assertEqual(run("TURN_ON fan\nTURN_OFF fan"), ["fan → ON", "fan → OFF"])

    def test_precedence(self):
        self.assertEqual(run("PRINT 2 + 3 * 4"), ["14"])
        self.assertEqual(run("PRINT (2 + 3) * 4"), ["20"])

    def test_optimizer_matches_unoptimized(self):
        src = "SET x = 10\nSET y = x + 5\nIF y > 12\nPRINT y\nELSE\nPRINT 0\nEND_IF"
        self.assertEqual(run(src, True), run(src, False))

    def test_optimizer_folds(self):
        *_, ir, opt = compile_source("START\nSET x = 10\nSET y = x + 5\nEND\n")
        self.assertLess(len(opt), len(ir))
        self.assertIn("PUSH 15", [str(i) for i in opt])

    def test_errors(self):
        self.assertEqual(kind("PRINT temperature")[0], "Semantic")
        self.assertEqual(kind('WAIT "hello"')[2], "WAIT requires a numeric value.")
        self.assertEqual(kind("SET a = 1 | 2")[0], "Lexical")
        self.assertEqual(kind("IF 1 > 0\nPRINT 1")[0], "Syntax")
        self.assertEqual(kind("WAIT 0 - 5")[0:1], ("Runtime",))
        self.assertEqual(kind("PRINT 1 / 0")[2], "Division by zero")

    def test_example_files(self):
        for name in os.listdir(os.path.join(ROOT, "examples")):
            with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
                execute(f.read(), out=lambda s: None)

    def test_temperature_output(self):
        out = []
        with open(os.path.join(ROOT, "examples", "temperature.flow"), encoding="utf-8") as f:
            execute(f.read(), out=out.append)
        self.assertEqual(out, ["Starting temperature monitoring", "Temperature is high", "fan → ON",
                               "Checking...", "Checking...", "Checking...", "fan → OFF",
                               "Monitoring completed"])

    def test_temporary_variable_isolation(self):
        src_seq = "SET __r0 = 999\nREPEAT 2\nPRINT \"loop\"\nEND_REPEAT\nPRINT __r0"
        for opt in (True, False):
            self.assertEqual(run(src_seq, opt), ["loop", "loop", "999"])

        src_nested = ("SET __r0 = 10\nSET __r1 = 20\n"
                      "REPEAT 2\nREPEAT 2\nPRINT \"inner\"\nEND_REPEAT\nEND_REPEAT\n"
                      "PRINT __r0\nPRINT __r1")
        for opt in (True, False):
            self.assertEqual(run(src_nested, opt), ["inner", "inner", "inner", "inner", "10", "20"])

    def test_definite_assignment(self):
        # Assigned on both branches -> valid
        valid_if_else = "SET a = 1\nIF a > 0\nSET x = 10\nELSE\nSET x = 20\nEND_IF\nPRINT x"
        self.assertEqual(run(valid_if_else), ["10"])

        # Assigned only in IF -> invalid
        k, _, msg = kind("SET a = 1\nIF a > 0\nSET x = 10\nEND_IF\nPRINT x")
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

        # Assigned only in ELSE -> invalid
        k, _, msg = kind("SET a = 1\nIF a > 0\nPRINT \"hi\"\nELSE\nSET x = 10\nEND_IF\nPRINT x")
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

        # Assigned only in REPEAT -> invalid after loop
        k, _, msg = kind("REPEAT 3\nSET x = 10\nEND_REPEAT\nPRINT x")
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

        # Variable read before assignment
        k, _, msg = kind("PRINT x\nSET x = 5")
        self.assertEqual(k, "Semantic")
        self.assertIn("not defined", msg)

        # Self-referencing assignment before initialization
        k, _, msg = kind("SET x = x + 1")
        self.assertEqual(k, "Semantic")
        self.assertIn("not defined", msg)

    def test_optimizer_dead_code_with_loops(self):
        src_else_loop = "IF 1 == 1\nPRINT \"live\"\nELSE\nREPEAT 3\nPRINT \"dead\"\nEND_REPEAT\nEND_IF"
        for opt in (True, False):
            self.assertEqual(run(src_else_loop, opt), ["live"])
        *_, opt_ir = compile_source(f"START\n{src_else_loop}\nEND\n", opt=True)
        opt_str = " ".join(str(i) for i in opt_ir)
        self.assertNotIn("dead", opt_str)
        self.assertNotIn("SUB", opt_str)

        src_if_loop = "IF 1 == 2\nREPEAT 3\nPRINT \"dead\"\nEND_REPEAT\nELSE\nPRINT \"live\"\nEND_IF"
        for opt in (True, False):
            self.assertEqual(run(src_if_loop, opt), ["live"])
        *_, opt_ir2 = compile_source(f"START\n{src_if_loop}\nEND\n", opt=True)
        opt_str2 = " ".join(str(i) for i in opt_ir2)
        self.assertNotIn("dead", opt_str2)
        self.assertNotIn("SUB", opt_str2)

    def test_repeat_count_validation(self):
        # Static rejection of fractional literal
        k, _, msg = kind("REPEAT 2.5\nPRINT 1\nEND_REPEAT")
        self.assertEqual(k, "Semantic")
        self.assertEqual(msg, "REPEAT count must be an integer.")

        # Static rejection of negative literal
        k, _, msg = kind("REPEAT -2\nPRINT 1\nEND_REPEAT")
        self.assertEqual(k, "Semantic")
        self.assertEqual(msg, "REPEAT count cannot be negative.")

        # Runtime rejection of dynamic fractional count
        k, _, msg = kind("SET c = 2.5\nREPEAT c\nPRINT 1\nEND_REPEAT")
        self.assertEqual(k, "Runtime")
        self.assertEqual(msg, "REPEAT count must be an integer")

        # Runtime rejection of dynamic negative count
        k, _, msg = kind("SET c = 0 - 2\nREPEAT c\nPRINT 1\nEND_REPEAT")
        self.assertEqual(k, "Runtime")
        self.assertEqual(msg, "REPEAT count cannot be negative")

        # Zero count executes 0 times
        self.assertEqual(run("REPEAT 0\nPRINT 1\nEND_REPEAT\nPRINT 2"), ["2"])

        # Float integer value executes successfully
        self.assertEqual(run("SET c = 3.0\nREPEAT c\nPRINT 1\nEND_REPEAT"), ["1", "1", "1"])

    def test_device_declarations(self):
        # Valid declarations and backwards compatibility
        src = "DEVICE fan TYPE cooling\nDEVICE sensor TYPE sensor\nPRINT 1"
        self.assertEqual(run(src), ["1"])

        # Duplicate device declaration (line 1 is START, line 2 is first, line 3 is dup)
        k, line, msg = kind("DEVICE fan TYPE cooling\nDEVICE fan TYPE cooling")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 3)
        self.assertIn("Duplicate device declaration 'fan'", msg)

        # Device name colliding with existing variable
        k, line, msg = kind("SET pump = 10\nDEVICE pump TYPE actuator")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 3)
        self.assertIn("collides with an existing variable", msg)

        # Variable assigning to declared device
        k, line, msg = kind("DEVICE pump TYPE actuator\nSET pump = 10")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 3)
        self.assertIn("is a declared device", msg)

        # Reading declared device directly as variable
        k, line, msg = kind("DEVICE pump TYPE actuator\nPRINT pump")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 3)
        self.assertIn("Cannot use declared device 'pump' as a variable", msg)

        # Undeclared device reference in property query
        k, line, msg = kind("IF undeclared.status == ON\nPRINT 1\nEND_IF")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 2)
        self.assertIn("Device 'undeclared' is not declared", msg)

    def test_device_state_properties(self):
        # Permitted properties and states
        src = ("DEVICE fan TYPE cooling\n"
               "DEVICE sensor TYPE sensor\n"
               "IF sensor.status == READY\n"
               "    PRINT \"sensor ready\"\n"
               "END_IF\n"
               "IF fan.status == OFF\n"
               "    PRINT \"fan off initially\"\n"
               "END_IF\n"
               "TURN_ON fan\n"
               "IF fan.status == ON\n"
               "    PRINT \"fan on now\"\n"
               "END_IF\n"
               "TURN_OFF fan\n"
               "IF fan.state == OFF\n"
               "    PRINT \"fan off again\"\n"
               "END_IF")
        for opt in (True, False):
            self.assertEqual(run(src, opt), [
                "sensor ready",
                "fan off initially",
                "fan → ON",
                "fan on now",
                "fan → OFF",
                "fan off again",
            ])

        # Reject unknown property
        k, line, msg = kind("DEVICE fan TYPE cooling\nIF fan.speed == ON\nPRINT 1\nEND_IF")
        self.assertEqual(k, "Semantic")
        self.assertEqual(line, 3)
        self.assertIn("Unknown property 'speed'", msg)

        # Reject state compared with number or string
        k1, _, msg1 = kind("DEVICE fan TYPE cooling\nIF fan.status == 10\nPRINT 1\nEND_IF")
        self.assertEqual(k1, "Semantic")
        self.assertIn("Cannot compare state with number", msg1)

        k2, _, msg2 = kind('DEVICE fan TYPE cooling\nIF fan.status == "ON"\nPRINT 1\nEND_IF')
        self.assertEqual(k2, "Semantic")
        self.assertIn("Cannot compare state with string", msg2)

    def test_boolean_logic_and_precedence(self):
        # AND binds tighter than OR: (1 > 0 OR (1 > 0 AND 0 > 1)) -> 1 OR 0 -> 1
        self.assertEqual(run("PRINT 1 > 0 OR 1 > 0 AND 0 > 1"), ["1"])
        # Parentheses override precedence: ((1 > 0 OR 1 > 0) AND 0 > 1) -> 1 AND 0 -> 0
        self.assertEqual(run("PRINT (1 > 0 OR 1 > 0) AND 0 > 1"), ["0"])
        # NOT binds tighter than AND: (NOT 1 > 2) AND 1 > 0 -> 1 AND 1 -> 1
        self.assertEqual(run("PRINT NOT 1 > 2 AND 1 > 0"), ["1"])
        # Parenthesized NOT
        self.assertEqual(run("PRINT NOT (1 > 2 AND 1 > 0)"), ["1"])

        # Type errors for boolean operators
        k, _, msg = kind('PRINT "hello" AND 1')
        self.assertEqual(k, "Semantic")
        self.assertIn("requires boolean or numeric expressions", msg)

        k2, _, msg2 = kind('PRINT NOT "hello"')
        self.assertEqual(k2, "Semantic")
        self.assertIn("requires a boolean or numeric expression", msg2)

    def test_contracts_require_and_ensure(self):
        # Valid REQUIRE and ENSURE
        src = ("DEVICE sensor TYPE sensor\n"
               "REQUIRE sensor.status == READY\n"
               "DEVICE fan TYPE cooling\n"
               "TURN_ON fan\n"
               "ENSURE fan.status == ON\n"
               "PRINT \"ok\"")
        for opt in (True, False):
            self.assertEqual(run(src, opt), ["fan → ON", "ok"])

        # Violated REQUIRE
        k, line, msg = kind("DEVICE fan TYPE cooling\nREQUIRE fan.status == ON\nPRINT 1")
        self.assertEqual(k, "Runtime")
        self.assertEqual(line, 3)
        self.assertIn("REQUIRE contract violated", msg)

        # Violated ENSURE
        k, line, msg = kind("DEVICE fan TYPE cooling\nTURN_OFF fan\nENSURE fan.status == ON")
        self.assertEqual(k, "Runtime")
        self.assertEqual(line, 4)
        self.assertIn("ENSURE contract violated", msg)

        # Semantic error for malformed REQUIRE / ENSURE
        k_sem, _, msg_sem = kind('REQUIRE "not_a_bool"')
        self.assertEqual(k_sem, "Semantic")
        self.assertIn("REQUIRE condition must be a boolean or numeric expression", msg_sem)

    def test_global_invariants(self):
        # Valid invariant checked through safe state transitions
        src_safe = ("DEVICE heater TYPE heating\n"
                    "DEVICE cooler TYPE cooling\n"
                    "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
                    "TURN_ON cooler\n"
                    "PRINT \"cooler on\"\n"
                    "TURN_OFF cooler\n"
                    "TURN_ON heater\n"
                    "PRINT \"heater on\"\n"
                    "TURN_OFF heater\n"
                    "PRINT \"done\"")
        for opt in (True, False):
            self.assertEqual(run(src_safe, opt), [
                "cooler → ON", "cooler on", "cooler → OFF",
                "heater → ON", "heater on", "heater → OFF",
                "done"
            ])

        # Violated invariant upon entering hazard state
        src_hazard = ("DEVICE heater TYPE heating\n"
                      "DEVICE cooler TYPE cooling\n"
                      "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
                      "TURN_ON heater\n"
                      "TURN_ON cooler\n"
                      "PRINT \"unreachable\"")
        k, line, msg = kind(src_hazard)
        self.assertEqual(k, "Runtime")
        self.assertEqual(line, 6)
        self.assertIn("INVARIANT contract violated", msg)

        # Violated invariant at start / initialization
        src_init_fail = ("DEVICE fan TYPE cooling\n"
                         "INVARIANT fan.status == ON\n"
                         "PRINT 1")
        k_init, line_init, msg_init = kind(src_init_fail)
        self.assertEqual(k_init, "Runtime")
        self.assertEqual(line_init, 3)
        self.assertIn("INVARIANT contract violated", msg_init)

    def test_recovery_syntax_validation(self):
        # Missing RECOVER
        k, line, msg = kind("TRY\nPRINT 1\nEND_TRY")
        self.assertEqual(k, "Syntax")
        self.assertEqual(line, 4)
        self.assertIn("Missing RECOVER", msg)

        # Missing END_TRY
        k, line, msg = kind("TRY\nPRINT 1\nRECOVER\nPRINT 2")
        self.assertEqual(k, "Syntax")
        self.assertEqual(line, 6)
        self.assertIn("Missing END_TRY", msg)

        # Duplicate RECOVER
        k, line, msg = kind("TRY\nPRINT 1\nRECOVER\nPRINT 2\nRECOVER\nPRINT 3\nEND_TRY")
        self.assertEqual(k, "Syntax")
        self.assertEqual(line, 6)
        self.assertIn("Missing END_TRY", msg)

        # Standalone RECOVER outside TRY
        k, line, msg = kind("RECOVER\nPRINT 1")
        self.assertEqual(k, "Syntax")
        self.assertEqual(line, 2)
        self.assertIn("Missing END", msg)

        # Standalone END_TRY outside TRY
        k, line, msg = kind("END_TRY")
        self.assertEqual(k, "Syntax")
        self.assertEqual(line, 2)
        self.assertIn("Missing END", msg)

    def test_recovery_definite_assignment(self):
        # Assigned on both TRY and RECOVER -> definitely assigned after END_TRY
        src_both = ("TRY\n"
                    "    SET x = 10\n"
                    "RECOVER\n"
                    "    SET x = 20\n"
                    "END_TRY\n"
                    "PRINT x")
        self.assertEqual(run(src_both), ["10"])

        # Assigned only in TRY -> NOT definitely assigned after END_TRY
        src_try_only = ("TRY\n"
                        "    SET x = 10\n"
                        "RECOVER\n"
                        "    PRINT \"rec\"\n"
                        "END_TRY\n"
                        "PRINT x")
        k, _, msg = kind(src_try_only)
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

        # Assigned only in RECOVER -> NOT definitely assigned after END_TRY
        src_rec_only = ("TRY\n"
                        "    PRINT \"try\"\n"
                        "RECOVER\n"
                        "    SET x = 20\n"
                        "END_TRY\n"
                        "PRINT x")
        k, _, msg = kind(src_rec_only)
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

        # Variable assigned in TRY cannot be read in RECOVER (it may fail before assignment)
        src_try_read_rec = ("TRY\n"
                            "    SET y = 5\n"
                            "    REQUIRE 1 == 0\n"
                            "RECOVER\n"
                            "    PRINT y\n"
                            "END_TRY")
        k, _, msg = kind(src_try_read_rec)
        self.assertEqual(k, "Semantic")
        self.assertIn("not definitely assigned", msg)

    def test_recovery_execution_and_skip_on_success(self):
        # When TRY succeeds, RECOVER is skipped
        src_success = ("DEVICE fan TYPE cooling\n"
                       "TRY\n"
                       "    REQUIRE fan.status == OFF\n"
                       "    TURN_ON fan\n"
                       "    ENSURE fan.status == ON\n"
                       "RECOVER\n"
                       "    PRINT \"should_not_run\"\n"
                       "    TURN_OFF fan\n"
                       "END_TRY\n"
                       "PRINT \"done\"")
        for opt in (True, False):
            self.assertEqual(run(src_success, opt), ["fan → ON", "done"])

        # When REQUIRE fails, RECOVER executes and preserves prior device state
        src_req_fail = ("DEVICE heater TYPE heating\n"
                        "DEVICE backup_cooler TYPE cooling\n"
                        "TRY\n"
                        "    REQUIRE backup_cooler.status == ON\n"
                        "    TURN_ON heater\n"
                        "RECOVER\n"
                        "    PRINT \"recovery started\"\n"
                        "    TURN_ON backup_cooler\n"
                        "END_TRY\n"
                        "PRINT \"workflow continuing\"")
        for opt in (True, False):
            self.assertEqual(run(src_req_fail, opt), [
                "recovery started",
                "backup_cooler → ON",
                "workflow continuing",
            ])

        # When ENSURE fails, RECOVER executes and prior actions in TRY are preserved
        src_ens_fail = ("DEVICE heater TYPE heating\n"
                        "DEVICE cooler TYPE cooling\n"
                        "TRY\n"
                        "    TURN_ON heater\n"
                        "    ENSURE heater.status == OFF\n"
                        "RECOVER\n"
                        "    IF heater.status == ON\n"
                        "        PRINT \"heater was on, safe shutdown\"\n"
                        "        TURN_OFF heater\n"
                        "        TURN_ON cooler\n"
                        "    END_IF\n"
                        "END_TRY\n"
                        "PRINT \"safe\"")
        for opt in (True, False):
            self.assertEqual(run(src_ens_fail, opt), [
                "heater → ON",
                "heater was on, safe shutdown",
                "heater → OFF",
                "cooler → ON",
                "safe",
            ])

        # Runtime errors in TRY (like division by zero) trigger RECOVER
        src_rt_fail = ("TRY\n"
                       "    SET z = 10 / 0\n"
                       "RECOVER\n"
                       "    PRINT \"caught div by zero\"\n"
                       "END_TRY")
        for opt in (True, False):
            self.assertEqual(run(src_rt_fail, opt), ["caught div by zero"])

    def test_recovery_error_chaining_when_recovery_fails(self):
        # Recovery itself fails: reports both errors with exact lines
        src = ("TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SET err = 10 / 0\n"
               "END_TRY")
        k, line, msg = kind(src)
        self.assertEqual(k, "Runtime")
        self.assertEqual(line, 5)
        self.assertIn("Recovery failed [line 5]: Division by zero", msg)
        self.assertIn("original error in TRY [line 3]: REQUIRE contract violated [line 3]", msg)

    def test_recovery_invariant_violations_fail_closed(self):
        # Global INVARIANT violated in TRY: must NOT be caught by RECOVER
        src_in_try = ("DEVICE heater TYPE heating\n"
                      "INVARIANT heater.status == OFF\n"
                      "TRY\n"
                      "    TURN_ON heater\n"
                      "RECOVER\n"
                      "    PRINT \"should never catch invariant\"\n"
                      "END_TRY")
        k, line, msg = kind(src_in_try)
        self.assertEqual(k, "Runtime")
        self.assertEqual(line, 5)
        self.assertIn("INVARIANT contract violated [line 3]", msg)

        # Global INVARIANT violated during RECOVER: must fail closed immediately
        src_in_rec = ("DEVICE heater TYPE heating\n"
                      "INVARIANT heater.status == OFF\n"
                      "TRY\n"
                      "    REQUIRE 1 == 0\n"
                      "RECOVER\n"
                      "    TURN_ON heater\n"
                      "END_TRY")
        k2, line2, msg2 = kind(src_in_rec)
        self.assertEqual(k2, "Runtime")
        self.assertEqual(line2, 7)
        self.assertIn("INVARIANT contract violated [line 3]", msg2)

    def test_nested_recovery_blocks(self):
        # Nested TRY in TRY body
        src_nested = ("TRY\n"
                      "    TRY\n"
                      "        REQUIRE 1 == 0\n"
                      "    RECOVER\n"
                      "        PRINT \"inner recovered\"\n"
                      "    END_TRY\n"
                      "    PRINT \"outer body continuing\"\n"
                      "RECOVER\n"
                      "    PRINT \"outer recovered\"\n"
                      "END_TRY\n"
                      "PRINT \"all done\"")
        for opt in (True, False):
            self.assertEqual(run(src_nested, opt), [
                "inner recovered",
                "outer body continuing",
                "all done"
            ])

        # Nested TRY in RECOVER block
        src_rec_nest = ("TRY\n"
                        "    REQUIRE 1 == 0\n"
                        "RECOVER\n"
                        "    TRY\n"
                        "        REQUIRE 2 == 0\n"
                        "    RECOVER\n"
                        "        PRINT \"inner in recover ok\"\n"
                        "    END_TRY\n"
                        "    PRINT \"outer recover ok\"\n"
                        "END_TRY")
        for opt in (True, False):
            self.assertEqual(run(src_rec_nest, opt), [
                "inner in recover ok",
                "outer recover ok"
            ])

        # Inner recovery fails, caught and handled by outer recovery
        src_chain_handled = ("TRY\n"
                             "    TRY\n"
                             "        REQUIRE 1 == 0\n"
                             "    RECOVER\n"
                             "        REQUIRE 2 == 0\n"
                             "    END_TRY\n"
                             "RECOVER\n"
                             "    PRINT \"outer handled inner recovery failure\"\n"
                             "END_TRY")
        for opt in (True, False):
            self.assertEqual(run(src_chain_handled, opt), [
                "outer handled inner recovery failure"
            ])

    def test_typed_invariant_violation_and_nested_fail_closed(self):
        # 1. InvariantViolation is raised and is an instance of FlowScriptError with is_invariant=True
        src_direct = ("DEVICE fan TYPE cooling\n"
                      "INVARIANT fan.status == ON\n"
                      "PRINT 1")
        try:
            run(src_direct)
            self.fail("Expected InvariantViolation")
        except FlowScriptError as e:
            self.assertIsInstance(e, InvariantViolation)
            self.assertTrue(getattr(e, "is_invariant", False))
            self.assertEqual(e.kind, "Runtime")
            self.assertEqual(e.line, 3)

        # 2. Invariant violation inside nested TRY body cannot be caught by inner or outer RECOVER
        src_nested_try = ("DEVICE heater TYPE heating\n"
                          "INVARIANT heater.status == OFF\n"
                          "TRY\n"
                          "    TRY\n"
                          "        TURN_ON heater\n"
                          "    RECOVER\n"
                          "        PRINT \"inner caught\"\n"
                          "    END_TRY\n"
                          "RECOVER\n"
                          "    PRINT \"outer caught\"\n"
                          "END_TRY")
        try:
            run(src_nested_try)
            self.fail("Expected InvariantViolation")
        except FlowScriptError as e:
            self.assertIsInstance(e, InvariantViolation)
            self.assertTrue(e.is_invariant)
            self.assertIn("INVARIANT contract violated", e.message)

        # 3. Invariant violation inside nested RECOVER block cannot be caught by outer RECOVER
        src_nested_rec = ("DEVICE heater TYPE heating\n"
                          "INVARIANT heater.status == OFF\n"
                          "TRY\n"
                          "    TRY\n"
                          "        REQUIRE 1 == 0\n"
                          "    RECOVER\n"
                          "        TURN_ON heater\n"
                          "    END_TRY\n"
                          "RECOVER\n"
                          "    PRINT \"outer caught\"\n"
                          "END_TRY")
        try:
            run(src_nested_rec)
            self.fail("Expected InvariantViolation")
        except FlowScriptError as e:
            self.assertIsInstance(e, InvariantViolation)
            self.assertTrue(e.is_invariant)
            self.assertIn("INVARIANT contract violated", e.message)

    def test_unrecognized_opcode_rejection(self):
        # Standalone unknown instruction raises FlowScriptError with opcode and line
        bad_code = [Instr("CORRUPTED_OPCODE", None, 77)]
        vm = VM(bad_code)
        with self.assertRaises(FlowScriptError) as ctx:
            vm.run()
        self.assertEqual(ctx.exception.kind, "Runtime")
        self.assertEqual(ctx.exception.line, 77)
        self.assertIn("Unknown instruction 'CORRUPTED_OPCODE'", ctx.exception.message)

        # Unknown instruction inside TRY is caught and handled by RECOVER
        bad_try_code = [
            Instr("SETUP_RECOVER", "L_REC", 1),
            Instr("CORRUPTED_OPCODE", None, 2),
            Instr("POP_RECOVER", None, 3),
            Instr("JUMP", "L_END", 4),
            Instr("LABEL", "L_REC", 5),
            Instr("PUSH", "handled_corrupted_op", 6),
            Instr("PRINT", None, 7),
            Instr("CLEAR_TRY_ERROR", None, 8),
            Instr("LABEL", "L_END", 9),
        ]
        out = []
        vm2 = VM(bad_try_code, out=out.append)
        vm2.run()
        self.assertEqual(out, ["handled_corrupted_op"])

        # LABEL pseudo-instruction executes as clean no-op
        label_code = [
            Instr("LABEL", "L_START", 1),
            Instr("PUSH", 42, 2),
            Instr("PRINT", None, 3),
            Instr("LABEL", "L_FINISH", 4),
        ]
        out_lbl = []
        vm3 = VM(label_code, out=out_lbl.append)
        vm3.run()
        self.assertEqual(out_lbl, ["42"])

    def test_synthesis_finds_valid_plan(self):
        # 1. Block-style SYNTHESIZE
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE heater.status == OFF AND cooler.status == ON\n"
               "END_TRY\n"
               "REQUIRE heater.status == OFF\n"
               "REQUIRE cooler.status == ON\n"
               "PRINT \"ok\"")
        self.assertEqual(run(src), ["heater → ON", "cooler → ON", "heater → OFF", "ok"])

        # 2. Inline RECOVER SYNTHESIZE
        src_inline = ("DEVICE heater TYPE heating\n"
                      "TURN_ON heater\n"
                      "TRY\n"
                      "    REQUIRE 1 == 0\n"
                      "RECOVER SYNTHESIZE heater.status == OFF\n"
                      "END_TRY\n"
                      "REQUIRE heater.status == OFF\n"
                      "PRINT \"ok_inline\"")
        self.assertEqual(run(src_inline), ["heater → ON", "heater → OFF", "ok_inline"])

    def test_synthesis_rejects_plan_violating_invariants(self):
        # Invariant: heater and cooler cannot be ON at same time
        # Starting with heater == ON. Goal: cooler == ON.
        # If approved actions only allow TURN_ON cooler, synthesis fails closed!
        src_fail = ("DEVICE heater TYPE heating\n"
                    "DEVICE cooler TYPE cooling\n"
                    "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
                    "TURN_ON heater\n"
                    "TRY\n"
                    "    REQUIRE 1 == 0\n"
                    "RECOVER\n"
                    "    SYNTHESIZE cooler.status == ON USING TURN_ON cooler MAX_STEPS 3\n"
                    "END_TRY")
        k, _, msg = kind(src_fail)
        self.assertEqual(k, "Synthesis")
        self.assertIn("No safe recovery plan found", msg)

        # But if TURN_OFF heater is also approved, it turns OFF heater first!
        src_pass = ("DEVICE heater TYPE heating\n"
                    "DEVICE cooler TYPE cooling\n"
                    "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
                    "TURN_ON heater\n"
                    "TRY\n"
                    "    REQUIRE 1 == 0\n"
                    "RECOVER\n"
                    "    SYNTHESIZE cooler.status == ON USING TURN_OFF heater, TURN_ON cooler MAX_STEPS 3\n"
                    "END_TRY\n"
                    "REQUIRE cooler.status == ON\n"
                    "REQUIRE heater.status == OFF\n"
                    "PRINT \"safe\"")
        self.assertEqual(run(src_pass), ["heater → ON", "heater → OFF", "cooler → ON", "safe"])

    def test_synthesis_enforces_approved_actions_only(self):
        # Target requires turning on cooler, but USING only permits heater actions
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE cooler.status == ON USING TURN_ON heater, TURN_OFF heater\n"
               "END_TRY")
        k, _, msg = kind(src)
        self.assertEqual(k, "Synthesis")
        self.assertIn("No safe recovery plan found", msg)

    def test_synthesis_budget_exhaustion(self):
        # Moving from (heater=ON, cooler=OFF) to (heater=OFF, cooler=ON) requires 2 steps.
        # Budget = 1 step -> fails
        src_budget1 = ("DEVICE heater TYPE heating\n"
                       "DEVICE cooler TYPE cooling\n"
                       "TURN_ON heater\n"
                       "TRY\n"
                       "    REQUIRE 1 == 0\n"
                       "RECOVER\n"
                       "    SYNTHESIZE heater.status == OFF AND cooler.status == ON MAX_STEPS 1\n"
                       "END_TRY")
        k, _, msg = kind(src_budget1)
        self.assertEqual(k, "Synthesis")
        self.assertIn("within 1 steps", msg)

        # Budget = 2 steps -> succeeds
        src_budget2 = ("DEVICE heater TYPE heating\n"
                       "DEVICE cooler TYPE cooling\n"
                       "TURN_ON heater\n"
                       "TRY\n"
                       "    REQUIRE 1 == 0\n"
                       "RECOVER\n"
                       "    SYNTHESIZE heater.status == OFF AND cooler.status == ON MAX_STEPS 2\n"
                       "END_TRY\n"
                       "PRINT \"budget2_ok\"")
        self.assertEqual(run(src_budget2), ["heater → ON", "cooler → ON", "heater → OFF", "budget2_ok"])

    def test_synthesis_unreachable_target_fails_cleanly(self):
        # Target condition contradicts itself
        src = ("DEVICE heater TYPE heating\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE heater.status == ON AND heater.status == OFF\n"
               "END_TRY")
        k, _, msg = kind(src)
        self.assertEqual(k, "Synthesis")
        self.assertIn("No safe recovery plan found", msg)

    def test_synthesis_determinism(self):
        src = ("START\n"
               "DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "DEVICE backup TYPE cooling\n"
               "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE backup.status == ON AND heater.status == OFF\n"
               "END_TRY\n"
               "END\n")
        # Run 5 iterations: ast, plan, and telemetry metrics must be identical
        first_tokens, first_tree, first_ir, first_opt, first_telem = compile_source(src, return_telemetry=True)
        for _ in range(4):
            tok, tr, ir, opt, telem = compile_source(src, return_telemetry=True)
            self.assertEqual([str(i) for i in opt], [str(i) for i in first_opt])
            self.assertEqual(telem[0].plan, first_telem[0].plan)
            self.assertEqual(telem[0].states_explored, first_telem[0].states_explored)
            self.assertEqual(telem[0].transitions_rejected, first_telem[0].transitions_rejected)

    def test_synthesis_opt_and_no_opt_match(self):
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE heater.status == OFF AND cooler.status == ON\n"
               "END_TRY\n"
               "PRINT \"done\"")
        self.assertEqual(run(src, opt=True), run(src, opt=False))

    def test_synthesis_telemetry(self):
        src = ("START\n"
               "DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE cooler.status == ON AND heater.status == OFF MAX_STEPS 4\n"
               "END_TRY\n"
               "END\n")
        *_, telem = compile_source(src, return_telemetry=True)
        self.assertEqual(len(telem), 1)
        t = telem[0]
        self.assertTrue(t.success)
        self.assertEqual(t.budget, 4)
        self.assertGreater(t.states_explored, 0)
        self.assertGreaterEqual(t.transitions_rejected, 1)  # At least one transition rejected due to invariant
        self.assertGreaterEqual(t.duration_ms, 0)
        self.assertIn("TURN_OFF heater", t.plan)
        self.assertIn("TURN_ON cooler", t.plan)
        # Check dict export
        d = t.to_dict()
        self.assertIn("states_explored", d)
        self.assertIn("plan", d)
        # Check CSV export
        csv_row = t.to_csv_row()
        self.assertIn("cooler.status == ON", csv_row)

    def test_synthesis_explicit_from_state(self):
        # Initial code has heater OFF, but FROM clause specifies failure state has heater ON
        src = ("DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE cooler.status == ON FROM heater.status == ON AND cooler.status == OFF\n"
               "END_TRY")
        *_, telem = compile_source(f"START\n{src}\nEND\n", return_telemetry=True)
        self.assertEqual(telem[0].initial_state["heater"], "ON")
        self.assertEqual(telem[0].initial_state["cooler"], "OFF")

    def test_synthesis_semantic_validation(self):
        # 1. Undeclared device in USING
        src_undec = ("DEVICE heater TYPE heating\n"
                     "TRY\nREQUIRE 1 == 0\nRECOVER\n"
                     "SYNTHESIZE heater.status == OFF USING TURN_OFF undeclared_dev\n"
                     "END_TRY")
        k, _, msg = kind(src_undec)
        self.assertEqual(k, "Semantic")
        self.assertIn("Device 'undeclared_dev' in USING clause is not declared.", msg)

        # 2. Cannot actuate sensor in USING
        src_sensor = ("DEVICE temp_sens TYPE sensor\n"
                      "TRY\nREQUIRE 1 == 0\nRECOVER\n"
                      "SYNTHESIZE 1 == 1 USING TURN_ON temp_sens\n"
                      "END_TRY")
        k, _, msg = kind(src_sensor)
        self.assertEqual(k, "Semantic")
        self.assertIn("Cannot actuate sensor 'temp_sens'", msg)

        # 3. Non-integer or negative MAX_STEPS
        src_neg = ("DEVICE heater TYPE heating\n"
                   "TRY\nREQUIRE 1 == 0\nRECOVER\n"
                   "SYNTHESIZE heater.status == OFF MAX_STEPS 0 - 2\n"
                   "END_TRY")
        k, _, msg = kind(src_neg)
        self.assertEqual(k, "Semantic")
        self.assertIn("cannot be negative", msg)


if __name__ == "__main__":
    unittest.main()
