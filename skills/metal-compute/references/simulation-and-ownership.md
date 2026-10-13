# Simulation and ownership

## Feedback and neighborhood updates

For reaction-diffusion, cellular automata, flocking, and other neighborhood updates, define a time-step contract: each thread reads the same previous state and owns one next-state element. Read buffer/texture A, write B, order the producer and consumer, then swap the roles. Distinct texture views of the same allocation are not independent storage.

In-place updates are appropriate when threads exclusively read and write their own element and the math does not require the old state from another element. A particle integrating independent acceleration can satisfy this. A particle inspecting neighbors' positions while those neighbors update them cannot.

Specify boundary behavior explicitly: clamp, wrap, fixed value, or a separately modeled boundary. For integer texture reads, implement this policy before the read; a sampler's addressing mode does not apply. For filters that use a threadgroup tile, initialize the full tile and halo, including inactive edge lanes, before the barrier. Do not return out-of-range lanes before a barrier that their group still executes.

Use elapsed time in documented units. Independent velocity-first integration is semi-implicit Euler; call it Verlet only if the algorithm actually maintains the state and equations required for Verlet. A constant per-frame drag factor changes behavior with frame rate; express a decay rate or retain the project's chosen fixed-step policy. Bound catch-up substeps according to the application's simulation budget, and avoid silently changing this policy during shader tuning.

## Capacity and bounded appends

Distinguish allocated capacity, active element count, and produced count. Check all dispatches and downstream consumers against the capacity. A newly allocated counter is not automatically initialized. Reset append counters in ordered work before the producers start.

An append kernel can reserve a unique slot using an atomic counter, then write only if the slot is below capacity. This yields an **attempted** count, possibly greater than capacity; consumers must use `min(attemptedCount, capacity)`. Define whether overflow is reported, dropped, or retried. Bound the number of increments so the counter cannot wrap. A bounded CAS reservation can instead maintain an accepted count, at the cost of contention and a more complex contract.

Each accepted slot needs exactly one producer. Consumer work must wait until payload writes finish, rather than polling the relaxed counter inside the same dispatch. A threadgroup barrier cannot provide a global rendezvous; spin-waiting on work in another group can prevent forward progress. Use separate ordered dispatches for compacting, sorting, or consuming the generated list.

Spatial hashes need a collision policy and capacity for every bucket or chain. Writing one particle index per hash value overwrites colliding particles; a hash function is not a neighbor-list data structure. Test concentrated particles that collide into the same bucket, not just uniform random distributions.

## Frames in flight

Ping-pong storage separates consecutive simulation states, but does not by itself protect a buffer still read by an earlier render frame. Trace every read/write use, including rendering, CPU inspection, and upload. Reuse storage only after those uses finish; add an appropriately sized resource ring or ordering where the existing frame schedule needs it.

For CPU readback, wait for the producing GPU work through the app's completion/event mechanism and perform any storage-mode coherency operation. A one-off blocking wait may be useful for a diagnostic test; avoid turning every simulation step into a CPU/GPU round trip.

## Validation scenarios

- Compare a small deterministic run against the CPU algorithm, including boundaries and multiple time steps.
- Exercise zero active elements, full capacity, append overflow, and repeated counter resets.
- Run odd texture sizes and tails smaller than one full group; inspect initialized halo values.
- Check two or more frames in flight and paused/resized rendering for stale state or premature reuse.

## Sources

- [Apple: MSL specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf) — execution scopes, memory flags, atomic operations, and texture reads, filtered by the selected pre-4 language version.
- [Apple: Resource synchronization](https://developer.apple.com/documentation/metal/resource-synchronization) — choose command-level ordering for producer/consumer dependencies; use its pre-Metal-4 sections.
- [Apple: Synchronizing events between a GPU and the CPU](https://developer.apple.com/documentation/metal/synchronizing-events-between-a-gpu-and-the-cpu) — asynchronous CPU/GPU coordination with shared events when supported.
