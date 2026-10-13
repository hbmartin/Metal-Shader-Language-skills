# Measured profiling

## Establish a comparable workload

Record the target device/GPU, OS/toolchain, build configuration, resolution, scene/input, shader parameters, precision, and frames in flight. Warm up shader/pipeline creation and resource allocation before measuring steady-state rendering; measure cold compilation separately when it is the reported problem. Hold animation time/seed fixed for image comparisons and use a repeatable animated interval for frame-time measurements.

Disable validation and temporary diagnostic rendering for the baseline. Capture/profiling overhead and GPU power/thermal state can affect timing. Compare multiple runs under comparable conditions and distinguish a real improvement from noise.

## Match the tool to the question

| Question | Tool and observation |
|---|---|
| Which pass/draw is expensive? | Xcode Metal capture and Performance timeline; preserve actual pass overlap |
| Which shader operation dominates? | Shader profiler, per-line metrics, and supported GPU counters after replay |
| Is the GPU waiting for the CPU? | Instruments Game Performance / Metal System Trace with CPU and GPU timelines |
| Are allocations or synchronization causing stalls? | Resource events, memory views, and command dependencies |
| Does the regression occur during live animation? | Metal Performance HUD when supported, followed by a focused capture/trace |

In Xcode, include shader sources, capture the representative workload, and enable profiling after replay or profile the captured trace. Inspect expensive pipelines/commands and their bound inputs before changing code. The available counters and shader-debugger capabilities depend on GPU and toolchain; verify those for the selected target. Use Instruments to correlate CPU encoding, compilation, synchronization, GPU work, and presentation.

Do not add each pass's isolated duration and call the sum frame time: GPU stages can overlap, while isolated measurements change that overlap. Per-line source time also includes stalls and mapped instructions; it is evidence for an experiment, not a guarantee that replacing that line fixes the bottleneck.

## Choose one evidence-backed change

- If fragment work dominates, test a lower render resolution or procedural quality setting, then compare the intended visual loss against the measured gain.
- If math dominates, experiment with fewer noise octaves, bounded ray-march work, algebraic simplification, or specialization of stable feature choices. Keep the required appearance and numerical behavior.
- If memory dominates, inspect formats, access patterns, redundant reads, and pass intermediates. Threadgroup staging is an option to measure, not an automatic improvement.
- If register pressure or occupancy limits the shader, try narrowing eligible color/intermediate types or reducing live values. Preserve precision for coordinates and sensitive calculations unless evidence supports reducing it.
- If CPU compilation or allocation dominates, cache compatible pipelines/resources and keep compilation out of repeated draw work when the task permits. A specialized function constant can remove branches but creates a variant that must be managed.

Re-run the same workload after the change, including correctness and visual comparison. Report the metric, units, baseline and new measurements, workload, and any quality difference. Do not claim a GPU speedup from a CPU wall-clock interval containing compilation, presentation waits, or resource readback.

## Sources

- [Apple: Optimizing GPU performance](https://developer.apple.com/documentation/xcode/optimizing-gpu-performance) — profiling replay, overlapping work, and counter interpretation.
- [Apple: Inspecting shaders](https://developer.apple.com/documentation/xcode/inspecting-shaders) — per-line inspection and shader reload.
- [Apple: Analyzing the performance of your Metal app](https://developer.apple.com/documentation/xcode/analyzing-the-performance-of-your-metal-app) — Instruments Game Performance and CPU/GPU correlation.
- [Apple: Learn performance best practices for Metal shaders](https://developer.apple.com/videos/play/tech-talks/111373/) — specialization, address-space choices, and measured use of smaller data types.
- [Apple: Monitoring your Metal app's graphics performance](https://developer.apple.com/documentation/xcode/monitoring-your-metal-apps-graphics-performance) — supported live HUD diagnostics.
