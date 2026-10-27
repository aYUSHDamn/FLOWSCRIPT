import json
import os
import sys
import threading
import time
import unittest
import urllib.request
import urllib.error

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import server


class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start server on an ephemeral loopback port for testing
        cls.host = "127.0.0.1"
        cls.port = 18888
        cls.server_thread = None
        cls.httpd = None

        server.mimetypes.init()
        server.mimetypes.add_type("application/javascript", ".js")
        server.mimetypes.add_type("text/css", ".css")

        cls.httpd = server.socketserver.ThreadingTCPServer((cls.host, cls.port), server.FlowScriptHTTPHandler)
        cls.httpd.allow_reuse_address = True
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)  # Brief wait for socket bind

    @classmethod
    def tearDownClass(cls):
        if cls.httpd:
            cls.httpd.shutdown()
            cls.httpd.server_close()

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _get(self, path: str):
        req = urllib.request.Request(self._url(path))
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            return resp.status, resp.headers.get("Content-Type", ""), data

    def _post_json(self, path: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data

    def test_health_endpoint(self):
        status, ctype, data = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        j = json.loads(data.decode("utf-8"))
        self.assertEqual(j["status"], "ok")
        self.assertEqual(j["product"], "FlowScript Studio")

    def test_list_examples(self):
        status, ctype, data = self._get("/api/examples")
        self.assertEqual(status, 200)
        j = json.loads(data.decode("utf-8"))
        self.assertIsInstance(j, list)
        ids = [x["id"] for x in j]
        self.assertIn("temperature", ids)
        self.assertIn("optimization_demo", ids)
        self.assertIn("recovery_demo", ids)
        self.assertIn("fault_recovery_demo", ids)
        self.assertIn("synthesis_demo", ids)
        self.assertIn("synthesis_failure", ids)

    def test_get_example_by_id(self):
        status, ctype, data = self._get("/api/examples/temperature")
        self.assertEqual(status, 200)
        j = json.loads(data.decode("utf-8"))
        self.assertEqual(j["id"], "temperature")
        self.assertIn("START", j["source"])
        self.assertIn("temperature", j["source"])

    def test_get_nonexistent_example(self):
        try:
            self._get("/api/examples/missing_workflow")
            self.fail("Expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            data = json.loads(e.read().decode("utf-8"))
            self.assertFalse(data["success"])

    def test_compile_valid_workflow(self):
        src = "START\nSET x = 10 + 5\nPRINT x\nEND\n"
        status, res = self._post_json("/api/compile", {"source": src, "optimize": True})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertGreater(len(res["tokens"]), 0)
        self.assertIn("Program()", res["ast"])
        self.assertGreater(len(res["ir"]), 0)
        self.assertGreater(len(res["optimized_ir"]), 0)
        self.assertEqual(len(res["diagnostics"]), 0)

    def test_compile_syntax_error_diagnostics(self):
        src = "START\nIF 1 > 0\nPRINT 1\nEND\n"  # Missing END_IF
        status, res = self._post_json("/api/compile", {"source": src})
        self.assertEqual(status, 200)
        self.assertFalse(res["success"])
        self.assertGreater(len(res["diagnostics"]), 0)
        d = res["diagnostics"][0]
        self.assertEqual(d["kind"], "Syntax")
        self.assertIn("END_IF", d["message"])
        self.assertIn("END_IF", d["suggestion"])

    def test_compile_synthesis_demo_telemetry(self):
        src = ("START\n"
               "DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE cooler.status == ON AND heater.status == OFF\n"
               "END_TRY\n"
               "END\n")
        status, res = self._post_json("/api/compile", {"source": src})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertGreater(len(res["telemetry"]), 0)
        t = res["telemetry"][0]
        self.assertTrue(t["success"])
        self.assertIn("TURN_ON cooler", t["plan"])
        self.assertIn("TURN_OFF heater", t["plan"])

    def test_compile_synthesis_failure_fail_closed(self):
        # Invariant forbids both ON, but TURN_OFF heater is not approved!
        src = ("START\n"
               "DEVICE heater TYPE heating\n"
               "DEVICE cooler TYPE cooling\n"
               "INVARIANT NOT (heater.status == ON AND cooler.status == ON)\n"
               "TURN_ON heater\n"
               "TRY\n"
               "    REQUIRE 1 == 0\n"
               "RECOVER\n"
               "    SYNTHESIZE cooler.status == ON USING TURN_ON cooler MAX_STEPS 2\n"
               "END_TRY\n"
               "END\n")
        status, res = self._post_json("/api/compile", {"source": src})
        self.assertEqual(status, 200)
        self.assertFalse(res["success"])
        d = res["diagnostics"][0]
        self.assertEqual(d["kind"], "Synthesis")
        self.assertIn("No safe recovery plan found", d["message"])

    def test_run_valid_workflow(self):
        src = "START\nSET a = 3\nPRINT a * 2\nEND\n"
        status, res = self._post_json("/api/run", {"source": src, "optimize": True})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["output"], ["6"])
        self.assertGreater(res["duration_ms"], 0)
        self.assertGreater(res["instructions_executed"], 0)

    def test_run_device_actuation_events(self):
        src = "START\nDEVICE fan TYPE ventilation\nTURN_ON fan\nTURN_OFF fan\nEND\n"
        status, res = self._post_json("/api/run", {"source": src})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["output"], ["fan → ON", "fan → OFF"])
        self.assertEqual(len(res["device_events"]), 2)
        self.assertEqual(res["device_events"][0]["device"], "fan")
        self.assertEqual(res["device_events"][0]["state"], "ON")
        self.assertEqual(res["final_devices"]["fan"], "OFF")

    def test_run_runtime_contract_failure(self):
        src = "START\nREQUIRE 1 == 0\nEND\n"
        status, res = self._post_json("/api/run", {"source": src})
        self.assertEqual(status, 200)
        self.assertFalse(res["success"])
        self.assertGreater(len(res["diagnostics"]), 0)
        self.assertEqual(res["diagnostics"][0]["kind"], "Runtime")
        self.assertIn("REQUIRE contract violated", res["diagnostics"][0]["message"])

    def test_payload_size_limit(self):
        giant_source = "START\n" + ("# comment\n" * 35000) + "END\n"
        status, res = self._post_json("/api/compile", {"source": giant_source})
        self.assertEqual(status, 413)
        self.assertIn("exceeds", res["diagnostics"][0]["message"])

    def test_path_traversal_rejection(self):
        try:
            self._get("/../server.py")
            self.fail("Expected HTTP error")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (400, 403, 404))

    def test_static_index_html(self):
        status, ctype, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        html = data.decode("utf-8")
        self.assertIn("FlowScript Studio", html)
        self.assertIn("Recovery Synthesis", html)

    def test_static_style_css(self):
        status, ctype, data = self._get("/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        css = data.decode("utf-8")
        self.assertIn("--bg-app", css)

    def test_static_app_js(self):
        status, ctype, data = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", ctype)
        js = data.decode("utf-8")
        self.assertIn("FlowScript Studio", js)

    def test_timeout_and_instruction_limit(self):
        # A REPEAT loop exceeding instruction limit
        src = "START\nREPEAT 250000\nSET x = 1\nEND_REPEAT\nEND\n"
        status, res = self._post_json("/api/run", {"source": src, "timeout": 1.0})
        self.assertEqual(status, 200)
        self.assertFalse(res["success"])
        msg = res["diagnostics"][0]["message"]
        self.assertTrue("limit" in msg or "timeout" in msg)

    def test_concurrent_requests_isolation(self):
        # Launch 8 simultaneous requests with different programs
        results = [None] * 8
        def worker(idx):
            src = f"START\nSET val = {idx * 10}\nPRINT val\nEND\n"
            _, res = self._post_json("/api/run", {"source": src})
            results[idx] = res

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()

        for idx, res in enumerate(results):
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            self.assertEqual(res["output"], [str(idx * 10)])

    def test_run_with_fault_injection(self):
        src = ("START\n"
               "DEVICE heater TYPE heating\n"
               "DEVICE backup_heater TYPE heating\n"
               "TRY\n"
               "    TURN_ON heater\n"
               "    ENSURE heater.status == ON\n"
               "RECOVER\n"
               "    TURN_ON backup_heater\n"
               "END_TRY\n"
               "END\n")
        payload = {
            "source": src,
            "fault_config": {
                "enabled": True,
                "rules": [
                    {
                        "device": "heater",
                        "action": "TURN_ON",
                        "fault_type": "action_failure",
                        "trigger_step": 1
                    }
                ]
            }
        }
        status, res = self._post_json("/api/run", payload)
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["final_devices"]["heater"], "OFF")
        self.assertEqual(res["final_devices"]["backup_heater"], "ON")
        self.assertGreater(len(res["execution_events"]), 0)
        self.assertEqual(res["fault_summary"]["faults_injected"], 1)
        self.assertEqual(res["fault_summary"]["recoveries_succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
