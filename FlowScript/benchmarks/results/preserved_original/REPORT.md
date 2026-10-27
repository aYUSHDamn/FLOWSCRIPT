# FlowScript Phase 5 Experimental Evaluation Report

## 1. Executive Summary & Research Gap

This report provides an empirical evaluation of FlowScript's compiler-synthesized, safety-constrained recovery mechanism.
Traditional workflow and domain-specific execution systems typically rely on **unhandled crash semantics** (fail-stop) or **blind local retries** (fixed re-actuation).
While fixed retries can mitigate transient glitches, they fundamentally fail when:
1. Failures are persistent (e.g. damaged physical actuators).
2. Failures are silent (state mismatches where observed state diverges from requested state).
3. Recovery requires coordinating multiple devices across strict global safety invariants.

FlowScript bridges this gap by coupling a **discrete finite-state model** with **bounded BFS synthesis** directly in the compiler pass.

## 2. Experimental Methodology & Metric Definitions

### 2.1 Evaluated Comparison Methods
- **Method 1: No Recovery (Baseline 1)**: Workflow executes without recovery blocks; any actuation or contract fault terminates execution fail-closed.
- **Method 2: Fixed Retry (Baseline 2)**: Standard industrial retry policy re-attempting the identical failing actuation up to $K=3$ times with local error trapping.
- **Method 3: FlowScript Synthesis (Proposed)**: Compiler synthesizes the minimal sequence of approved actions from the observed failure state using bounded BFS with invariant pruning.

### 2.2 Formal Metric Definitions
- **Task Success Rate ($R_{\text{task}}$)**: $\frac{N_{\text{success}}}{N_{\text{total}}}$, where success requires $S_{\text{final}} \models \text{Target}$ and zero unhandled exceptions.
- **Global Invariant Violations ($V_{\text{inv}}$)**: Total occurrences of state transitions violating declared global invariants (must be strictly 0).
- **Recovery Success Rate ($R_{\text{rec}}$)**: $\frac{N_{\text{recovered}}}{N_{\text{faulted}}}$, measuring successful goal restoration following fault injection.
- **Unhandled Failure Rate ($R_{\text{fail}}$)**: Proportion of trials aborting due to unhandled runtime errors.
- **Synthesis Time ($T_{\text{synth}}$)**: Wall-clock duration of the BFS graph search algorithm in milliseconds.
- **Execution Time ($T_{\text{exec}}$)**: Virtual machine stack-machine bytecode execution duration in milliseconds.
- **States Explored**: Total discrete graph nodes dequeued during BFS search.
- **Transitions Rejected**: Candidate device actuations pruned because intermediate state $S'$ violated an invariant.

## 3. Quantitative Results & Summary Tables

### 3.1 Comparative Performance Matrix Across Scenarios

| Scenario ID | Comparison Method | Trials ($N$) | Task Success | Recovery Success | Invariant Violations | Mean Total Time (ms) | 95% CI (ms) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `S1_transient` | **fixed_retry** | 5 | 100.0% | 100.0% | 0 | 0.364 ms | ±0.033 |
| `S1_transient` | **no_recovery** | 5 | 0.0% | 0.0% | 0 | 0.148 ms | ±0.056 |
| `S1_transient` | **synthesized_recovery** | 5 | 100.0% | 100.0% | 0 | 0.260 ms | ±0.047 |
| `S2_persistent_backup` | **fixed_retry** | 5 | 0.0% | 0.0% | 0 | 0.360 ms | ±0.005 |
| `S2_persistent_backup` | **no_recovery** | 5 | 0.0% | 0.0% | 0 | 0.115 ms | ±0.002 |
| `S2_persistent_backup` | **synthesized_recovery** | 5 | 100.0% | 100.0% | 0 | 0.271 ms | ±0.047 |
| `S3_state_mismatch` | **fixed_retry** | 5 | 0.0% | 0.0% | 0 | 0.398 ms | ±0.049 |
| `S3_state_mismatch` | **no_recovery** | 5 | 0.0% | 0.0% | 0 | 0.127 ms | ±0.002 |
| `S3_state_mismatch` | **synthesized_recovery** | 5 | 100.0% | 100.0% | 0 | 0.252 ms | ±0.005 |
| `S4_multi_device_inv` | **fixed_retry** | 5 | 0.0% | 0.0% | 5 | 0.654 ms | ±0.057 |
| `S4_multi_device_inv` | **no_recovery** | 5 | 0.0% | 0.0% | 0 | 0.321 ms | ±0.043 |
| `S4_multi_device_inv` | **synthesized_recovery** | 5 | 100.0% | 100.0% | 0 | 0.560 ms | ±0.041 |
| `S5_fail_closed` | **fixed_retry** | 5 | 0.0% | 0.0% | 5 | 0.469 ms | ±0.023 |
| `S5_fail_closed` | **no_recovery** | 5 | 0.0% | 0.0% | 5 | 0.215 ms | ±0.002 |
| `S5_fail_closed` | **synthesized_recovery** | 5 | 0.0% | 0.0% | 0 | 0.139 ms | ±0.002 |
| `S7_probabilistic` | **fixed_retry** | 30 | 0.0% | 0.0% | 0 | 0.623 ms | ±0.039 |
| `S7_probabilistic` | **no_recovery** | 30 | 0.0% | 0.0% | 0 | 0.276 ms | ±0.013 |
| `S7_probabilistic` | **synthesized_recovery** | 30 | 40.0% | 40.0% | 0 | 0.427 ms | ±0.013 |

### 3.2 State-Space Scalability & Search Budget Analysis (Scenario S6)

| Controllable Devices ($D$) | State Space ($2^D$) | Search Budget ($k$) | Success | Plan Length | States Explored | Transitions Pruned | Mean Synthesis Time (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 2 | 4 | 1 | FAIL (Exhausted) | 0 | 2.0 | 1.0 | 0.014 ± 0.004 |
| 2 | 4 | 2 | YES | 2 | 2.0 | 1.0 | 0.015 ± 0.001 |
| 2 | 4 | 3 | YES | 2 | 2.0 | 1.0 | 0.014 ± 0.000 |
| 2 | 4 | 4 | YES | 2 | 2.0 | 1.0 | 0.015 ± 0.002 |
| 2 | 4 | 5 | YES | 2 | 2.0 | 1.0 | 0.014 ± 0.001 |
| 4 | 16 | 1 | FAIL (Exhausted) | 0 | 3.0 | 2.0 | 0.025 ± 0.003 |
| 4 | 16 | 2 | YES | 2 | 2.0 | 2.0 | 0.028 ± 0.001 |
| 4 | 16 | 3 | YES | 2 | 2.0 | 2.0 | 0.027 ± 0.000 |
| 4 | 16 | 4 | YES | 2 | 2.0 | 2.0 | 0.029 ± 0.006 |
| 4 | 16 | 5 | YES | 2 | 2.0 | 2.0 | 0.027 ± 0.000 |
| 6 | 64 | 1 | FAIL (Exhausted) | 0 | 4.0 | 3.0 | 0.040 ± 0.003 |
| 6 | 64 | 2 | YES | 2 | 2.0 | 3.0 | 0.046 ± 0.003 |
| 6 | 64 | 3 | YES | 2 | 2.0 | 3.0 | 0.046 ± 0.004 |
| 6 | 64 | 4 | YES | 2 | 2.0 | 3.0 | 0.044 ± 0.001 |
| 6 | 64 | 5 | YES | 2 | 2.0 | 3.0 | 0.044 ± 0.000 |
| 8 | 256 | 1 | FAIL (Exhausted) | 0 | 5.0 | 4.0 | 0.067 ± 0.007 |
| 8 | 256 | 2 | YES | 2 | 2.0 | 4.0 | 0.073 ± 0.003 |
| 8 | 256 | 3 | YES | 2 | 2.0 | 4.0 | 0.071 ± 0.001 |
| 8 | 256 | 4 | YES | 2 | 2.0 | 4.0 | 0.082 ± 0.013 |
| 8 | 256 | 5 | YES | 2 | 2.0 | 4.0 | 0.073 ± 0.001 |

## 4. Statistical Significance Testing (Scenario S7: Probabilistic Faults)

- **Sample Size**: N = 30 trials per method across identical pseudo-random seeds (p_fault = 0.4).
- **FlowScript Task Success Rate**: **40.0%**
- **Fixed Retry Task Success Rate**: **0.0%**
- **Two-Proportion Z-Test**: z = 3.873, p = 0.000108
- **Statistical Significance**: Statistically significant at alpha=0.001.
- **Execution Latency**: FlowScript synthesis added an average of only **-0.196 ms** over fixed retries.

## 5. Key Research Findings

1. **Safety-by-Construction**: Across all evaluated scenarios and trials, FlowScript produced **zero invariant violations** ($V_{\text{inv}} = 0$). In scenario S5, where safety invariants strictly blocked all paths to the target, the compiler aborted with a clean diagnostic rather than emitting an unsafe recovery sequence.
2. **Superiority Over Blind Retries on Persistent & Silent Faults**: While fixed retries recovered from transient faults (Scenario S1), they achieved 0% success on persistent faults (Scenario S2) and silent state mismatches (Scenario S3). FlowScript achieved 100% recovery by synthesizing transitions to redundant backup devices.
3. **Multi-Device Coordinated Recovery**: When a single target action is blocked by a declared invariant (Scenario S4), FlowScript automatically discovers the multi-step resolution sequence (`TURN_OFF heater`, `TURN_ON backup_cooler`), which cannot be achieved by single-action retries.
4. **Sub-Millisecond Synthesis Overhead**: For realistic state spaces up to $D=8$ ($2^8 = 256$ states), BFS graph search completed in under **0.5 milliseconds**, making compile-time synthesis practical for responsive execution.

## 6. Experimental Limitations & Physical Deployment Considerations

- **Discrete Binary Abstraction**: The simulator assumes discrete boolean states ($S \in \{\text{ON}, \text{OFF}\}$) with instantaneous state transitions. Real cyber-physical deployments involve continuous physical dynamics (e.g., thermal dissipation delays, actuator slew rates).
- **Scalability Limit of Uninformed BFS**: Without heuristic search (e.g. A*) or symbolic BDD representations, uninformed BFS search exhibits $O(b^d)$ time complexity for large device counts ($D > 16$).
- **Static Topology Assumption**: The action model assumes available devices and approved actions are fully known at compile time.

## 7. Reproduction Instructions

To reproduce the complete benchmark evaluation, re-generate all CSV tables, and render figures:
```powershell
python benchmarks/run_benchmarks.py
```
