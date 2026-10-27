"""FlowScript Studio Backend Server.

Provides a robust, zero-external-dependency local HTTP server and REST API
for compiling FlowScript workflows, executing them on the simulated virtual machine,
and inspecting compiler stages and synthesis telemetry.

Usage:
    python server.py [--host HOST] [--port PORT]
"""

import argparse
import http.server
import json
import mimetypes
import os
import socketserver
import sys
import time
from typing import Dict, Any, Tuple, Optional

# Ensure project root is on sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

WEB_DIR = os.path.join(ROOT_DIR, "web")
EXAMPLES_DIR = os.path.join(ROOT_DIR, "examples")

from lexer.lexer import Lexer
from parser.parser import Parser
from ast_nodes.nodes import dump
from semantic.analyzer import SemanticAnalyzer
from ir.generator import IRGenerator
from optimizer.optimizer import optimize
from synthesis.synthesizer import SynthesizerPass, SynthesisTelemetry
from runtime.vm import VM
from runtime.faults import FaultConfig, FaultInjector, FaultType, FaultRule
from errors import FlowScriptError, InvariantViolation


MAX_PAYLOAD_BYTES = 256 * 1024  # 256 KB safety limit


def explain_diagnostic(kind: str, message: str) -> str:
    """Return a helpful, beginner-friendly explanation and fix suggestion."""
    msg_lower = message.lower()
    if "variable" in msg_lower and "not defined" in msg_lower:
        return "Declare and initialize variables using 'SET <name> = <value>' before using them."
    if "definitely assigned" in msg_lower:
        return "Ensure the variable is initialized along all conditional execution paths before reading it."
    if "missing end_if" in msg_lower:
        return "Every 'IF' statement requires a closing 'END_IF' keyword."
    if "missing end_repeat" in msg_lower:
        return "Every 'REPEAT' loop requires a closing 'END_REPEAT' keyword."
    if "missing end_try" in msg_lower:
        return "Every 'TRY' block must be completed with 'RECOVER' and closed with 'END_TRY'."
    if "invariant contract violated" in msg_lower:
        return "A global safety invariant was violated. Global invariants must hold across all device state changes."
    if "require contract violated" in msg_lower:
        return "A local REQUIRE precondition failed. If inside a TRY block, control transfers to RECOVER."
    if "ensure contract violated" in msg_lower:
        return "A local ENSURE postcondition failed. Check that the preceding actions achieved the expected state."
    if "no safe recovery plan found" in msg_lower:
        return "The compiler's bounded search could not find an action sequence that reaches the target safely without violating invariants within the step budget."
    if "division by zero" in msg_lower:
        return "Arithmetic division by zero is undefined. Ensure the denominator evaluates to a non-zero value."
    if "cannot actuate sensor" in msg_lower:
        return "Sensors are read-only devices that supply continuous observations; they cannot be actuated."
    if "unknown instruction" in msg_lower:
        return "The VM encountered an unrecognized bytecode instruction."
    if "instruction limit" in msg_lower:
        return "The workflow exceeded the maximum permitted instruction limit. Check for infinite loops."
    if "timeout" in msg_lower:
        return "Workflow execution exceeded the allowed runtime timeout limit."
    if "simulated actuation failure" in msg_lower or "actuation fault" in msg_lower:
        return "Injected simulated fault: device actuation failed. If protected by TRY, execution routes to RECOVER."
    return "Check the syntax and semantics at the indicated source line."


def compile_pipeline(source: str, opt: bool = True) -> Dict[str, Any]:
    """Compile FlowScript source code and capture all intermediate representations."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    SemanticAnalyzer().analyze(tree)
    synth = SynthesizerPass()
    synth.transform(tree)
    ir = IRGenerator().generate(tree)
    opt_ir = optimize(ir) if opt else ir

    # Serialize tokens
    tok_list = [{"type": t.type, "value": str(t.value), "line": t.line} for t in tokens]

    # Serialize IR
    ir_list = [{"index": idx, "op": ins.op, "arg": None if ins.arg is None else str(ins.arg), "line": ins.line, "text": str(ins)} for idx, ins in enumerate(ir)]
    opt_ir_list = [{"index": idx, "op": ins.op, "arg": None if ins.arg is None else str(ins.arg), "line": ins.line, "text": str(ins)} for idx, ins in enumerate(opt_ir)]

    reduction = len(ir) - len(opt_ir)
    reduction_pct = round((reduction / len(ir) * 100), 1) if ir else 0.0

    return {
        "success": True,
        "tokens": tok_list,
        "ast": dump(tree),
        "ir": ir_list,
        "optimized_ir": opt_ir_list,
        "opt_stats": {
            "original_count": len(ir),
            "optimized_count": len(opt_ir),
            "reduction_count": reduction,
            "reduction_pct": reduction_pct
        },
        "telemetry": [t.to_dict() for t in synth.telemetry_log],
        "diagnostics": []
    }


def run_pipeline(
    source: str,
    opt: bool = True,
    timeout: float = 5.0,
    max_instructions: int = 200000,
    fault_config: Optional[FaultConfig] = None
) -> Dict[str, Any]:
    """Compile and execute FlowScript source code on the simulated VM with optional fault injection."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    SemanticAnalyzer().analyze(tree)
    synth = SynthesizerPass()
    synth.transform(tree)
    ir = IRGenerator().generate(tree)
    code = optimize(ir) if opt else ir

    output_lines = []
    device_events = []
    t_start = time.perf_counter()

    def out_callback(msg: str):
        output_lines.append(msg)
        if " → " in msg:
            parts = msg.split(" → ")
            if len(parts) == 2:
                device_events.append({
                    "device": parts[0].strip(),
                    "state": parts[1].strip(),
                    "timestamp_ms": round((time.perf_counter() - t_start) * 1000, 2)
                })

    injector = FaultInjector(fault_config) if fault_config else None
    vm = VM(
        code,
        realtime=False,
        out=out_callback,
        max_instructions=max_instructions,
        timeout_sec=timeout,
        fault_injector=injector
    )
    try:
        vm.run()
    except FlowScriptError as e:
        dur_ms = (time.perf_counter() - t_start) * 1000
        is_inv = isinstance(e, InvariantViolation) or getattr(e, "is_invariant", False)
        return {
            "success": False,
            "output": output_lines,
            "device_events": device_events,
            "final_devices": vm.devices,
            "final_vars": {k: v for k, v in vm.vars.items() if not k.startswith("__r")},
            "simulated_time": vm.simulated_time,
            "instructions_executed": vm.instruction_count,
            "duration_ms": round(dur_ms, 3),
            "telemetry": [t.to_dict() for t in synth.telemetry_log],
            "execution_events": [e.to_dict() for e in vm.execution_events],
            "fault_summary": vm.fault_summary,
            "opt": opt,
            "diagnostics": [{
                "kind": e.kind,
                "message": e.message,
                "line": e.line,
                "is_invariant": is_inv,
                "suggestion": explain_diagnostic(e.kind, e.message)
            }]
        }

    dur_ms = (time.perf_counter() - t_start) * 1000

    return {
        "success": True,
        "output": output_lines,
        "device_events": device_events,
        "final_devices": vm.devices,
        "final_vars": {k: v for k, v in vm.vars.items() if not k.startswith("__r")},
        "simulated_time": vm.simulated_time,
        "instructions_executed": vm.instruction_count,
        "duration_ms": round(dur_ms, 3),
        "telemetry": [t.to_dict() for t in synth.telemetry_log],
        "execution_events": [e.to_dict() for e in vm.execution_events],
        "fault_summary": vm.fault_summary,
        "opt": opt,
        "diagnostics": []
    }


# Curated example programs
CURATED_EXAMPLES = [
    {
        "id": "temperature",
        "name": "Temperature Monitoring",
        "category": "Basic Workflows",
        "badge": "Beginner",
        "description": "Sensors and threshold checks: evaluate temperature, actuate a fan, and poll simulated status in a loop.",
        "filename": "temperature.flow"
    },
    {
        "id": "optimization_demo",
        "name": "Constant Folding & Dead Code",
        "category": "Compiler Optimization",
        "badge": "Intermediate",
        "description": "Inspect how the FlowScript optimizer folds arithmetic constants and eliminates dead conditional branches.",
        "filename": "optimization_demo.flow"
    },
    {
        "id": "recovery_demo",
        "name": "Explicit Fault Recovery",
        "category": "Fault Recovery",
        "badge": "Advanced",
        "description": "Structured TRY / RECOVER blocks: detect failed preconditions (REQUIRE) and trigger deterministic manual fallback procedures.",
        "filename": "recovery_demo.flow"
    },
    {
        "id": "fault_recovery_demo",
        "name": "Fault Injection & Monitoring",
        "category": "Fault Recovery",
        "badge": "Phase 4",
        "description": "Inject simulated hardware actuation failures, contract state mismatches, or delays, and observe automated self-healing telemetry.",
        "filename": "fault_recovery_demo.flow"
    },
    {
        "id": "synthesis_demo",
        "name": "Safety-Constrained Synthesis",
        "category": "Automated Synthesis",
        "badge": "Research",
        "description": "Compiler-synthesized recovery: BFS automatically generates the shortest sequence of approved actions that satisfies goals without violating global invariants.",
        "filename": "synthesis_demo.flow"
    },
    {
        "id": "synthesis_failure",
        "name": "Hazardous State (Fail-Closed)",
        "category": "Research Demonstration",
        "badge": "Safety Proof",
        "description": "Proves that the compiler rejects unsafe action requests and fails closed when global invariants strictly prevent actuation.",
        "embedded_source": (
            "START\n"
            "# Research Demonstration: Fail-Closed Safety Verification\n"
            "# In this scenario, heater is ON and a fault occurs.\n"
            "# The target requires cooler to be ON, but the global safety invariant\n"
            "# forbids heater and cooler from being ON simultaneously.\n"
            "# Because TURN_OFF heater is NOT in the approved actions list,\n"
            "# NO safe plan exists. The compiler must FAIL CLOSED.\n"
            "DEVICE heater TYPE heating\n"
            "DEVICE cooler TYPE cooling\n"
            "\n"
            "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
            "\n"
            "TURN_ON heater\n"
            "TRY\n"
            "    PRINT \"Attempting operation requiring cooling\"\n"
            "    REQUIRE 1 == 0\n"
            "RECOVER\n"
            "    # Only TURN_ON cooler is approved; turning off heater is forbidden!\n"
            "    # Compilation will fail closed with a clean diagnostic error.\n"
            "    SYNTHESIZE cooler.status == ON USING TURN_ON cooler MAX_STEPS 3\n"
            "END_TRY\n"
            "END\n"
        )
    }
]


def get_example_source(example_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve example metadata and source code."""
    for ex in CURATED_EXAMPLES:
        if ex["id"] == example_id:
            res = dict(ex)
            if "embedded_source" in ex:
                res["source"] = ex["embedded_source"]
            elif "filename" in ex:
                path = os.path.join(EXAMPLES_DIR, ex["filename"])
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        res["source"] = f.read()
                else:
                    return None
            return res
    return None


class FlowScriptHTTPHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request Handler for FlowScript Studio API and Static Assets."""

    server_version = "FlowScriptStudio/3.0"

    def _send_json(self, status: int, data: Any):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, kind: str, message: str, line: int = 0, is_invariant: bool = False):
        suggestion = explain_diagnostic(kind, message)
        self._send_json(status, {
            "success": False,
            "diagnostics": [{
                "kind": kind,
                "message": message,
                "line": line,
                "is_invariant": is_invariant,
                "suggestion": suggestion
            }]
        })

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if not path:
            path = "/"

        # API: Health check
        if path == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "version": "3.0",
                "product": "FlowScript Studio",
                "compiler": "FlowScript Research Compiler"
            })
            return

        # API: List examples
        if path == "/api/examples":
            summary = []
            for ex in CURATED_EXAMPLES:
                summary.append({
                    "id": ex["id"],
                    "name": ex["name"],
                    "category": ex["category"],
                    "badge": ex.get("badge", ""),
                    "description": ex["description"]
                })
            self._send_json(200, summary)
            return

        # API: Get single example
        if path.startswith("/api/examples/"):
            ex_id = path[len("/api/examples/"):]
            ex_data = get_example_source(ex_id)
            if ex_data is None:
                self._send_error_json(404, "API", f"Example '{ex_id}' not found.")
                return
            self._send_json(200, ex_data)
            return

        # Static file serving from web/
        self._serve_static(path)

    def _serve_static(self, rel_path: str):
        if rel_path in ("/", ""):
            filename = "index.html"
        else:
            filename = rel_path.lstrip("/")

        # Security: protect against directory traversal
        target_path = os.path.abspath(os.path.join(WEB_DIR, filename))
        if not target_path.startswith(os.path.abspath(WEB_DIR)):
            self._send_error_json(403, "Security", "Access denied: path traversal attempt rejected.")
            return

        if not os.path.isfile(target_path):
            self._send_error_json(404, "Static", f"File '{filename}' not found.")
            return

        content_type, _ = mimetypes.guess_type(target_path)
        if not content_type:
            content_type = "application/octet-stream"

        try:
            with open(target_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type == "application/javascript" else content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
        except OSError as e:
            self._send_error_json(500, "IO", f"Failed reading static file: {e}")

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")

        # Check payload length
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._send_error_json(400, "API", "Invalid Content-Length header.")
            return

        if content_length > MAX_PAYLOAD_BYTES:
            self._send_error_json(413, "API", f"Payload size exceeds {MAX_PAYLOAD_BYTES // 1024} KB limit.")
            return

        try:
            body_bytes = self.rfile.read(content_length)
            body_json = json.loads(body_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            self._send_error_json(400, "API", f"Malformed JSON payload: {e}")
            return
        except UnicodeDecodeError:
            self._send_error_json(400, "API", "Payload must be UTF-8 encoded.")
            return

        source = body_json.get("source", "")
        if not isinstance(source, str):
            self._send_error_json(400, "API", "'source' field must be a string.")
            return

        opt = bool(body_json.get("optimize", True))

        if path == "/api/compile":
            try:
                result = compile_pipeline(source, opt=opt)
                self._send_json(200, result)
            except FlowScriptError as e:
                is_inv = isinstance(e, InvariantViolation) or getattr(e, "is_invariant", False)
                self._send_json(200, {
                    "success": False,
                    "tokens": [],
                    "ast": "",
                    "ir": [],
                    "optimized_ir": [],
                    "opt_stats": {"original_count": 0, "optimized_count": 0, "reduction_count": 0, "reduction_pct": 0},
                    "telemetry": [],
                    "diagnostics": [{
                        "kind": e.kind,
                        "message": e.message,
                        "line": e.line,
                        "is_invariant": is_inv,
                        "suggestion": explain_diagnostic(e.kind, e.message)
                    }]
                })
            except Exception as e:
                self._send_error_json(500, "CompilerInternal", f"Unexpected internal compiler error: {e}")
            return

        if path == "/api/run":
            timeout = float(body_json.get("timeout", 5.0))
            if timeout <= 0 or timeout > 30.0:
                timeout = 5.0

            raw_fault_cfg = body_json.get("fault_config")
            fault_cfg = FaultConfig.from_dict(raw_fault_cfg) if raw_fault_cfg else None

            try:
                result = run_pipeline(source, opt=opt, timeout=timeout, fault_config=fault_cfg)
                self._send_json(200, result)
            except FlowScriptError as e:
                is_inv = isinstance(e, InvariantViolation) or getattr(e, "is_invariant", False)
                self._send_json(200, {
                    "success": False,
                    "output": [],
                    "device_events": [],
                    "final_devices": {},
                    "final_vars": {},
                    "simulated_time": 0,
                    "duration_ms": 0,
                    "telemetry": [],
                    "execution_events": [],
                    "fault_summary": {},
                    "diagnostics": [{
                        "kind": e.kind,
                        "message": e.message,
                        "line": e.line,
                        "is_invariant": is_inv,
                        "suggestion": explain_diagnostic(e.kind, e.message)
                    }]
                })
            except Exception as e:
                self._send_error_json(500, "RuntimeInternal", f"Unexpected execution runtime error: {e}")
            return

        self._send_error_json(404, "API", f"Endpoint '{path}' not found.")

    def log_message(self, format, *args):
        # Override to suppress noisy stdout log spam during development & testing
        pass


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Start the FlowScript Studio local web server."""
    mimetypes.init()
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    server_address = (host, port)
    # Using ThreadingHTTPServer so simultaneous API/asset requests are handled smoothly
    with socketserver.ThreadingTCPServer(server_address, FlowScriptHTTPHandler) as httpd:
        httpd.allow_reuse_address = True
        print(f"============================================================")
        print(f"  FlowScript Studio v3.0 (Research & Compiler Playground)")
        print(f"  Local URL: http://{host}:{port}/")
        print(f"  Backend: Python {sys.version.split()[0]} standard library")
        print(f"  Press Ctrl+C to stop.")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down FlowScript Studio server...")
            httpd.shutdown()


def main():
    parser = argparse.ArgumentParser(description="FlowScript Studio Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
