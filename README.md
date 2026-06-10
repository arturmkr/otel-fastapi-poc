# OpenTelemetry: Examples

## The Main Sampling Answer

| | Head Sampling | Tail Sampling |
|---|---|---|
| **Where** | Application SDK | Collector |
| **When** | At the beginning of a trace | After receiving the trace |
| **Advantage** | Cheap; immediately reduces traffic | Sees the result and errors |
| **Disadvantage** | May accidentally drop an error | Costs more memory and waiting time |

In this project:

| Sampling Type | File | Configuration | Behavior |
|---|---|---|---|
| Head | `app.py` | `ParentBased(TraceIdRatioBased(...))` | Makes an early SDK-side decision |
| Tail | `otel-gateway-config.yaml` | `tail_sampling` | Keeps every error and 10% of everything else |

The app currently sends 100% of traces:

```yaml
OTEL_HEAD_SAMPLE_RATIO: "1.0"
```

This allows the Collector to see every trace and keep every error. If you set
the app value to `"0.1"`, the client drops 90% of traces in advance. The tail
sampler cannot recover an error that the application never sent.

## Files

### `app.py`: What Lives in the Application

Read it from top to bottom. Every example is labeled immediately before its
1-3 important lines:

| Code | OpenTelemetry Concept |
|---|---|
| `AppResourceDetector` | Resource Detector |
| `resource` | Resource |
| `ParentBased` + `TraceIdRatioBased` | Head Sampler |
| `OTLPSpanExporter` | Trace Exporter |
| `BatchSpanProcessor` | Span Processor |
| `View` + `ExplicitBucketHistogramAggregation` | Metric Aggregator |
| `OTLPMetricExporter` | Metric Exporter |
| `PeriodicExportingMetricReader` | Metric Reader |
| `MeterProvider` | Metric Provider |
| `OTLPLogExporter` | Log Exporter |
| `BatchLogRecordProcessor` | Log Record Processor |
| `LoggerProvider` | Log Provider |
| `create_counter` / `create_histogram` | Metric Instruments |
| `span.set_attribute` | Span Attribute |
| `span.add_event` | Span Event |
| `span.set_status(ERROR)` | Span Status |
| `FastAPIInstrumentor` | Auto-instrumentation + propagation |

`/checkout` is the only business example:

```bash
curl 'http://localhost:8000/checkout'
curl 'http://localhost:8000/checkout?fail=true'
```

The gateway keeps approximately 10% of successful traces. It always keeps error
traces.

### `sdk_small_examples.py`: Two Very Small Pairs

```python
incoming_context = propagate.extract(carrier)   # read context
propagate.inject(carrier, context=incoming_context)  # write context
```

| Temporality | Meaning |
|---|---|
| `AggregationTemporality.CUMULATIVE` | Value since process start |
| `AggregationTemporality.DELTA` | Value since the previous export |

### `otel-agent-config.yaml`: Collector Near the Application

| Component | Type | What It Does |
|---|---|---|
| `batch` | Processor | Groups telemetry into batches |
| `memory_limiter` | Processor | Protects the Collector from OOM |
| `resource/agent` | Processor | Adds a Resource attribute to every signal |
| `sending_queue` | Exporter option | Buffers data before sending |
| `retry_on_failure` | Exporter option | Retries temporary export failures |
| `file_storage` | Extension | Persists the queue on disk/WAL-like persistence |
| `otlp/gateway` | Exporter | Sends data to the central gateway |

`sending_queue` and `retry_on_failure` belong to the exporter. They are not
processors.

The agent does not make sampling decisions in this example. It only receives,
buffers, and forwards telemetry.

### `otel-gateway-config.yaml`: Central Processing

The config is intentionally readable from top to bottom in small blocks:

| Component | Type | What It Does |
|---|---|---|
| `filter/drop-health` | Processor | Removes noisy `/health` spans |
| `attributes/spans` | Processor | Removes `user.email` and adds `processed.by` |
| `resource/common` | Processor | Adds the `environment=demo` Resource attribute |
| `tail_sampling` | Processor | Keeps every error and 10% of other traces |
| `spanmetrics` | Connector | Converts traces into metrics |
| `health_check` | Extension | Exposes a health probe endpoint |
| `zpages` | Extension | Exposes live Collector diagnostics |

The connector appears in two places:

```yaml
traces:
  exporters: [debug, spanmetrics]   # connector acts as an exporter here

metrics:
  receivers: [otlp, spanmetrics]    # the same connector acts as a receiver here
```

Extensions are enabled separately from pipelines:

```yaml
service:
  extensions: [health_check, zpages]
```

| Extension | URL |
|---|---|
| Health check | <http://localhost:13133> |
| zPages | <http://localhost:55679/debug/servicez> |

## What Is Configured Where

| Question | Answer |
|---|---|
| Immediately keep a random 10% and reduce network traffic | Head sampler in the application SDK |
| Keep every error and 10% of successful traces | Tail sampling processor in the Collector |
| Process ended spans before export from the app | Span Processor in the SDK |
| Centrally remove/add span attributes | Attributes processor in the Collector |
| Add metadata to the entire service | Resource in the SDK or resource processor in the Collector |
| Connect the traces pipeline to the metrics pipeline | Connector |
| Transfer trace context between services | Propagator: `inject()` / `extract()` |
| Convert measurements into histogram buckets | Metric aggregation/View |
| Define the metric collection/export period | MetricReader |
| Connect a specific metric measurement to a trace | Exemplar |

An exemplar appears when a metric measurement is recorded inside a sampled
span. It stores an example value together with its `trace_id`/`span_id`. In
`/checkout`, `checkout_duration.record(...)` is called inside the
`charge-payment` span.

## Run And Validate

```bash
docker compose up --build -d
docker compose logs -f otel-gateway
```

Validate configs without starting the Collector:

```bash
docker compose run --rm --no-deps otel-agent validate --config=/etc/otelcol-contrib/config.yaml
docker compose run --rm --no-deps otel-gateway validate --config=/etc/otelcol-contrib/config.yaml
```

Prometheus: <http://localhost:9090>

```promql
checkout_requests_total
checkout_duration_milliseconds_bucket
traces_span_metrics_calls_total
```
