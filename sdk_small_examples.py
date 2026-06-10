"""Tiny SDK examples that are easier to study separately from the running app."""

from opentelemetry import propagate
from opentelemetry.sdk.metrics import Counter
from opentelemetry.sdk.metrics.export import AggregationTemporality
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter


def propagation_example(carrier: dict[str, str]) -> None:
    # EXTRACT: read trace context from incoming HTTP/message headers.
    incoming_context = propagate.extract(carrier)

    # INJECT: write trace context into outgoing HTTP/message headers.
    propagate.inject(carrier, context=incoming_context)


def cumulative_temporality_example() -> OTLPMetricExporter:
    # TEMPORALITY: CUMULATIVE means "value since process start".
    # DELTA would mean "value since the previous export".
    return OTLPMetricExporter(
        preferred_temporality={Counter: AggregationTemporality.CUMULATIVE}
    )
