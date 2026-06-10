import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource, ResourceDetector
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode

OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-agent:4317")
HEAD_SAMPLE_RATIO = float(os.getenv("OTEL_HEAD_SAMPLE_RATIO", "1.0"))


# RESOURCE DETECTOR: discovers metadata about the entity producing telemetry.
class AppResourceDetector(ResourceDetector):
    def detect(self) -> Resource:
        return Resource.create({"service.name": "checkout-api", "team": "payments"})


resource = AppResourceDetector().detect()  # RESOURCE: attached to every signal.

# ----- TRACE PIPELINE: Exporter -> SpanProcessor -> TracerProvider -----

# TRACE EXPORTER: knows WHERE to send ended spans.
span_exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)

# SPAN PROCESSOR: knows HOW to process ended spans before export.
span_processor = BatchSpanProcessor(span_exporter)

# HEAD SAMPLING: runs inside the application SDK, before spans are exported.
# 0.10 = keep 10% of new root traces. ParentBased follows the parent's decision.
tracer_provider = TracerProvider(
    resource=resource,
    sampler=ParentBased(root=TraceIdRatioBased(HEAD_SAMPLE_RATIO)),
)
tracer_provider.add_span_processor(span_processor)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("checkout")

# ----- METRIC PIPELINE: Exporter -> MetricReader -> MeterProvider -----

# AGGREGATION: turn duration measurements into these histogram buckets.
duration_view = View(
    instrument_name="checkout.duration",
    aggregation=ExplicitBucketHistogramAggregation([10, 50, 100, 250, 500]),
)

# METRIC EXPORTER: knows WHERE to send collected metric data.
metric_exporter = OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True)

# METRIC READER: every 5 seconds collects aggregated metrics and exports them.
metric_reader = PeriodicExportingMetricReader(
    metric_exporter,
    export_interval_millis=5000,
)

# METER PROVIDER: owns the metric readers and views; creates Meter objects.
meter_provider = MeterProvider(
    resource=resource,
    metric_readers=[metric_reader],
    views=[duration_view],
)
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("checkout")

# METRIC INSTRUMENTS: application code records measurements through them.
checkout_counter = meter.create_counter("checkout.requests")
checkout_duration = meter.create_histogram("checkout.duration", unit="ms")

# ----- LOG PIPELINE: Exporter -> LogRecordProcessor -> LoggerProvider -----

# LOG EXPORTER: knows WHERE to send completed log records.
log_exporter = OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True)

# LOG RECORD PROCESSOR: batches log records before giving them to the exporter.
log_processor = BatchLogRecordProcessor(log_exporter)

# LOGGER PROVIDER: owns log record processors; root SDK configuration for logs.
log_provider = LoggerProvider(resource=resource)
log_provider.add_log_record_processor(log_processor)
logger = logging.getLogger("checkout")
logger.addHandler(LoggingHandler(logger_provider=log_provider))
logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    tracer_provider.shutdown()
    meter_provider.shutdown()
    log_provider.shutdown()


app = FastAPI(title="Small OpenTelemetry Examples", lifespan=lifespan)

# AUTO-INSTRUMENTATION: creates SERVER spans and extracts incoming trace context.
FastAPIInstrumentor.instrument_app(app)


@app.get("/checkout")
def checkout(
    payment_method: str = Query("card", pattern="^(card|cash)$"),
    fail: bool = False,
):
    with tracer.start_as_current_span("charge-payment") as span:
        # SPAN ATTRIBUTE: describes this one operation.
        span.set_attribute("payment.method", payment_method)
        span.set_attribute("user.email", "student@example.com")  # Gateway deletes it.

        # SPAN EVENT: something happened at a point in time inside the span.
        span.add_event("payment.started")

        # LOW-CARDINALITY metric attribute: only card/cash, not user_id/email.
        checkout_counter.add(1, {"payment.method": payment_method})
        checkout_duration.record(42, {"payment.method": payment_method})

        if fail:
            # ERROR STATUS: tail sampler in the gateway keeps every error trace.
            span.set_status(Status(StatusCode.ERROR, "payment rejected"))
            span.add_event("payment.rejected")
            logger.error("Payment rejected")
            raise HTTPException(status_code=500, detail="payment rejected")

        logger.info("Payment completed")
        return {"status": "paid", "payment_method": payment_method}


@app.get("/health")
def health():
    # Gateway filter processor drops this noisy health-check trace.
    return {"status": "ok"}
