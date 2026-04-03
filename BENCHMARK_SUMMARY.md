# Benchmark Summary

Status: April 3, 2026

Source of truth:

- project overview: [README.md](/home/tishka17/src/dixp/README.md)
- raw snapshot: [benchmarks/latest-results.json](/home/tishka17/src/dixp/benchmarks/latest-results.json)
- rendered report: [benchmarks/latest-results.md](/home/tishka17/src/dixp/benchmarks/latest-results.md)
- harness: [benchmarks/run_di_benchmarks.py](/home/tishka17/src/dixp/benchmarks/run_di_benchmarks.py)
- renderer: [benchmarks/render_results_md.py](/home/tishka17/src/dixp/benchmarks/render_results_md.py)
- benchmark workflow: [benchmarks/README.md](/home/tishka17/src/dixp/benchmarks/README.md)
- longer analysis: [COMPETITIVE_COMPARISON.md](/home/tishka17/src/dixp/COMPETITIVE_COMPARISON.md)

Command used:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py --repeat 5 --iterations 50 --format json > benchmarks/latest-results.json
```

Rendered markdown report:

```bash
python3 benchmarks/render_results_md.py benchmarks/latest-results.json > benchmarks/latest-results.md
```

Compared libraries:

- `dixp`
- `dependency-injector 4.49.0`
- `injector 0.24.0`
- `lagom 2.7.7`
- `punq 0.7.0`
- `dishka 1.9.1`
- `wireup 2.9.0`

## Short Take

`dixp` is not the raw performance leader in the current benchmark snapshot.

This snapshot was regenerated after aligning the competitor adapters with the current documented APIs for `injector`, `lagom`, `punq`, `dishka`, and `wireup`, including native collection APIs where those libraries expose them, and now also includes composite `start_ready` and `request_cycle` workloads.

Its strongest story remains:

- architecture validation
- graph diagnostics
- bundle contracts and policy enforcement
- explicit runtime API

Its weakest story right now is raw runtime throughput, including the added composite startup and request benchmarks.

## Where `dixp` Lands

Out of 7 libraries:

- `freeze`: 7th
- `start`: 7th
- `start_ready`: 7th
- `validate`: 6th
- `singleton_get`: 7th
- `scoped_get`: 7th
- `collection_all`: 6th
- `call`: 6th
- `request_cycle`: 6th

That means `dixp` currently sits in the lower half on every measured runtime-speed metric, including the added composite startup and request-cycle scenarios. Its best relative results are now `validate`, `collection_all`, `call`, and `request_cycle`.

## Metric Winners

- `freeze`: `punq`
- `start`: `lagom`
- `start_ready`: `lagom`
- `validate`: `lagom`
- `singleton_get`: `dependency-injector`
- `scoped_get`: `lagom`
- `collection_all`: `wireup`
- `call`: `wireup`
- `request_cycle`: `lagom`

## Where `dixp` Still Wins

Against `punq`:

- `validate`
- `collection_all`
- `call`
- `request_cycle`

`dixp` does not beat `dependency-injector`, `injector`, `lagom`, `dishka`, or `wireup` on any measured metric in this snapshot.

## Median Results

| library | freeze | start | start_ready | validate | singleton_get | scoped_get | collection_all | call | request_cycle |
|---|---|---|---|---|---|---|---|---|---|
| dixp | 37.767 ms | 38.106 ms | 37.895 ms | 39.8 us | 3.6 us | 19.3 us | 14.1 us | 43.7 us | 51.7 us |
| dependency-injector | 57.1 us | 198.8 us | 221.4 us | 22.5 us | 64.2 ns | 568.1 ns | 958.8 ns | 3.2 us | 2.6 us |
| injector | 116.2 us | 55.1 us | 171.1 us | 27.8 us | 1.4 us | 1.3 us | 2.9 us | 40.1 us | 24.5 us |
| lagom | 886.6 ns | 17.4 us | 19.0 us | 1.4 us | 113.0 ns | 426.8 ns | 233.3 ns | 5.7 us | 1.5 us |
| punq | 790.1 ns | 37.2 us | 245.9 us | 162.3 us | 537.4 ns | 13.4 us | 100.8 us | 167.4 us | 170.1 us |
| dishka | 443.1 us | 168.5 us | 1.171 ms | 23.7 us | 284.2 ns | 2.0 us | 486.0 ns | 3.6 us | 3.1 us |
| wireup | 18.9 us | 1.205 ms | 1.239 ms | 2.4 us | 85.6 ns | 1.1 us | 190.4 ns | 1.7 us | 1.8 us |

## Safe Conclusion

The benchmark supports this claim:

- `dixp` is differentiated by safety, diagnostics, and architecture controls, not by raw throughput speed.

The benchmark does not support these claims:

- `dixp` is the fastest Python DI library
- `dixp` beats `dependency-injector` on throughput
- `dixp` beats `injector` on throughput
- `dixp` beats `lagom` on throughput
- `dixp` beats `dishka` on throughput
- `dixp` beats `wireup` on throughput

## Next Optimization Targets

If the goal is to improve `dixp` benchmark standing, the biggest pressure points are:

1. `freeze`
2. `start`
3. `start_ready`
4. `request_cycle`

The added realistic workloads are not rescuing the picture yet: `start_ready` is last, and `request_cycle` still only beats `punq`.
