/**
 * FlowScript Studio Frontend Application.
 *
 * Implements a complete IDE client:
 * - Pure vanilla JS custom code editor with syntax highlighting, line gutter & keyboard navigation.
 * - Real compiler backend integration (compile & run endpoints).
 * - Multi-stage compiler inspector (Tokens, AST, IR, Optimized IR, Diagnostics).
 * - Research telemetry visualizer for safety-constrained recovery synthesis.
 * - Interactive guided tutorial and research model documentation.
 */

(function () {
  "use strict";

  // Application State
  const state = {
    currentExampleId: "temperature",
    currentSource: "",
    originalSource: "",
    isDirty: false,
    optimize: true,
    faultInjectionEnabled: false,
    faultPreset: "action_failure",
    customFault: {
      device: "primary_pump",
      action: "TURN_ON",
      fault_type: "action_failure",
      trigger_step: 1,
      delay_seconds: 2.5,
      mismatch_state: "OFF",
    },
    activeTab: "tab-output",
    isSidebarOpen: true,
    tutorialStep: 0,
    examples: [],
    tokensCache: [],
    pendingSwitchExampleId: null,
  };

  // DOM Elements
  const el = {
    sidebar: document.getElementById("sidebar"),
    toggleSidebarBtn: document.getElementById("toggle-sidebar-btn"),
    exampleSelect: document.getElementById("example-select"),
    examplesList: document.getElementById("examples-list"),
    optToggle: document.getElementById("opt-toggle"),
    optToggleLabel: document.getElementById("opt-toggle-label"),
    faultToggle: document.getElementById("fault-toggle"),
    faultToggleLabel: document.getElementById("fault-toggle-label"),
    faultPresetWrapper: document.getElementById("fault-preset-wrapper"),
    faultPresetSelect: document.getElementById("fault-preset-select"),
    compileBtn: document.getElementById("compile-btn"),
    runBtn: document.getElementById("run-btn"),
    backendStatus: document.getElementById("backend-status"),
    activeFilename: document.getElementById("active-filename"),
    dirtyIndicator: document.getElementById("dirty-indicator"),
    cursorPos: document.getElementById("cursor-pos"),
    formatBtn: document.getElementById("format-btn"),
    copyBtn: document.getElementById("copy-btn"),
    copyText: document.getElementById("copy-text"),
    downloadBtn: document.getElementById("download-btn"),
    resetBtn: document.getElementById("reset-btn"),
    editorGutter: document.getElementById("editor-gutter"),
    editorScroller: document.getElementById("editor-scroller"),
    highlightLayer: document.getElementById("highlight-layer"),
    highlightCode: document.getElementById("highlight-code"),
    codeInput: document.getElementById("code-input"),
    compilerStatusBadge: document.getElementById("compiler-status-badge"),
    perfMetrics: document.getElementById("perf-metrics"),
    tabsBar: document.querySelector(".tabs-bar"),
    tabPanes: document.querySelectorAll(".tab-pane"),
    tabBtns: document.querySelectorAll(".tab-btn"),
    terminal: document.getElementById("terminal"),
    deviceChips: document.getElementById("device-chips"),
    varsSummary: document.getElementById("vars-summary"),
    varsGrid: document.getElementById("vars-grid"),
    diagnosticsList: document.getElementById("diagnostics-list"),
    diagBadge: document.getElementById("diag-badge"),
    tokenFilter: document.getElementById("token-filter"),
    tokensBody: document.getElementById("tokens-body"),
    astView: document.getElementById("ast-view"),
    irBody: document.getElementById("ir-body"),
    optIrBody: document.getElementById("opt-ir-body"),
    optStatsPill: document.getElementById("opt-stats-pill"),
    optStatsDetails: document.getElementById("opt-stats-details"),
    telemetryBadge: document.getElementById("telemetry-badge"),
    telemetryView: document.getElementById("telemetry-view"),
    loadSynthDemoBtn: document.getElementById("load-synth-demo-btn"),
    // Phase 4 Runtime Monitoring
    monitoringBadge: document.getElementById("monitoring-badge"),
    faultConfigBtn: document.getElementById("fault-config-btn"),
    loadFaultDemoBtn: document.getElementById("load-fault-demo-btn"),
    kpiFaultStatus: document.getElementById("kpi-fault-status"),
    kpiFaultsInjected: document.getElementById("kpi-faults-injected"),
    kpiRecoveries: document.getElementById("kpi-recoveries"),
    kpiSimTime: document.getElementById("kpi-sim-time"),
    eventsTable: document.getElementById("events-table"),
    eventsBody: document.getElementById("events-body"),
    // Tutorial
    tutorialBtn: document.getElementById("tutorial-btn"),
    tutorialBanner: document.getElementById("tutorial-banner"),
    tutCloseBtn: document.getElementById("tut-close-btn"),
    tutStepNum: document.getElementById("tut-step-num"),
    tutTitle: document.getElementById("tut-title"),
    tutDesc: document.getElementById("tut-desc"),
    tutExpectedText: document.getElementById("tut-expected-text"),
    tutLoadBtn: document.getElementById("tut-load-btn"),
    tutRunBtn: document.getElementById("tut-run-btn"),
    tutPrevBtn: document.getElementById("tut-prev-btn"),
    tutNextBtn: document.getElementById("tut-next-btn"),
    // Modals
    researchBtn: document.getElementById("research-btn"),
    researchModal: document.getElementById("research-modal"),
    modalCloseBtn: document.getElementById("modal-close-btn"),
    modalOkBtn: document.getElementById("modal-ok-btn"),
    confirmModal: document.getElementById("confirm-modal"),
    confirmCloseBtn: document.getElementById("confirm-close-btn"),
    confirmCancelBtn: document.getElementById("confirm-cancel-btn"),
    confirmProceedBtn: document.getElementById("confirm-proceed-btn"),
    // Fault Modal
    faultModal: document.getElementById("fault-modal"),
    faultModalCloseBtn: document.getElementById("fault-modal-close-btn"),
    faultModalApplyBtn: document.getElementById("fault-modal-apply-btn"),
    cfgFaultEnable: document.getElementById("cfg-fault-enable"),
    cfgFaultScenario: document.getElementById("cfg-fault-scenario"),
    cfgRuleDevice: document.getElementById("cfg-rule-device"),
    cfgRuleAction: document.getElementById("cfg-rule-action"),
    cfgRuleType: document.getElementById("cfg-rule-type"),
    cfgRuleStep: document.getElementById("cfg-rule-step"),
    cfgRuleDelay: document.getElementById("cfg-rule-delay"),
    cfgRuleMismatch: document.getElementById("cfg-rule-mismatch"),
  };

  // Syntax Highlighting Engine for FlowScript
  const KEYWORDS = new Set([
    "START", "END", "SET", "PRINT", "IF", "ELSE", "END_IF",
    "REPEAT", "END_REPEAT", "WAIT", "TURN_ON", "TURN_OFF",
    "DEVICE", "TYPE", "INVARIANT", "REQUIRE", "ENSURE",
    "TRY", "RECOVER", "END_TRY", "SYNTHESIZE", "MAX_STEPS",
    "USING", "FROM", "AND", "OR", "NOT"
  ]);

  const DEVICE_TYPES = new Set(["heating", "cooling", "ventilation", "sensor"]);
  const STATES = new Set(["ON", "OFF", "READY", "ERROR"]);

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function highlightFlowScript(code) {
    const lines = code.split("\n");
    const highlightedLines = lines.map((line) => {
      let out = "";
      let i = 0;
      while (i < line.length) {
        // Comment
        if (line[i] === "#") {
          out += `<span class="tok-comm">${escapeHtml(line.slice(i))}</span>`;
          break;
        }

        // String literal
        if (line[i] === '"') {
          let j = i + 1;
          while (j < line.length && line[j] !== '"') {
            if (line[j] === "\\" && j + 1 < line.length) j++;
            j++;
          }
          const strVal = line.slice(i, j + 1);
          out += `<span class="tok-str">${escapeHtml(strVal)}</span>`;
          i = j + 1;
          continue;
        }

        // Whitespace
        if (/\s/.test(line[i])) {
          out += line[i];
          i++;
          continue;
        }

        // Identifiers / Keywords / Device properties
        if (/[A-Za-z_]/.test(line[i])) {
          let j = i;
          while (j < line.length && /[A-Za-z0-9_]/.test(line[j])) j++;
          const word = line.slice(i, j);

          // Check if followed by .status
          if (j < line.length && line[j] === ".") {
            let k = j + 1;
            while (k < line.length && /[A-Za-z0-9_]/.test(line[k])) k++;
            const prop = line.slice(j + 1, k);
            out += `<span class="tok-dev">${escapeHtml(word)}</span>.<span class="tok-prop">${escapeHtml(prop)}</span>`;
            i = k;
            continue;
          }

          if (KEYWORDS.has(word)) {
            out += `<span class="tok-kw">${escapeHtml(word)}</span>`;
          } else if (STATES.has(word)) {
            out += `<span class="tok-state">${escapeHtml(word)}</span>`;
          } else if (DEVICE_TYPES.has(word)) {
            out += `<span class="tok-dev">${escapeHtml(word)}</span>`;
          } else {
            out += escapeHtml(word);
          }
          i = j;
          continue;
        }

        // Numbers
        if (/[0-9]/.test(line[i])) {
          let j = i;
          while (j < line.length && /[0-9.]/.test(line[j])) j++;
          out += `<span class="tok-num">${escapeHtml(line.slice(i, j))}</span>`;
          i = j;
          continue;
        }

        // Other operators and punctuation
        out += escapeHtml(line[i]);
        i++;
      }
      return out;
    });

    return highlightedLines.join("\n") + "\n";
  }

  // Editor Updating & Line Gutter
  function updateEditor() {
    const val = el.codeInput.value;
    state.currentSource = val;
    state.isDirty = val !== state.originalSource;
    el.dirtyIndicator.classList.toggle("hidden", !state.isDirty);

    // Update highlight layer
    el.highlightCode.innerHTML = highlightFlowScript(val);

    // Update gutter line numbers
    const lineCount = Math.max(1, val.split("\n").length);
    let gutterHtml = "";
    for (let i = 1; i <= lineCount; i++) {
      gutterHtml += `<div class="gutter-line" id="gutter-L${i}">${i}</div>`;
    }
    el.editorGutter.innerHTML = gutterHtml;

    updateCursorPosition();
  }

  function syncScroll() {
    el.editorGutter.scrollTop = el.codeInput.scrollTop;
    el.highlightLayer.scrollTop = el.codeInput.scrollTop;
    el.highlightLayer.scrollLeft = el.codeInput.scrollLeft;
  }

  function updateCursorPosition() {
    const selStart = el.codeInput.selectionStart;
    const textBefore = el.codeInput.value.substring(0, selStart);
    const lines = textBefore.split("\n");
    const lineNum = lines.length;
    const colNum = lines[lines.length - 1].length + 1;
    el.cursorPos.textContent = `Ln ${lineNum}, Col ${colNum}`;
  }

  function setErrorGutterMarkers(lineNumbers) {
    document.querySelectorAll(".gutter-line.error-line").forEach((gl) => {
      gl.classList.remove("error-line");
    });
    lineNumbers.forEach((ln) => {
      const gl = document.getElementById(`gutter-L${ln}`);
      if (gl) gl.classList.add("error-line");
    });
  }

  function jumpToLine(lineNum) {
    const lines = el.codeInput.value.split("\n");
    if (lineNum < 1 || lineNum > lines.length) return;
    let offset = 0;
    for (let i = 0; i < lineNum - 1; i++) {
      offset += lines[i].length + 1;
    }
    el.codeInput.focus();
    el.codeInput.setSelectionRange(offset, offset + lines[lineNum - 1].length);
    // Scroll to position
    const lineHeight = 20.8;
    el.codeInput.scrollTop = Math.max(0, (lineNum - 3) * lineHeight);
    syncScroll();
  }

  // Keyboard Shortcuts & Smart Indentation
  function handleEditorKeyDown(e) {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = el.codeInput.selectionStart;
      const end = el.codeInput.selectionEnd;
      const val = el.codeInput.value;

      if (e.shiftKey) {
        // Unindent
        const lineStart = val.lastIndexOf("\n", start - 1) + 1;
        if (val.startsWith("    ", lineStart)) {
          el.codeInput.value = val.substring(0, lineStart) + val.substring(lineStart + 4);
          el.codeInput.selectionStart = el.codeInput.selectionEnd = Math.max(lineStart, start - 4);
          updateEditor();
        }
      } else {
        // Indent 4 spaces
        el.codeInput.value = val.substring(0, start) + "    " + val.substring(end);
        el.codeInput.selectionStart = el.codeInput.selectionEnd = start + 4;
        updateEditor();
      }
      return;
    }

    if (e.key === "Enter") {
      // Auto-indent
      e.preventDefault();
      const start = el.codeInput.selectionStart;
      const val = el.codeInput.value;
      const lineStart = val.lastIndexOf("\n", start - 1) + 1;
      const currentLine = val.substring(lineStart, start);
      const matchIndent = currentLine.match(/^(\s*)/);
      let indent = matchIndent ? matchIndent[1] : "";

      // Add extra indent if block start
      const trimmed = currentLine.trim();
      if (/^(START|IF\b.*|ELSE|REPEAT\b.*|TRY|RECOVER)$/.test(trimmed)) {
        indent += "    ";
      }

      el.codeInput.value = val.substring(0, start) + "\n" + indent + val.substring(start);
      el.codeInput.selectionStart = el.codeInput.selectionEnd = start + 1 + indent.length;
      updateEditor();
      return;
    }
  }

  // Format Indentation Action
  function formatCode() {
    const lines = el.codeInput.value.split("\n");
    let indentLevel = 0;
    const formatted = [];

    for (let rawLine of lines) {
      let trimmed = rawLine.trim();
      if (!trimmed) {
        formatted.push("");
        continue;
      }

      // Check unindent triggers
      if (/^(END|ELSE|END_IF|END_REPEAT|RECOVER|END_TRY)$/.test(trimmed)) {
        indentLevel = Math.max(0, indentLevel - 1);
      }

      const indentStr = "    ".repeat(indentLevel);
      formatted.push(indentStr + trimmed);

      // Check indent triggers
      if (/^(START|IF\b.*|ELSE|REPEAT\b.*|TRY|RECOVER)$/.test(trimmed)) {
        indentLevel++;
      }
    }

    el.codeInput.value = formatted.join("\n");
    updateEditor();
  }

  // API Client Methods
  async function apiGet(path) {
    const res = await fetch(path);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err?.diagnostics?.[0]?.message || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function apiPost(path, data) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return res.json();
  }

  // Compiler Actions
  async function compileWorkflow() {
    setCompilerStatus("compiling", "Compiling...");
    const t0 = performance.now();

    try {
      const res = await apiPost("/api/compile", {
        source: el.codeInput.value,
        optimize: state.optimize,
      });

      const durMs = Math.round(performance.now() - t0);
      renderCompilationResults(res, durMs);
    } catch (err) {
      setCompilerStatus("error", "Failed");
      renderError(err.message);
    }
  }

  function buildFaultConfigPayload() {
    if (!state.faultInjectionEnabled) return null;

    if (state.faultPreset === "action_failure") {
      return {
        enabled: true,
        rules: [
          {
            device: "primary_pump",
            action: "TURN_ON",
            fault_type: "action_failure",
            trigger_step: 1,
            delay_seconds: 0.0,
            mismatch_state: "OFF",
            error_message: "Simulated actuator hardware fault on primary_pump"
          }
        ]
      };
    } else if (state.faultPreset === "state_mismatch") {
      return {
        enabled: true,
        rules: [
          {
            device: "primary_pump",
            action: "TURN_ON",
            fault_type: "state_mismatch",
            trigger_step: 1,
            delay_seconds: 0.0,
            mismatch_state: "OFF"
          }
        ]
      };
    } else if (state.faultPreset === "delayed_completion") {
      return {
        enabled: true,
        rules: [
          {
            device: "primary_pump",
            action: "TURN_ON",
            fault_type: "delayed_completion",
            trigger_step: 1,
            delay_seconds: 2.5,
            mismatch_state: "OFF"
          }
        ]
      };
    } else {
      // Custom user configuration
      return {
        enabled: true,
        rules: [
          {
            device: state.customFault.device || "primary_pump",
            action: state.customFault.action || "TURN_ON",
            fault_type: state.customFault.fault_type || "action_failure",
            trigger_step: parseInt(state.customFault.trigger_step, 10) || 1,
            delay_seconds: parseFloat(state.customFault.delay_seconds) || 0.0,
            mismatch_state: state.customFault.mismatch_state || "OFF"
          }
        ]
      };
    }
  }

  async function runWorkflow() {
    setCompilerStatus("compiling", "Executing...");
    const t0 = performance.now();

    try {
      const payload = {
        source: el.codeInput.value,
        optimize: state.optimize,
        timeout: 5.0,
      };

      if (state.faultInjectionEnabled) {
        payload.fault_config = buildFaultConfigPayload();
      }

      const res = await apiPost("/api/run", payload);

      const durMs = Math.round(performance.now() - t0);
      renderExecutionResults(res, durMs);
    } catch (err) {
      setCompilerStatus("error", "Execution Error");
      renderError(err.message);
    }
  }

  function setCompilerStatus(type, label) {
    el.compilerStatusBadge.className = `badge badge-${type === "compiling" ? "idle" : type === "success" ? "success" : type === "error" ? "error" : "idle"}`;
    el.compilerStatusBadge.textContent = label;
  }

  // Rendering Results
  function renderCompilationResults(res, durMs) {
    if (res.success) {
      setCompilerStatus("success", "Compiled Cleanly");
      el.perfMetrics.textContent = `${durMs} ms • ${res.tokens.length} tokens • ${res.ir.length} IR instructions`;
      setErrorGutterMarkers([]);
      renderDiagnostics([]);
    } else {
      setCompilerStatus("error", "Compiler Diagnostic");
      el.perfMetrics.textContent = `${durMs} ms • 1 diagnostic reported`;
      renderDiagnostics(res.diagnostics);
      const lines = res.diagnostics.map((d) => d.line).filter((l) => l > 0);
      setErrorGutterMarkers(lines);
      switchTab("tab-diagnostics");
    }

    renderTokens(res.tokens || []);
    renderAst(res.ast || "");
    renderIr(res.ir || []);
    renderOptimizedIr(res.optimized_ir || [], res.opt_stats || {});
    renderTelemetry(res.telemetry || []);
  }

  function renderExecutionResults(res, durMs) {
    renderTerminalOutput(res);
    renderDeviceHUD(res.final_devices || {}, res.device_events || []);
    renderVariables(res.final_vars || {});
    renderMonitoring(res.execution_events || [], res.fault_summary || {}, res.simulated_time || 0);

    if (res.success) {
      setCompilerStatus("success", "Execution Succeeded");
      el.perfMetrics.textContent = `${res.duration_ms || durMs} ms • ${res.instructions_executed || 0} instructions`;
      setErrorGutterMarkers([]);
      renderDiagnostics([]);
      if (state.activeTab !== "tab-monitoring") {
        switchTab("tab-output");
      }
    } else {
      setCompilerStatus("error", "Runtime Failure");
      el.perfMetrics.textContent = `${res.duration_ms || durMs} ms • Failed`;
      renderDiagnostics(res.diagnostics || []);
      const lines = (res.diagnostics || []).map((d) => d.line).filter((l) => l > 0);
      setErrorGutterMarkers(lines);
      if (state.activeTab !== "tab-monitoring") {
        switchTab("tab-output");
      }
    }

    renderTelemetry(res.telemetry || []);
  }

  function renderTerminalOutput(res) {
    const lines = res.output || [];
    if (!lines.length && !res.diagnostics?.length) {
      el.terminal.innerHTML = `<div class="terminal-line terminal-dim">[No printed output produced by workflow]</div>`;
      return;
    }

    const timestamp = new Date().toLocaleTimeString();
    let html = `<div class="terminal-line terminal-dim">[${timestamp}] Workflow execution started (${state.optimize ? "Optimized" : "Unoptimized"})</div>`;

    for (let l of lines) {
      if (l.includes("→")) {
        html += `<div class="terminal-line"><span class="terminal-time">[${timestamp}]</span> <span class="terminal-action">⚡ ${escapeHtml(l)}</span></div>`;
      } else {
        html += `<div class="terminal-line"><span class="terminal-time">[${timestamp}]</span> ${escapeHtml(l)}</div>`;
      }
    }

    if (res.fault_summary && res.fault_summary.faults_injected > 0) {
      const s = res.fault_summary;
      html += `<div class="terminal-line"><span class="terminal-time">[${timestamp}]</span> <span class="badge badge-amber">⚡ Fault Telemetry</span>: Injected ${s.faults_injected} fault(s) • Recovered: ${s.recoveries_succeeded}/${s.recoveries_triggered} • Sim Time: +${(res.simulated_time || 0).toFixed(3)}s</div>`;
    }

    if (!res.success && res.diagnostics?.length) {
      const d = res.diagnostics[0];
      html += `<div class="terminal-line terminal-error"><span class="terminal-time">[${timestamp}]</span> ✖ ${escapeHtml(d.kind)} Error [Line ${d.line}]: ${escapeHtml(d.message)}</div>`;
      if (d.suggestion) {
        html += `<div class="terminal-line terminal-dim">&nbsp;&nbsp;&nbsp;&nbsp;💡 Suggestion: ${escapeHtml(d.suggestion)}</div>`;
      }
    } else if (res.success) {
      html += `<div class="terminal-line terminal-dim">[${timestamp}] Workflow finished successfully in ${res.duration_ms} ms.</div>`;
    }

    el.terminal.innerHTML = html;
    el.terminal.scrollTop = el.terminal.scrollHeight;
  }

  function renderMonitoring(events, summary, simTime) {
    if (state.faultInjectionEnabled) {
      el.kpiFaultStatus.textContent = "Active";
      el.kpiFaultStatus.className = "kpi-value highlight-amber";
    } else {
      el.kpiFaultStatus.textContent = "Disabled";
      el.kpiFaultStatus.className = "kpi-value";
    }

    const injected = summary.faults_injected || 0;
    const succeeded = summary.recoveries_succeeded || 0;
    const triggered = summary.recoveries_triggered || 0;

    el.kpiFaultsInjected.textContent = injected;
    el.kpiRecoveries.textContent = `${succeeded} / ${triggered}`;
    el.kpiSimTime.textContent = `${(simTime || 0).toFixed(3)}s`;

    if (injected > 0 || state.faultInjectionEnabled) {
      el.monitoringBadge.textContent = `${injected} Fault${injected === 1 ? "" : "s"}`;
      el.monitoringBadge.classList.remove("hidden");
    } else {
      el.monitoringBadge.classList.add("hidden");
    }

    if (!events || !events.length) {
      el.eventsBody.innerHTML = `<tr><td colspan="9" class="dim-row">No runtime events recorded. Run a workflow to stream execution events.</td></tr>`;
      return;
    }

    let html = "";
    events.forEach((evt) => {
      const isMismatch = evt.requested_state && evt.observed_state && evt.requested_state !== evt.observed_state;
      const isFault = evt.fault_type !== null || evt.event_type === "FAULT_INJECTED";
      const isRecovery = evt.event_type && evt.event_type.startsWith("RECOVERY");

      let evtClass = "chip";
      if (isFault) evtClass = "chip chip-event-fault";
      else if (isRecovery) evtClass = "chip chip-event-recovery";
      else if (evt.event_type === "ACTUATION") evtClass = "chip chip-event-actuation";

      let reqObsHtml = '<span class="dim-row">—</span>';
      if (evt.requested_state || evt.observed_state) {
        if (isMismatch) {
          reqObsHtml = `<span class="chip chip-mismatch">${escapeHtml(evt.requested_state || "")} &ne; ${escapeHtml(evt.observed_state || "")}</span>`;
        } else {
          reqObsHtml = `<span class="chip">${escapeHtml(evt.requested_state || "—")} &rarr; ${escapeHtml(evt.observed_state || "—")}</span>`;
        }
      }

      let faultChip = '<span class="dim-row">—</span>';
      if (evt.fault_type) {
        faultChip = `<span class="chip chip-event-fault">${escapeHtml(evt.fault_type)}</span>`;
      }

      let recChip = '<span class="dim-row">—</span>';
      if (evt.recovery_decision) {
        recChip = `<span class="chip chip-event-recovery">${escapeHtml(evt.recovery_decision)}</span>`;
      }

      let outcomeClass = "chip";
      if (evt.final_outcome === "SUCCESS") outcomeClass = "chip chip-outcome-success";
      else if (evt.final_outcome === "FAULT") outcomeClass = "chip chip-outcome-fault";
      else if (evt.final_outcome === "RECOVERED") outcomeClass = "chip chip-outcome-recovered";
      else if (evt.final_outcome === "FAILED") outcomeClass = "chip chip-event-fault";

      const simTimeSec = typeof evt.simulated_time === "number" ? evt.simulated_time.toFixed(3) : "0.000";

      html += `
        <tr>
          <td>${evt.step}</td>
          <td><code>+${simTimeSec}s</code></td>
          <td><span class="${evtClass}">${escapeHtml(evt.event_type)}</span></td>
          <td><strong>${escapeHtml(evt.device || "—")}</strong></td>
          <td><code>${escapeHtml(evt.action || "—")}</code></td>
          <td>${reqObsHtml}</td>
          <td>${faultChip}</td>
          <td>${recChip}</td>
          <td><span class="${outcomeClass}">${escapeHtml(evt.final_outcome || "—")}</span></td>
        </tr>`;
    });

    el.eventsBody.innerHTML = html;
  }

  function renderDeviceHUD(finalDevices, events) {
    const entries = Object.entries(finalDevices);
    if (!entries.length) {
      el.deviceChips.innerHTML = `<span class="chip chip-dim">No devices declared</span>`;
      return;
    }

    let html = "";
    for (let [dev, st] of entries) {
      const isOn = st === "ON";
      html += `<span class="chip ${isOn ? "chip-on" : "chip-off"}">${escapeHtml(dev)}: <strong>${escapeHtml(st)}</strong></span>`;
    }
    el.deviceChips.innerHTML = html;
  }

  function renderVariables(vars) {
    const entries = Object.entries(vars);
    if (!entries.length) {
      el.varsSummary.classList.add("hidden");
      return;
    }
    el.varsSummary.classList.remove("hidden");
    let html = "";
    for (let [k, v] of entries) {
      html += `<span class="var-pill"><strong>${escapeHtml(k)}</strong> = ${escapeHtml(String(v))}</span>`;
    }
    el.varsGrid.innerHTML = html;
  }

  function renderDiagnostics(diagnostics) {
    el.diagBadge.textContent = diagnostics.length;
    el.diagBadge.classList.toggle("hidden", diagnostics.length === 0);

    if (!diagnostics.length) {
      el.diagnosticsList.innerHTML = `
        <div class="empty-state">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <p>No diagnostics reported. The program parsed, analyzed, and executed cleanly.</p>
        </div>`;
      return;
    }

    let html = "";
    for (let d of diagnostics) {
      html += `
        <div class="diag-card ${escapeHtml(d.kind)}">
          <div class="diag-header">
            <span class="diag-kind">${escapeHtml(d.kind)} Error</span>
            ${d.line > 0 ? `<button class="diag-line-btn" data-line="${d.line}">Line ${d.line}</button>` : ""}
          </div>
          <div class="diag-message">${escapeHtml(d.message)}</div>
          ${d.suggestion ? `<div class="diag-suggestion">💡 <strong>Suggestion:</strong> ${escapeHtml(d.suggestion)}</div>` : ""}
        </div>`;
    }
    el.diagnosticsList.innerHTML = html;

    // Attach jump-to-line buttons
    el.diagnosticsList.querySelectorAll(".diag-line-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const ln = parseInt(btn.getAttribute("data-line"), 10);
        jumpToLine(ln);
      });
    });
  }

  function renderTokens(tokens) {
    state.tokensCache = tokens;
    filterTokensTable();
  }

  function filterTokensTable() {
    const q = (el.tokenFilter.value || "").toLowerCase().trim();
    const tokens = state.tokensCache || [];
    const filtered = q
      ? tokens.filter((t) => t.type.toLowerCase().includes(q) || t.value.toLowerCase().includes(q))
      : tokens;

    if (!filtered.length) {
      el.tokensBody.innerHTML = `<tr><td colspan="4" class="dim-row">No tokens matching filter.</td></tr>`;
      return;
    }

    let html = "";
    filtered.forEach((t, i) => {
      html += `
        <tr>
          <td>${i + 1}</td>
          <td><span class="chip">${escapeHtml(t.type)}</span></td>
          <td><code>${escapeHtml(t.value)}</code></td>
          <td>Line ${t.line}</td>
        </tr>`;
    });
    el.tokensBody.innerHTML = html;
  }

  function renderAst(astText) {
    el.astView.textContent = astText || "No AST available.";
  }

  function renderIr(ir) {
    if (!ir.length) {
      el.irBody.innerHTML = `<tr><td colspan="4" class="dim-row">No IR instructions available.</td></tr>`;
      return;
    }
    let html = "";
    ir.forEach((ins) => {
      html += `
        <tr>
          <td>${ins.index}</td>
          <td><span class="chip">${escapeHtml(ins.op)}</span></td>
          <td>${ins.arg !== null ? `<code>${escapeHtml(ins.arg)}</code>` : '<span class="dim-row">—</span>'}</td>
          <td>Line ${ins.line}</td>
        </tr>`;
    });
    el.irBody.innerHTML = html;
  }

  function renderOptimizedIr(optIr, stats) {
    if (!optIr.length) {
      el.optIrBody.innerHTML = `<tr><td colspan="4" class="dim-row">No optimized instructions available.</td></tr>`;
      el.optStatsPill.classList.add("hidden");
      el.optStatsDetails.textContent = "0 instructions";
      return;
    }

    const red = stats.reduction_count || 0;
    const pct = stats.reduction_pct || 0;
    if (red > 0) {
      el.optStatsPill.textContent = `-${pct}% (${red} dead/folded)`;
      el.optStatsPill.classList.remove("hidden");
      el.optStatsDetails.textContent = `${stats.original_count} → ${stats.optimized_count} instructions (${red} eliminated)`;
    } else {
      el.optStatsPill.classList.add("hidden");
      el.optStatsDetails.textContent = `${stats.optimized_count} instructions (No dead code found)`;
    }

    let html = "";
    optIr.forEach((ins) => {
      html += `
        <tr>
          <td>${ins.index}</td>
          <td><span class="chip">${escapeHtml(ins.op)}</span></td>
          <td>${ins.arg !== null ? `<code>${escapeHtml(ins.arg)}</code>` : '<span class="dim-row">—</span>'}</td>
          <td>Line ${ins.line}</td>
        </tr>`;
    });
    el.optIrBody.innerHTML = html;
  }

  function renderTelemetry(telemetry) {
    if (!telemetry.length) {
      el.telemetryBadge.classList.add("hidden");
      el.telemetryView.innerHTML = `
        <div class="empty-state">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <p>No <code>SYNTHESIZE</code> directive in this workflow.</p>
          <button id="load-synth-demo-btn-inline" class="btn btn-secondary btn-sm" style="margin-top: 12px;">Load Synthesis Demo</button>
        </div>`;
      const btn = document.getElementById("load-synth-demo-btn-inline");
      if (btn) btn.addEventListener("click", () => switchExample("synthesis_demo"));
      return;
    }

    el.telemetryBadge.classList.remove("hidden");
    const t = telemetry[0];

    const initStr = Object.entries(t.initial_state)
      .map(([k, v]) => `${k}=${v}`)
      .join(", ") || "None";

    let stepsHtml = "";
    if (t.plan.length > 0) {
      t.plan.forEach((step, i) => {
        stepsHtml += `
          <div class="timeline-step">
            <span class="step-num">${i + 1}</span>
            <span class="step-action">${escapeHtml(step)}</span>
          </div>`;
      });
    } else if (t.success) {
      stepsHtml = `<div class="terminal-dim">Initial state already satisfied target condition (0 steps needed).</div>`;
    } else {
      stepsHtml = `<div class="terminal-error">No safe recovery sequence found within search budget of ${t.budget} steps.</div>`;
    }

    el.telemetryView.innerHTML = `
      <div class="telemetry-card">
        <div class="kpi-grid">
          <div class="kpi-box">
            <div class="kpi-label">Synthesis Outcome</div>
            <div class="kpi-value ${t.success ? "highlight-purple" : "highlight-red"}">${t.success ? "Safe Plan Found" : "Fail-Closed"}</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">Search Depth / Budget</div>
            <div class="kpi-value">${t.search_depth} / ${t.budget} steps</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">States Explored</div>
            <div class="kpi-value">${t.states_explored} states</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">Transitions Pruned by Invariants</div>
            <div class="kpi-value highlight-red">${t.transitions_rejected} transitions</div>
          </div>
        </div>

        <div class="state-transition-box">
          <div><strong>Initial State:</strong> <code>[${escapeHtml(initStr)}]</code></div>
          <div class="transition-arrow">&rarr; BFS Bounded Search &rarr;</div>
          <div><strong>Target:</strong> <code>${escapeHtml(t.target_condition)}</code></div>
        </div>

        <div class="plan-timeline">
          <div class="timeline-title">Synthesized Safe Action Sequence:</div>
          <div class="timeline-steps">${stepsHtml}</div>
        </div>

        <div class="info-card">
          <div class="info-card-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Safety-by-Construction Guarantee</span>
          </div>
          <p>The compiler explored candidate device transitions and rejected <strong>${t.transitions_rejected}</strong> intermediate states that violated declared global safety contracts. The synthesized plan is guaranteed safe before code generation.</p>
        </div>
      </div>`;
  }

  function renderError(msg) {
    el.terminal.innerHTML = `<div class="terminal-line terminal-error">✖ ${escapeHtml(msg)}</div>`;
  }

  // Tab Navigation
  function switchTab(targetTabId) {
    state.activeTab = targetTabId;
    el.tabBtns.forEach((btn) => {
      const match = btn.getAttribute("data-tab") === targetTabId;
      btn.classList.toggle("active", match);
      btn.setAttribute("aria-selected", match);
    });
    el.tabPanes.forEach((pane) => {
      pane.classList.toggle("active", pane.id === targetTabId);
    });
  }

  // Example Switching & Dirty State Handling
  async function loadExamplesList() {
    try {
      const examples = await apiGet("/api/examples");
      state.examples = examples;

      let selectHtml = "";
      let sidebarHtml = "";

      for (let ex of examples) {
        selectHtml += `<option value="${ex.id}">${escapeHtml(ex.name)}</option>`;
        sidebarHtml += `
          <div class="example-item ${ex.id === state.currentExampleId ? "active" : ""}" data-id="${ex.id}" role="listitem">
            <div class="example-title-row">
              <span class="example-name">${escapeHtml(ex.name)}</span>
              <span class="example-badge ${escapeHtml(ex.badge)}">${escapeHtml(ex.badge)}</span>
            </div>
            <div class="example-desc">${escapeHtml(ex.description)}</div>
          </div>`;
      }

      el.exampleSelect.innerHTML = selectHtml;
      el.examplesList.innerHTML = sidebarHtml;

      // Select listeners
      el.exampleSelect.value = state.currentExampleId;
      el.examplesList.querySelectorAll(".example-item").forEach((item) => {
        item.addEventListener("click", () => {
          promptSwitchExample(item.getAttribute("data-id"));
        });
      });
    } catch (err) {
      console.error("Failed to load examples:", err);
    }
  }

  function promptSwitchExample(targetId) {
    if (targetId === state.currentExampleId && !state.isDirty) return;
    if (state.isDirty) {
      state.pendingSwitchExampleId = targetId;
      el.confirmModal.classList.remove("hidden");
    } else {
      switchExample(targetId);
    }
  }

  async function switchExample(exampleId) {
    try {
      const data = await apiGet(`/api/examples/${exampleId}`);
      state.currentExampleId = data.id;
      state.originalSource = data.source;
      state.isDirty = false;
      el.activeFilename.textContent = `${data.id}.flow`;
      el.exampleSelect.value = data.id;

      // Update sidebar active class
      el.examplesList.querySelectorAll(".example-item").forEach((item) => {
        item.classList.toggle("active", item.getAttribute("data-id") === data.id);
      });

      el.codeInput.value = data.source;
      updateEditor();
      compileWorkflow();
    } catch (err) {
      renderError(`Could not load example '${exampleId}': ${err.message}`);
    }
  }

  // Tutorial Engine
  const TUTORIAL_STEPS = [
    {
      title: "1. Welcome & Basic Workflows",
      example: "temperature",
      desc: "FlowScript workflows begin with START and finish with END. Devices are declared and controlled with TURN_ON / TURN_OFF commands. Press 'Run Workflow' to simulate execution.",
      expected: "The fan activates (fan → ON) when temperature exceeds 30, polls simulated status in a loop, and shuts down.",
    },
    {
      title: "2. Sensed Properties & Conditions",
      example: "temperature",
      desc: "FlowScript lets you query device states directly using property expressions like 'fan.status == ON'. Try modifying the temperature threshold in the editor.",
      expected: "Conditional branches take the IF or ELSE paths based on sensed variables and device states.",
    },
    {
      title: "3. Constant Folding & Optimization",
      example: "optimization_demo",
      desc: "The FlowScript compiler features a multi-pass optimizer. In the 'Optimized IR' tab, watch how arithmetic expressions (10 + 5) are folded into constants (15) and dead code branches are eliminated.",
      expected: "Optimized IR instruction count is significantly reduced compared to raw IR bytecode.",
    },
    {
      title: "4. Global Safety Invariants",
      example: "recovery_demo",
      desc: "Global 'INVARIANT' contracts enforce universal safety rules that must hold across all device actuations. Local 'REQUIRE' and 'ENSURE' assertions guard preconditions and postconditions.",
      expected: "Any actuation violating a global invariant triggers an immediate uncatchable InvariantViolation.",
    },
    {
      title: "5. Explicit Fault Recovery",
      example: "recovery_demo",
      desc: "When a fault or failed precondition occurs inside a 'TRY' block, execution cleanly transfers to the 'RECOVER' handler. Handlers can safely isolate faults and activate backups.",
      expected: "The failed precondition enters RECOVER, turning on the backup cooler and satisfying safety contracts.",
    },
    {
      title: "6. Automated Recovery Synthesis",
      example: "synthesis_demo",
      desc: "Instead of hand-writing recovery sequences, write 'SYNTHESIZE <target>'. FlowScript uses bounded BFS to synthesize the minimal sequence of approved actions that achieves safety without violating invariants.",
      expected: "The 'Recovery Synthesis' tab displays search depth, states explored, and rejected hazardous transitions.",
    },
    {
      title: "7. Fault Injection & Self-Healing",
      example: "fault_recovery_demo",
      desc: "Simulate real-world hardware failures (actuation failure, state mismatch, latency) with zero non-determinism. Toggle 'Faults: ON' and click 'Run Workflow' to verify that TRY/RECOVER safely isolates faults and activates backup devices.",
      expected: "The primary pump fails actuation or state contract, triggering the self-healing RECOVER block to engage the backup pump.",
    },
  ];

  function openTutorial() {
    state.tutorialStep = 0;
    el.tutorialBanner.classList.remove("hidden");
    renderTutorialStep();
  }

  function renderTutorialStep() {
    const s = TUTORIAL_STEPS[state.tutorialStep];
    el.tutStepNum.textContent = state.tutorialStep + 1;
    el.tutTitle.textContent = s.title;
    el.tutDesc.textContent = s.desc;
    el.tutExpectedText.textContent = s.expected;
    el.tutPrevBtn.disabled = state.tutorialStep === 0;
    el.tutNextBtn.textContent = state.tutorialStep === TUTORIAL_STEPS.length - 1 ? "Finish" : "Next →";
  }

  function nextTutorialStep() {
    if (state.tutorialStep < TUTORIAL_STEPS.length - 1) {
      state.tutorialStep++;
      renderTutorialStep();
      const s = TUTORIAL_STEPS[state.tutorialStep];
      promptSwitchExample(s.example);
    } else {
      el.tutorialBanner.classList.add("hidden");
    }
  }

  function prevTutorialStep() {
    if (state.tutorialStep > 0) {
      state.tutorialStep--;
      renderTutorialStep();
      const s = TUTORIAL_STEPS[state.tutorialStep];
      promptSwitchExample(s.example);
    }
  }

  // Health Monitoring
  async function checkBackendHealth() {
    try {
      const data = await apiGet("/api/health");
      if (data.status === "ok") {
        el.backendStatus.className = "status-pill status-connected";
        el.backendStatus.querySelector(".status-text").textContent = "Connected";
      }
    } catch (e) {
      el.backendStatus.className = "status-pill status-offline";
      el.backendStatus.querySelector(".status-text").textContent = "Backend Offline";
    }
  }

  // Event Listeners Setup
  function initEventListeners() {
    // Editor events
    el.codeInput.addEventListener("input", updateEditor);
    el.codeInput.addEventListener("scroll", syncScroll);
    el.codeInput.addEventListener("keydown", handleEditorKeyDown);
    el.codeInput.addEventListener("click", updateCursorPosition);
    el.codeInput.addEventListener("keyup", updateCursorPosition);

    // Global keyboard shortcuts
    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        runWorkflow();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        compileWorkflow();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        compileWorkflow();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "\\") {
        e.preventDefault();
        el.sidebar.classList.toggle("collapsed");
      }
    });

    // Toolbar actions
    el.compileBtn.addEventListener("click", compileWorkflow);
    el.runBtn.addEventListener("click", runWorkflow);

    el.optToggle.addEventListener("change", () => {
      state.optimize = el.optToggle.checked;
      el.optToggleLabel.textContent = `Optimizer: ${state.optimize ? "ON" : "OFF"}`;
      compileWorkflow();
    });

    // Fault Injection Controls (Phase 4)
    el.faultToggle.addEventListener("change", () => {
      state.faultInjectionEnabled = el.faultToggle.checked;
      el.faultToggleLabel.textContent = `Faults: ${state.faultInjectionEnabled ? "ON" : "OFF"}`;
      el.faultPresetWrapper.classList.toggle("hidden", !state.faultInjectionEnabled);
      el.monitoringBadge.classList.toggle("hidden", !state.faultInjectionEnabled);
      if (state.faultInjectionEnabled) {
        el.kpiFaultStatus.textContent = "Active";
        el.kpiFaultStatus.className = "kpi-value highlight-amber";
      } else {
        el.kpiFaultStatus.textContent = "Disabled";
        el.kpiFaultStatus.className = "kpi-value";
      }
    });

    el.faultPresetSelect.addEventListener("change", (e) => {
      const val = e.target.value;
      if (val === "custom") {
        openFaultModal();
      } else {
        state.faultPreset = val;
      }
    });

    function openFaultModal() {
      el.cfgFaultEnable.value = state.faultInjectionEnabled ? "true" : "false";
      el.cfgFaultScenario.value = state.faultPreset;
      el.cfgRuleDevice.value = state.customFault.device;
      el.cfgRuleAction.value = state.customFault.action;
      el.cfgRuleType.value = state.customFault.fault_type;
      el.cfgRuleStep.value = state.customFault.trigger_step;
      el.cfgRuleDelay.value = state.customFault.delay_seconds;
      el.cfgRuleMismatch.value = state.customFault.mismatch_state;
      el.faultModal.classList.remove("hidden");
    }

    if (el.faultConfigBtn) {
      el.faultConfigBtn.addEventListener("click", openFaultModal);
    }
    if (el.faultModalCloseBtn) {
      el.faultModalCloseBtn.addEventListener("click", () => el.faultModal.classList.add("hidden"));
    }
    if (el.cfgFaultScenario) {
      el.cfgFaultScenario.addEventListener("change", (e) => {
        const scn = e.target.value;
        if (scn === "action_failure") {
          el.cfgRuleDevice.value = "primary_pump";
          el.cfgRuleAction.value = "TURN_ON";
          el.cfgRuleType.value = "action_failure";
          el.cfgRuleStep.value = 1;
          el.cfgRuleDelay.value = 0.0;
          el.cfgRuleMismatch.value = "OFF";
        } else if (scn === "state_mismatch") {
          el.cfgRuleDevice.value = "primary_pump";
          el.cfgRuleAction.value = "TURN_ON";
          el.cfgRuleType.value = "state_mismatch";
          el.cfgRuleStep.value = 1;
          el.cfgRuleDelay.value = 0.0;
          el.cfgRuleMismatch.value = "OFF";
        } else if (scn === "delayed_completion") {
          el.cfgRuleDevice.value = "primary_pump";
          el.cfgRuleAction.value = "TURN_ON";
          el.cfgRuleType.value = "delayed_completion";
          el.cfgRuleStep.value = 1;
          el.cfgRuleDelay.value = 2.5;
          el.cfgRuleMismatch.value = "OFF";
        }
      });
    }

    if (el.faultModalApplyBtn) {
      el.faultModalApplyBtn.addEventListener("click", () => {
        state.faultInjectionEnabled = el.cfgFaultEnable.value === "true";
        state.faultPreset = el.cfgFaultScenario.value;
        state.customFault = {
          device: el.cfgRuleDevice.value.trim() || "primary_pump",
          action: el.cfgRuleAction.value,
          fault_type: el.cfgRuleType.value,
          trigger_step: parseInt(el.cfgRuleStep.value, 10) || 1,
          delay_seconds: parseFloat(el.cfgRuleDelay.value) || 0.0,
          mismatch_state: el.cfgRuleMismatch.value,
        };

        el.faultToggle.checked = state.faultInjectionEnabled;
        el.faultToggleLabel.textContent = `Faults: ${state.faultInjectionEnabled ? "ON" : "OFF"}`;
        el.faultPresetWrapper.classList.toggle("hidden", !state.faultInjectionEnabled);
        el.faultPresetSelect.value = state.faultPreset;
        el.faultModal.classList.add("hidden");

        runWorkflow();
      });
    }

    if (el.loadFaultDemoBtn) {
      el.loadFaultDemoBtn.addEventListener("click", () => {
        state.faultInjectionEnabled = true;
        el.faultToggle.checked = true;
        el.faultToggleLabel.textContent = "Faults: ON";
        el.faultPresetWrapper.classList.remove("hidden");
        switchExample("fault_recovery_demo");
      });
    }

    el.toggleSidebarBtn.addEventListener("click", () => {
      el.sidebar.classList.toggle("collapsed");
    });

    el.formatBtn.addEventListener("click", formatCode);

    el.copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(el.codeInput.value);
        el.copyText.textContent = "Copied!";
        setTimeout(() => { el.copyText.textContent = "Copy"; }, 1500);
      } catch (err) {
        console.error("Clipboard copy failed:", err);
      }
    });

    el.downloadBtn.addEventListener("click", () => {
      const blob = new Blob([el.codeInput.value], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${state.currentExampleId || "workflow"}.flow`;
      a.click();
      URL.revokeObjectURL(a.href);
    });

    el.resetBtn.addEventListener("click", () => {
      el.codeInput.value = state.originalSource;
      updateEditor();
    });

    el.exampleSelect.addEventListener("change", (e) => {
      promptSwitchExample(e.target.value);
    });

    // Inspector Tabs
    el.tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        switchTab(btn.getAttribute("data-tab"));
      });
    });

    // Token filter input
    el.tokenFilter.addEventListener("input", filterTokensTable);

    if (el.loadSynthDemoBtn) {
      el.loadSynthDemoBtn.addEventListener("click", () => switchExample("synthesis_demo"));
    }

    // Tutorial controls
    el.tutorialBtn.addEventListener("click", openTutorial);
    el.tutCloseBtn.addEventListener("click", () => el.tutorialBanner.classList.add("hidden"));
    el.tutNextBtn.addEventListener("click", nextTutorialStep);
    el.tutPrevBtn.addEventListener("click", prevTutorialStep);
    el.tutLoadBtn.addEventListener("click", () => {
      const s = TUTORIAL_STEPS[state.tutorialStep];
      switchExample(s.example);
    });
    el.tutRunBtn.addEventListener("click", runWorkflow);

    // Research Model Modal
    el.researchBtn.addEventListener("click", () => el.researchModal.classList.remove("hidden"));
    el.modalCloseBtn.addEventListener("click", () => el.researchModal.classList.add("hidden"));
    el.modalOkBtn.addEventListener("click", () => el.researchModal.classList.add("hidden"));

    // Confirm Discard Modal
    el.confirmCloseBtn.addEventListener("click", () => el.confirmModal.classList.add("hidden"));
    el.confirmCancelBtn.addEventListener("click", () => el.confirmModal.classList.add("hidden"));
    el.confirmProceedBtn.addEventListener("click", () => {
      el.confirmModal.classList.add("hidden");
      if (state.pendingSwitchExampleId) {
        switchExample(state.pendingSwitchExampleId);
        state.pendingSwitchExampleId = null;
      }
    });
  }

  // App Initialization
  async function init() {
    initEventListeners();
    await checkBackendHealth();
    await loadExamplesList();
    await switchExample("temperature");
    setInterval(checkBackendHealth, 10000);
  }

  // Start application once DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
