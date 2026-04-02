# Competitive Comparison: `dixp` vs Other Python DI Libraries

Status: April 3, 2026

This document is intentionally strict about claims.

- It lists verified competitor positioning from official project pages.
- It lists locally verifiable `dixp` capabilities from this repository.
- It does not invent head-to-head performance numbers that were not measured.

As of April 3, 2026, this repository now includes:

- installed competitor libraries in a local `.venv`
- a reproducible benchmark harness in `benchmarks/run_di_benchmarks.py`
- benchmark workflow notes in `benchmarks/README.md`
- a local snapshot in `benchmarks/latest-results.json`
- a rendered benchmark report in `benchmarks/latest-results.md`
- a short benchmark summary in `BENCHMARK_SUMMARY.md`

That still does not make the numbers universal truth. The benchmark is:

- local to one machine and one Python environment
- adapter-based, not official vendor-maintained benchmark code
- workload-equivalent, not feature-equivalent, across libraries
- strongest as a reality check, not as absolute proof of superiority

## Compared Libraries

The comparison below uses at least six well-known Python DI libraries:

- `dependency-injector`: <https://pypi.org/project/dependency-injector/>
- `injector`: <https://pypi.org/project/injector/>
- `lagom`: <https://pypi.org/project/lagom/>
- `punq`: <https://pypi.org/project/punq/>
- `dishka`: <https://pypi.org/project/dishka/>
- `wireup`: <https://pypi.org/project/wireup/>

## Benchmark Snapshot

Command used:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py --repeat 5 --iterations 50 --format json > benchmarks/latest-results.json
```

Rendered report:

```bash
python3 benchmarks/render_results_md.py benchmarks/latest-results.json > benchmarks/latest-results.md
```

Versions used in the local `.venv`:

- `dependency-injector 4.49.0`
- `injector 0.24.0`
- `lagom 2.7.7`
- `punq 0.7.0`
- `dishka 1.9.1`
- `wireup 2.9.0`

Measured values below are median latency per operation. Lower is better.

| library | freeze | start | validate | singleton_get | scoped_get | collection_all | call |
|---|---|---|---|---|---|---|---|
| dixp | 33.078 ms | 32.943 ms | 40.4 us | 3.6 us | 19.0 us | 14.1 us | 43.2 us |
| dependency-injector | 55.3 us | 196.8 us | 22.1 us | 61.0 ns | 516.4 ns | 923.8 ns | 3.0 us |
| injector | 121.7 us | 205.0 us | 53.7 us | 1.3 us | 24.8 us | 2.7 us | 111.6 us |
| lagom | 648.1 ns | 22.3 us | 1.6 us | 116.2 ns | 436.7 ns | 480.5 ns | 53.0 us |
| punq | 139.9 ns | 35.4 us | 165.6 us | 711.6 ns | 13.2 us | 95.8 us | 159.8 us |
| dishka | 233.0 us | 118.6 us | 13.6 us | 302.8 ns | 2.0 us | 310.9 ns | 3.1 us |
| wireup | 76.4 us | 1.318 ms | 2.9 us | 84.7 ns | 2.0 us | 90.2 ns | 2.7 us |

The benchmark snapshot does not show `dixp` as the raw throughput leader. It does show that:

- `dixp` wins against `injector` on `validate` and `call`
- `dixp` wins against `punq` on `validate`, `collection_all`, and `call`
- `dixp` loses clearly to `dependency-injector`, `dishka`, and `wireup` on most measured hot-path metrics
- `lagom` is faster on most microbenchmarks here, while `dixp` is slightly faster on `call`

## What `dixp` Can Honestly Claim Today

Compared with most Python DI containers, `dixp` is unusually strong in these areas:

1. Architecture guardrails, not just object construction.
   `bundle(...)`, exports, private services, `requires(...)`, layer rules, tag rules, incoming/outgoing bundle policies, bundle cycle detection, and graph drift reporting are first-class features.

2. Explainability.
   `doctor()`, `explain()`, bundle graph export, Mermaid output, JSON output, and diffable graph baselines are built in.

3. Typed composition flow.
   `App`, `@service`, `singleton(...)`, `scoped(...)`, `value(...)`, `env(...)`, and named keys keep the public API small and type-oriented.

4. Diagnostics as structured data.
   Errors now carry `code` and `details`, which makes `dixp` easier to integrate with CI, custom reporting, and tests.

5. Explicit runtime ergonomics.
   `get()`, `all()`, `call()`, `warmup()`, `activate()`, `override()`, scopes, sync/async APIs, and validation are exposed as explicit tasks instead of hidden magic.

## Where `dixp` Should Be Careful

These claims should not be made yet:

- "Fastest Python DI container"
- "Faster than `dependency-injector`"
- "Faster than `dishka`"
- "Faster than `wireup`"
- "Best ecosystem integration"

This is no longer just caution in the abstract. The local benchmark snapshot in this repository does not support those claims. `dependency-injector`, `dishka`, and `wireup` are materially faster than `dixp` in most of the measured microbenchmarks, and `lagom` is also faster on most of them.

## Head-to-Head Positioning

### 1. `dependency-injector`

Official positioning:
- providers
- overriding
- configuration
- resources

Where `dixp` is better:
- stronger architecture-level controls
- built-in bundle graph reporting and drift detection
- more opinionated, smaller public composition surface
- structured error codes and human-readable graph diagnostics

Where `dependency-injector` is stronger:
- broader ecosystem maturity
- more established provider model
- dramatically stronger raw throughput in this local benchmark snapshot

Speed claim:
- The current local benchmark strongly favors `dependency-injector` on every measured performance metric.

Verdict:
- `dixp` is better for architecture-first teams.
- `dependency-injector` remains much stronger for teams optimizing for raw throughput and mature provider ecosystems.

### 2. `injector`

Official positioning:
- Guice-inspired framework
- modules
- automatic transitive dependency provisioning

Where `dixp` is better:
- better graph diagnostics
- better startup validation story
- better sync/async API split
- better architecture boundary enforcement
- better reporting for CI and review workflows

Where `injector` is stronger:
- familiar mental model for teams that already like Guice-style modules

Speed claim:
- In the current local benchmark, `dixp` is faster on `validate` and `call`, while `injector` is faster on `freeze`, `start`, `singleton_get`, `scoped_get`, and `collection_all`.

Verdict:
- `dixp` is materially stronger for teams that want operational diagnostics and architecture rules, not just injection.

### 3. `lagom`

Official positioning:
- "just enough" dependency injection
- type-based auto wiring
- strong type focus
- async support

Where `dixp` is better:
- stronger validation and explainability
- stronger architecture constraints
- built-in config loading via typed `env(...)`
- richer runtime report surface

Where `lagom` is stronger:
- lighter "minimum ceremony" positioning
- may feel more natural for teams that want auto-wiring with minimal container surface

Speed claim:
- In the current local benchmark, `lagom` is faster on every measured metric except `call`, where `dixp` has a modest edge.

Verdict:
- `dixp` is stronger when governance and diagnostics matter more than minimum ceremony.

### 4. `punq`

Official positioning:
- small and simple
- no global state
- no decorators
- easy to understand

Where `dixp` is better:
- scopes
- bundle boundaries
- graph validation
- explainability
- async-aware runtime APIs
- open generic support
- structured diagnostics

Where `punq` is stronger:
- much smaller mental model
- lower adoption cost for tiny projects

Speed claim:
- In the current local benchmark, `punq` is faster on `freeze`, `start`, `singleton_get`, and `scoped_get`, while `dixp` is faster on `validate`, `collection_all`, and `call`.

Verdict:
- `dixp` is materially stronger for medium and large codebases.
- `punq` stays attractive for intentionally tiny setups.

### 5. `dishka`

Official positioning:
- scope-focused DI framework
- agreeable API
- strong scope story

Where `dixp` is better:
- architecture contracts
- bundle graph export and drift detection
- `doctor()` / `explain()` style diagnostics
- structured error reporting

Where `dishka` is stronger:
- scope model is a central design focus
- stronger ecosystem story for framework integrations around scoped execution
- much stronger raw performance in this local benchmark snapshot

Speed claim:
- The current local benchmark favors `dishka` across every measured performance metric.

Verdict:
- this is the closest conceptual competitor for teams that care about runtime correctness.
- `dixp` is stronger on architecture governance; `dishka` is stronger where scopes and integrations are the main concern.

### 6. `wireup`

Official positioning:
- type-driven DI
- fail-fast startup
- framework integrations
- explicit performance positioning

Where `dixp` is better:
- bundle contracts and bundle policy enforcement
- graph explainability
- drift detection and Mermaid/JSON reporting
- smaller conceptual distance between application architecture and container composition

Where `wireup` is stronger:
- stronger public performance story
- broader framework integration story
- clearer "battle-tested" positioning
- much stronger raw performance in this local benchmark snapshot

Speed claim:
- The current local benchmark favors `wireup` across every measured performance metric.

Verdict:
- `dixp` is better for architecture-aware composition and diagnostics.
- `wireup` currently has the stronger explicit performance narrative.

## Practical Summary

If the buyer cares most about:

- architecture safety: `dixp` is one of the strongest options in this set
- human diagnostics: `dixp` is stronger than most of the field
- typed app composition with a small public API: `dixp` is strong
- raw performance: `dependency-injector`, `dishka`, `wireup`, and often `lagom` are stronger in this local snapshot
- scope-centered framework integration: `dishka` is a serious competitor
- minimalism: `punq` and `lagom` remain attractive

Short version:

- `dixp` is clearly better than `injector` and `punq` for architecture-first teams.
- `dixp` is usually better than `lagom` when explainability and policy enforcement matter.
- `dixp` competes on safety, diagnostics, and architecture controls, not on raw microbenchmark speed.
- `dixp` should not claim it is faster than `dependency-injector`, `dishka`, or `wireup` under the current benchmark snapshot.

## What "Faster" Should Mean for `dixp`

The repository now includes a reproducible local harness for this work:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py
```

The current snapshot is useful, but it is still only a starting point. A stronger benchmark story should still measure at least:

1. Cold graph compile / freeze time.
2. `start(validate=True)` time on a dense graph.
3. Hot singleton resolve throughput.
4. Hot scoped resolve throughput.
5. Collection resolve throughput (`all()` / `list[T]`).
6. `call()` / `acall()` injection throughput.
7. Failure-path quality:
   missing dependency, circular dependency, lifetime mismatch, bundle policy violation.

The current snapshot already suggests that `dixp` is unlikely to win every microbenchmark. Its strongest story is:

- better safety per line of composition
- better diagnostics per failure
- better architecture control per container

That is a valuable position, but it is different from "highest raw resolve throughput".

## Recommended Marketing Language

Safe claims:

- "`dixp` is a typed Python IoC toolkit that combines DI with architecture validation."
- "`dixp` gives teams built-in graph diagnostics, bundle contracts, and drift detection."
- "`dixp` favors explicit composition and operational clarity over magical wiring."
- "`dixp` optimizes for architecture safety and diagnostics more than raw container throughput."

Unsafe claims under the current benchmark snapshot:

- "`dixp` is the fastest Python DI container."
- "`dixp` beats `dependency-injector` on throughput."
- "`dixp` beats `dishka` on throughput."
- "`dixp` beats `wireup` on request-time injection performance."
