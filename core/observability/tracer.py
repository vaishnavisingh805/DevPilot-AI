"""Execution Tracing and Span Latency Tracker."""

import time
from typing import Dict, List, Optional
from datetime import datetime, timezone


class TraceSpan:
    """Represents a timed execution span."""

    def __init__(self, span_name: str, parent_id: Optional[str] = None):
        self.span_id = f"span_{int(time.time() * 1000)}"
        self.span_name = span_name
        self.parent_id = parent_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.duration_seconds: float = 0.0
        self.metadata: Dict[str, str] = {}

    def finish(self, **kwargs) -> float:
        self.end_time = time.time()
        self.duration_seconds = round(self.end_time - self.start_time, 4)
        for k, v in kwargs.items():
            self.metadata[k] = str(v)
        return self.duration_seconds

    def to_dict(self) -> Dict[str, str]:
        return {
            "span_id": self.span_id,
            "span_name": self.span_name,
            "parent_id": self.parent_id or "root",
            "duration_seconds": str(self.duration_seconds),
            "metadata": str(self.metadata),
        }


class SystemTracer:
    """Distributed tracing manager tracking latency across multi-agent pipelines."""

    def __init__(self):
        self.spans: List[TraceSpan] = []

    def start_span(self, name: str, parent_id: Optional[str] = None) -> TraceSpan:
        span = TraceSpan(name, parent_id)
        self.spans.append(span)
        return span

    def get_summary(self) -> List[Dict[str, str]]:
        return [s.to_dict() for s in self.spans]

    def clear(self) -> None:
        self.spans.clear()


system_tracer = SystemTracer()

