# Resources and library choices

## Storage and bindings

Use the project's existing allocation policy unless the workload needs a specific change. On Apple GPUs, shared resources permit CPU access; private resources are GPU-only; memoryless storage is for eligible temporary render textures, not compute buffers or persistent feedback state. On relevant Intel/AMD Mac targets, managed storage needs coherency operations. For managed buffers, CPU changes require `didModifyRange`; GPU changes need the appropriate blit synchronization and completion before CPU access.

Record binding indices, byte offsets, element stride, pixel format, mip/slice, and read/write use. Allocate texture usage for the shader and render operations actually performed. A `texture2d<float>` does not imply a floating-point storage format; the pixel format controls conversion and representable range. Verify read/write format and feature support on the target GPU.

For argument-buffer resources, explicitly declare their use/residency with the applicable encoder resource or heap APIs. Residency and synchronization solve different problems: a resident resource can still be accessed in the wrong order. Keep indirect resources alive for their complete GPU use.

## Producer/consumer ordering with the classic API

For direct resources with hazard tracking on an `MTLCommandQueue`, preserve the framework's automatic ordering. Untracked resources, heap aliasing, and indirect access require checking explicit dependencies. Do not assume that command encoding order is sufficient for all resource access patterns.

Use a supported compute memory barrier for dependent commands within a compute pass, fences for GPU pass dependencies, and events where queue or CPU coordination needs them. Match the synchronized stages to the actual reader and writer; a compute-to-fragment dependency need not block unrelated vertex work. Do not copy newer queue-barrier API calls into a classic encoder.

For a supported classic cross-queue dependency on one device, signal an `MTLEvent` with `MTLCommandBuffer.encodeSignalEvent(_:value:)` after the producing work and wait for that value with `encodeWaitForEvent(_:value:)` before the consuming work. End active encoders before encoding these command-buffer operations. Use increasing event values when reusing an event; CPU coordination uses supported shared-event APIs instead.

An unsatisfied wait in a submitted command buffer needs a reachable signal at an equal-or-greater value. Encoding a signal does not submit it: commit the producing command buffer and ensure its work can reach the signal without a circular dependency. Finish producer preparation and decide whether both operations will run before submitting the consumer's wait. If a skipped frame, setup failure, or early return prevents producer submission, omit the dependent consumer work and its wait before consumer submission. An already-satisfied value proceeds immediately.

Committed consumer work cannot be withdrawn. Consumer-first submission requires a guaranteed reachable signal or a predesigned cancellation protocol in which the consumer safely handles missing producer data. Signaling the value without producing data releases subsequent consumer passes; marking their output invalid afterward does not prevent stale or invalid input use. A producer failure that prevents its signal requires the application's error recovery to handle the dependency rather than assuming the wait will clear.

Order writes before reads and before reusing or aliasing their memory. Consider read-after-write, write-after-read, and write-after-write conflicts. Keep CPU modifications outside the resource's in-flight GPU ownership interval, even with shared storage. Resource synchronization is not a substitute for fixing two threads that write the same output element in a kernel.

## Optional Metal Performance Shaders

Consider MPS for a standard blur, convolution, reduction, or matrix operation when its supported formats, dimensions, boundary behavior, and precision match the requested result. Retain a custom kernel when it enables the intended appearance, fused work, or a different data contract. There is no universal rule that MPS is fastest or that matrix multiplication must use it.

Inspect the chosen MPS operation's current documentation and availability. Check source/destination requirements, offsets/strides, and in-place fallback behavior before encoding. Reuse operation objects and compatible resources when practical, encode into the existing command schedule, and measure the complete workflow including conversions and extra copies.

## Sources

- [Apple: Resource fundamentals](https://developer.apple.com/documentation/metal/resource-fundamentals) — storage/access permissions and the limits of hazard tracking for indirect resources.
- [Apple: Choosing a resource storage mode for Apple GPUs](https://developer.apple.com/documentation/metal/choosing-a-resource-storage-mode-for-apple-gpus) and [managed resource synchronization](https://developer.apple.com/documentation/metal/synchronizing-a-managed-resource-in-macos) — select and synchronize storage for the actual GPU architecture.
- [Apple: MTLHazardTrackingMode](https://developer.apple.com/documentation/metal/mtlhazardtrackingmode), [memoryBarrier(scope:)](https://developer.apple.com/documentation/metal/mtlcomputecommandencoder/memorybarrier(scope:)), and [MTLFence](https://developer.apple.com/documentation/metal/mtlfence) — automatic tracking on classic queues, compute intrapass barriers, and pass dependencies. Use the classic encoder methods rather than Metal 4 stage/submission examples.
- [Apple: About synchronization events](https://developer.apple.com/documentation/metal/about-synchronization-events) and [Synchronizing events within a single device](https://developer.apple.com/documentation/metal/synchronizing-events-within-a-single-device) — classic command-buffer signal/wait dependencies across queues on one device.
- [Apple: encodeWaitForEvent(_:value:)](https://developer.apple.com/documentation/metal/mtlcommandbuffer/encodewaitforevent(_:value:)) — a wait pauses subsequent passes until the event reaches an equal-or-greater value.
- [Apple: Metal Performance Shaders](https://developer.apple.com/documentation/metalperformanceshaders) — verify the specific library operation's contract rather than assuming interchangeability.

Sources reviewed 2026-10-13.
