# Lifecycle and resources

## Compilation and replacement

Prefer the project's existing precompiled `.metallib` path. Load from the bundle that owns the library, which may be a package resource bundle rather than the application bundle. Cache functions and pipeline states using the configuration that changes them: source/library identity, entry points, function constants, attachment formats, sample count, and vertex layout.

Runtime source compilation is appropriate for a shader editor or an algorithm that genuinely changes. `makeLibrary(source:options:)` creates a library, not a configured renderer. Create matching functions and a render pipeline after library success, and surface those error stages separately. Source-string compilation does not supply a filesystem include search path: assemble shared helpers into the source or use an established preprocessing path. Debounce edit-driven compilation, discard stale completions, and retain the last good pipeline while a candidate compiles. An animation parameter should update a uniform; suitable fixed variants can use function constants.

Apple's [source compilation API](https://developer.apple.com/documentation/metal/mtldevice/makelibrary(source:options:)) documents synchronous compilation and include limits; its [pipeline creation APIs](https://developer.apple.com/documentation/metal/mtldevice/makerenderpipelinestate(descriptor:)) define the next stage. Use async variants where appropriate to the existing application.

## Minimal per-frame ownership

Reuse the device, queue, pipeline, samplers, and size-stable offscreen textures. Create a command buffer for the frame. Acquire the drawable close to encoding work that needs it; if unavailable or size is zero, skip the frame and release any acquired in-flight slot. Bind this frame's resources, encode each pass, end encoders, register completion/error handling, schedule presentation, and commit. Offscreen work needs no drawable or presentation.

Use a bounded number of in-flight resource versions suited to the renderer. Retire/reuse a uniform slot only after the GPU has finished the commands that read it. Completion handlers must release slots on success and failure; pre-commit early exits also release them. Do not replace this ownership scheme with a per-frame CPU wait just to hide a race. [CPU/GPU synchronization](https://developer.apple.com/documentation/metal/synchronizing-cpu-and-gpu-work) and [completion handlers](https://developer.apple.com/documentation/metal/mtlcommandbuffer/addcompletedhandler(_:)) describe the primitives.

## Resource contracts

- A shader slot does not allocate a resource. Match buffer offsets/layout/lengths, texture indices and access, sampler state, and stage bindings explicitly. A Swift `SIMD3<Float>` is not interchangeable with a packed three-float array; use shared definitions or verify offsets and stride.
- Declare texture usage for actual operations, such as `.renderTarget` and `.shaderRead` for a render-then-sample intermediate. Ping-pong feedback textures; sampling an ordinary texture while simultaneously writing it as a render attachment is not a portable feedback mechanism.
- Keep resources alive until using commands complete, including resources reached indirectly. Default retained command buffers help with referenced objects but do not prevent CPU overwrite or prove indirect-resource ownership correct. Preserve explicit owners for heap/argument-buffer resources.
- `.shared` provides CPU-accessible storage, not concurrent access synchronization. `.private` resources need a supported GPU transfer path for readback; `.managed` resources on supporting Macs need the appropriate CPU modification notification and GPU-to-CPU synchronization before reading. Check command completion/errors before trusting output.

See [resource storage modes](https://developer.apple.com/documentation/metal/mtlstoragemode) and the [MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) for the actual platform and memory-layout rules.

## Classic Metal hazards

For directly bound, tracked resources on a classic `MTLCommandQueue`, Metal handles eligible GPU resource hazards. Heap resources commonly default to untracked; inspect the descriptor rather than assuming. Resources accessed indirectly through argument buffers need the applicable `useResource`/`useHeap` declarations; binding the argument buffer alone is insufficient.

With untracked resources, establish every producer/consumer dependency yourself: appropriate intrapass barriers where supported, fences between passes on a queue, and event signal/wait dependencies across queues. Resource declaration, ownership, CPU/GPU exclusion, and execution ordering are separate responsibilities; `useResource` is not a replacement for all synchronization. Rendering order alone should not be relied upon to make untracked hazards disappear.

For a supported classic cross-queue dependency on one device, signal an `MTLEvent` with `MTLCommandBuffer.encodeSignalEvent(_:value:)` after the producing work and wait for that value with `encodeWaitForEvent(_:value:)` before the consuming work. End active encoders before encoding these command-buffer operations, and use increasing event values when reusing an event. Apple's [event overview](https://developer.apple.com/documentation/metal/about-synchronization-events) and [single-device synchronization example](https://developer.apple.com/documentation/metal/synchronizing-events-within-a-single-device) describe this scheduling.

An unsatisfied wait in a submitted command buffer needs a reachable signal at an equal-or-greater value. Encoding a signal does not submit it: commit the producing command buffer and ensure its work can reach the signal without a circular dependency. If a frame is skipped, setup fails, or an early return prevents producer submission, omit the dependent consumer work and its wait. An already-satisfied value proceeds immediately; a producer failure that prevents its signal needs error handling for dependent work, not an assumption that the wait will clear. Apple's [event wait API](https://developer.apple.com/documentation/metal/mtlcommandbuffer/encodewaitforevent(_:value:)) specifies when subsequent passes can continue.

Check a render/compute producer followed by a sampling consumer using a changing frame marker. Check frame-slot wraparound and resize while work is in flight. Apple's [hazard-tracking modes](https://developer.apple.com/documentation/metal/mtlhazardtrackingmode), [fence API](https://developer.apple.com/documentation/metal/mtlfence), and [resource declaration API](https://developer.apple.com/documentation/metal/mtlrendercommandencoder/useresource(_:usage:)) explain the relevant classic behavior. Use classic encoder fence methods; Metal 4 stage/submission examples do not change an existing classic queue's contract.

Sources reviewed 2026-10-13.
