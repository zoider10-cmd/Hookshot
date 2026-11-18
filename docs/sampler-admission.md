# Sampler cache admission, reuse and retry

NVN samplers pass through an ID/generation table, a thread-local parameter/handle
cache and a global book that owns every sampler made. Ignoring `vkCreateSampler`
failure could admit an undefined error-output handle, or retain null in those
caches indefinitely. Checking only the factory result would still let the outer
ID table retain null.

Only successful handles now enter the owning or acceleration caches. The ID
table does not mark a failed creation resolved for that registration generation.
Failure of one key is bounded to one attempt per present; later presents can
retry the same ID, including on a fresh thread. Successful hits and unrelated
keys remain usable. Failure keys are cleared at a later present. If failure
tracking itself cannot allocate, new keys wait until the next present, while
already-owned successful handles still work.

## Reuse and the driver's sampler limit

A driver makes at most `maxSamplerAllocationCount` samplers (NVIDIA about 4000,
NVK 4096). Past it `vkCreateSampler` fails, and a draw needing a new sampler would
be refused (below) for the rest of the run. Keys multiply samplers: each
registration change, anisotropy row and upscale LOD bias makes a new set. So the
factory does not let the limit decide:

- **Reuse.** The book keeps one sampler for each distinct create info, less what
  no sample reaches: the anisotropy of a sampler without anisotropic filtering, and
  the border colour of one no address mode clamps to its border. A key whose info
  matches another key's gets that sampler. A sampler that does not compare keeps
  its comparison in the info, because a driver may compare anyway.
- **Retirement.** The book's room is the limit less a reserve of 64 (a quarter of
  a smaller limit) for the renderer's other samplers and an upscaler SDK's. From
  three quarters of the room, each new sampler first retires the least recently
  resolved one. A retired sampler leaves every table at once: the book's, each
  thread's handle cache (a retirement generation), and the ID tables and the
  descriptors kept by reuse (`samplers_changed`). It is destroyed only once the
  GPU timeline reaches the `vk_retirement_value()` taken at its retirement: a
  signal after every recording made so far, so no submission in flight loses a
  sampler it draws with.
- **Recency.** The thread tables hide uses from the book. Once the book holds half
  of the retiring point, their entries last one present, so every sampler in use
  resolves through the book once a present and keeps its place.

The last quarter of the room holds new samplers while retired ones still belong
to the GPU. Creation stops only when the samplers made and the retired ones the
GPU may still use fill the room. Then nothing is retired, and the key waits for a
later present like a failed creation; a log line says why. No sampler is made past
the room. If noting a retirement cannot allocate, that sampler stays made instead
of being lost. No sampler is ever replaced by another with a different filtering
policy.

## Ownership and descriptors

A newly created sampler whose book insertion throws is destroyed before
returning null. An error-output handle is never returned or destroyed. The
parameter, key and thread-local handle tables are acceleration caches: allocation
failure there does not discard registered parameters or destroy a valid owned
handle. Existing registration/version checks, the lifetimes of successful
samplers (until retired as above), filter/LOD/compare/anisotropy/border/reduction
policies and the renderer API are unchanged. Existing replay locking serializes
the book and failure tracking; no new worker or GPU wait is added.

Before either pushing descriptors or allocating/updating a descriptor set,
`bind_descriptors` rejects a combined-image-sampler array containing a failed
sampler. It leaves the pushed-state cache untouched and returns failure to
the existing draw, compute and mesh-fallback callers. A later rebuild can retry;
no replacement sampler changes the requested filtering policy. Storage images
continue to accept their unused null sampler.

## Tests

`tests/test_sampler_admission.py` executes the complete actual sampler factory,
book, ID-cache consumer and parameter policy helpers, using the public NVN
parameter layout. Vulkan, registration/environment/hash inputs, the GPU timeline
and the replay-lock boundary are modeled. Standard containers use tagged throwing
allocators to target each cache operation. The owning-cache fault is armed after
successful resource creation, independent of an STL's sentinel/bucket allocation
choices. Each of the 50 cases runs three ways (the ID table, the factory itself,
and the cache switched off), 150 in all. They cover failure/retry/cache chains,
ownership and allocation rollback, independent keys, registration changes,
threads and unchanged sampler policies. The actual complete descriptor-binding
function and fingerprint helpers run against modeled Vulkan calls too: cold and
warm failures in an array's second element, graphics/compute, pooled sets, both
pushed-state layouts, full pushes, next-present recovery and storage images.
Rejected writes must produce no allocation, update, bind or push and must
preserve the prior fingerprint.

The limit cases use a modeled driver that makes at most 80 samplers. In 300
recordings on two long-lived threads, with the GPU two recordings behind, 1,525
distinct samplers are drawn with. None is refused, each is made once, and none is
destroyed before the GPU passes the last recording that drew with it. Other cases
cover a stopped GPU filling the room and recovering at the next present, keys that
share one sampler, and allocation failure in the key table and in noting a
retirement. Run against a tree from before sampler reuse (`--source`), the limit
cases fail.

Run `python -I -B tests/run_all.py sampler_admission --strict`, or invoke the
test with `--headers <Vulkan include folder> --cxx <compiler>`; `--sanitize` is
supported on Linux. Game-free failure models do not prove native OOM/device-loss
recovery, a real driver's limit, image-quality changes, a full campaign or
performance improvements.
