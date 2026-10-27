"""FlowScript compiler entry point.

usage: python main.py examples/temperature.flow [--tokens] [--ast] [--ir] [--no-opt] [--realtime] [--telemetry]
"""
import argparse, sys

from lexer.lexer import Lexer
from parser.parser import Parser
from ast_nodes.nodes import dump
from semantic.analyzer import SemanticAnalyzer
from ir.generator import IRGenerator
from optimizer.optimizer import optimize
from synthesis.synthesizer import SynthesizerPass, SynthesisTelemetry
from runtime.vm import VM
from errors import FlowScriptError


def compile_source(source, opt=True, return_telemetry=False):
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    SemanticAnalyzer().analyze(tree)
    synth = SynthesizerPass()
    synth.transform(tree)
    ir = IRGenerator().generate(tree)
    opt_ir = optimize(ir) if opt else ir
    if return_telemetry:
        return tokens, tree, ir, opt_ir, synth.telemetry_log
    return tokens, tree, ir, opt_ir


def execute(source, opt=True, realtime=False, out=print, fault_injector=None):
    *_, code = compile_source(source, opt)
    vm = VM(code, realtime, out, fault_injector=fault_injector)
    vm.run()
    return vm


def main():
    ap = argparse.ArgumentParser(description="FlowScript compiler")
    ap.add_argument("file")
    ap.add_argument("--tokens", action="store_true", help="show token stream")
    ap.add_argument("--ast", action="store_true", help="show AST")
    ap.add_argument("--ir", action="store_true", help="show IR before and after optimization")
    ap.add_argument("--no-opt", action="store_true", help="skip optimizer")
    ap.add_argument("--realtime", action="store_true", help="really sleep on WAIT")
    ap.add_argument("--telemetry", action="store_true", help="output recovery synthesis telemetry (CSV format)")
    ap.add_argument("--fault-device", help="device to inject fault into")
    ap.add_argument("--fault-action", help="action to fault (TURN_ON / TURN_OFF)")
    ap.add_argument("--fault-type", choices=["action_failure", "state_mismatch", "delayed_completion"], default="action_failure", help="type of simulated fault")
    ap.add_argument("--fault-step", type=int, default=1, help="occurrence count to trigger fault")
    ap.add_argument("--fault-delay", type=float, default=2.0, help="delay in seconds for delayed_completion")
    ap.add_argument("--fault-mismatch", default="OFF", help="observed state for state_mismatch")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        with open(a.file, encoding="utf-8") as f:
            src = f.read()
        tokens, tree, ir, opt, telemetry = compile_source(src, not a.no_opt, return_telemetry=True)
        if a.tokens: print("== TOKENS ==\n" + " ".join(map(repr, tokens)) + "\n")
        if a.ast:    print("== AST ==\n" + dump(tree))
        if a.ir:
            print("== IR ==\n" + "\n".join(map(str, ir)))
            print("\n== OPTIMIZED IR ==\n" + "\n".join(map(str, opt)) + "\n")
        if a.telemetry:
            print("== RECOVERY SYNTHESIS TELEMETRY ==")
            print(SynthesisTelemetry.csv_header())
            for record in telemetry:
                print(record.to_csv_row())
            print()
        injector = None
        if a.fault_device:
            from runtime.faults import FaultConfig, FaultRule, FaultInjector
            rule = FaultRule(
                device=a.fault_device,
                action=a.fault_action,
                fault_type=a.fault_type,
                trigger_step=a.fault_step,
                delay_seconds=a.fault_delay,
                mismatch_state=a.fault_mismatch
            )
            injector = FaultInjector(FaultConfig(enabled=True, rules=[rule]))
        vm = VM(opt, a.realtime, fault_injector=injector)
        vm.run()
        if a.telemetry and injector and injector.events:
            print("\n== EXECUTION MONITORING EVENTS ==")
            for evt in injector.events:
                print(f"[{evt.simulated_time:.2f}s] {evt.event_type}: {evt.details} (Outcome: {evt.final_outcome})")
    except FlowScriptError as e:
        print(e, file=sys.stderr); sys.exit(1)
    except OSError as e:
        print(f"Cannot open file: {e}", file=sys.stderr); sys.exit(2)


if __name__ == "__main__":
    main()
