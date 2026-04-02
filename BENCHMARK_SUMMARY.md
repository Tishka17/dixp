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

Its strongest story remains:

- architecture validation
- graph diagnostics
- bundle contracts and policy enforcement
- explicit runtime API

Its weakest story right now is microbenchmark throughput.

## Where `dixp` Lands

Out of 7 libraries:

- `freeze`: 7th
- `start`: 7th
- `validate`: 5th
- `singleton_get`: 7th
- `scoped_get`: 6th
- `collection_all`: 6th
- `call`: 4th

That means `dixp` currently sits in the middle or lower half on every measured runtime-speed metric, with its best relative result in `call`.

## Metric Winners

- `freeze`: `punq`
- `start`: `lagom`
- `validate`: `lagom`
- `singleton_get`: `dependency-injector`
- `scoped_get`: `lagom`
- `collection_all`: `wireup`
- `call`: `wireup`

## Where `dixp` Still Wins

Against `injector`:

- `validate`
- `call`

Against `punq`:

- `validate`
- `collection_all`
- `call`

Against `lagom`:

- `call`

`dixp` does not beat `dependency-injector`, `dishka`, or `wireup` on any measured metric in this snapshot.

## Median Results

| library | freeze | start | validate | singleton_get | scoped_get | collection_all | call |
|---|---|---|---|---|---|---|---|
| dixp | 33.078 ms | 32.943 ms | 40.4 us | 3.6 us | 19.0 us | 14.1 us | 43.2 us |
| dependency-injector | 55.3 us | 196.8 us | 22.1 us | 61.0 ns | 516.4 ns | 923.8 ns | 3.0 us |
| injector | 121.7 us | 205.0 us | 53.7 us | 1.3 us | 24.8 us | 2.7 us | 111.6 us |
| lagom | 648.1 ns | 22.3 us | 1.6 us | 116.2 ns | 436.7 ns | 480.5 ns | 53.0 us |
| punq | 139.9 ns | 35.4 us | 165.6 us | 711.6 ns | 13.2 us | 95.8 us | 159.8 us |
| dishka | 233.0 us | 118.6 us | 13.6 us | 302.8 ns | 2.0 us | 310.9 ns | 3.1 us |
| wireup | 76.4 us | 1.318 ms | 2.9 us | 84.7 ns | 2.0 us | 90.2 ns | 2.7 us |

## Safe Conclusion

The benchmark supports this claim:

- `dixp` is differentiated by safety, diagnostics, and architecture controls, not by raw microbenchmark speed.

The benchmark does not support these claims:

- `dixp` is the fastest Python DI library
- `dixp` beats `dependency-injector` on throughput
- `dixp` beats `dishka` on throughput
- `dixp` beats `wireup` on throughput

## Next Optimization Targets

If the goal is to improve `dixp` benchmark standing, the biggest pressure points are:

1. `freeze`
2. `start`
3. `singleton_get`
4. `collection_all`

`call` is the most defensible runtime path today because it is closer to the pack and already beats `lagom`, `injector`, and `punq` in this snapshot.
