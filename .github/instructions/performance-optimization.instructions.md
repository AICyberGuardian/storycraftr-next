---
applyTo: '*'
description: 'The most comprehensive, practical, and engineer-authored performance optimization instructions for all languages, frameworks, and stacks. Covers frontend, backend, and database best practices with actionable guidance, scenario-based checklists, troubleshooting, and pro tips.'
---

# Performance Optimization Best Practices

## General Principles

- **Measure First, Optimize Second:** Always profile and measure before optimizing. Use benchmarks, profilers, and monitoring tools to identify real bottlenecks.
- **Optimize for the Common Case:** Focus on optimizing code paths that are most frequently executed.
- **Avoid Premature Optimization:** Write clear, maintainable code first; optimize only when necessary.
- **Minimize Resource Usage:** Use memory, CPU, network, and disk resources efficiently.
- **Prefer Simplicity:** Simple algorithms and data structures are often faster and easier to optimize.
- **Document Performance Assumptions:** Clearly comment on any code that is performance-critical.
- **Understand the Platform:** Know the performance characteristics of your language, framework, and runtime.
- **Automate Performance Testing:** Integrate performance tests into your CI/CD pipeline.
- **Set Performance Budgets:** Define acceptable limits for load time, memory usage, API latency, etc.

## Backend Performance

### Algorithm and Data Structure Optimization
- **Choose the Right Data Structure:** Arrays for sequential access, hash maps for fast lookups, trees for hierarchical data.
- **Efficient Algorithms:** Use binary search, quicksort, or hash-based algorithms where appropriate.
- **Avoid O(n^2) or Worse:** Profile nested loops and recursive calls.
- **Batch Processing:** Process data in batches to reduce overhead.
- **Streaming:** Use streaming APIs for large data sets to avoid loading everything into memory.

### Concurrency and Parallelism
- **Asynchronous I/O:** Use async/await, callbacks, or event loops to avoid blocking threads.
- **Thread/Worker Pools:** Use pools to manage concurrency and avoid resource exhaustion.
- **Avoid Race Conditions:** Use locks, semaphores, or atomic operations where needed.
- **Bulk Operations:** Batch network/database calls to reduce round trips.
- **Backpressure:** Implement backpressure in queues and pipelines to avoid overload.

### Caching
- **Cache Expensive Computations:** Use in-memory caches (Redis, Memcached) for hot data.
- **Cache Invalidation:** Use time-based (TTL), event-based, or manual invalidation.
- **Distributed Caching:** For multi-server setups, use distributed caches and be aware of consistency issues.
- **Cache Stampede Protection:** Use locks or request coalescing to prevent thundering herd problems.

### Database Performance

#### Query Optimization
- **Indexes:** Use indexes on columns that are frequently queried, filtered, or joined.
- **Avoid SELECT *:** Select only the columns you need.
- **Parameterized Queries:** Prevent SQL injection and improve plan caching.
- **Query Plans:** Analyze and optimize query execution plans. Use `EXPLAIN` in SQL databases.
- **Avoid N+1 Queries:** Use joins or batch queries to avoid repeated queries in loops.
- **Limit Result Sets:** Use `LIMIT`/`OFFSET` or cursors for large tables.

#### Schema Design
- **Normalization:** Normalize to reduce redundancy, but denormalize for read-heavy workloads if needed.
- **Data Types:** Use the most efficient data types and set appropriate constraints.
- **Partitioning:** Partition large tables for scalability and manageability.
- **Archiving:** Regularly archive or purge old data to keep tables small and fast.

### Logging and Monitoring
- **Minimize Logging in Hot Paths:** Excessive logging can slow down critical code.
- **Structured Logging:** Use JSON or key-value logs for easier parsing and analysis.
- **Monitor Everything:** Latency, throughput, error rates, resource usage.
- **Alerting:** Set up alerts for performance regressions and resource exhaustion.

### Language-Specific Tips

#### Python
- Use built-in data structures (`dict`, `set`, `deque`) for speed.
- Profile with `cProfile`, `line_profiler`, or `py-spy`.
- Use `multiprocessing` or `asyncio` for parallelism.
- Avoid GIL bottlenecks in CPU-bound code; use C extensions or subprocesses.
- Use `functools.lru_cache` for memoization.

#### Node.js
- Use asynchronous APIs; avoid blocking the event loop.
- Use clustering or worker threads for CPU-bound tasks.
- Limit concurrent open connections to avoid resource exhaustion.
- Use streams for large file or network data processing.
- Profile with `clinic.js`, `node --inspect`, or Chrome DevTools.

### Common Backend Pitfalls
- Synchronous/blocking I/O in web servers.
- Not using connection pooling for databases.
- Over-caching or caching sensitive/volatile data.
- Ignoring error handling in async code.
- Not monitoring or alerting on performance regressions.

## Code Review Checklist for Performance

- [ ] Are there any obvious algorithmic inefficiencies (O(n^2) or worse)?
- [ ] Are data structures appropriate for their use?
- [ ] Are there unnecessary computations or repeated work?
- [ ] Is caching used where appropriate, and is invalidation handled correctly?
- [ ] Are database queries optimized, indexed, and free of N+1 issues?
- [ ] Are large payloads paginated, streamed, or chunked?
- [ ] Are there any memory leaks or unbounded resource usage?
- [ ] Are network requests minimized, batched, and retried on failure?
- [ ] Are there any blocking operations in hot paths?
- [ ] Is logging in hot paths minimized and structured?
- [ ] Are performance-critical code paths documented and tested?
- [ ] Are there automated tests or benchmarks for performance-sensitive code?
- [ ] Are there alerts for performance regressions?

---

## References and Tools

- **Profilers:** Chrome DevTools, Py-Spy, VisualVM, dotTrace, cProfile
- **Monitoring:** Prometheus, Grafana, Datadog, New Relic, Dynatrace
- **Load Testing:** k6, Gatling, Locust, WebPageTest
- **Distributed Tracing:** OpenTelemetry, Jaeger, Zipkin
- **Benchmarking:** benchmark.js, pytest-benchmark, JMH
