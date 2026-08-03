import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricResult:
    check_id: str
    worker_id: str
    timestamp: str
    journey_name: str
    latency_ms: float
    status: str
    status_code: int
    region: str
    tags: Dict[str, str] = field(default_factory=dict)
    steps_completed: int = 0
    steps_total: int = 0
    error: Optional[str] = None


class MockDataSource:
    """Reads mock journey data from an in-memory store or JSON source."""

    def __init__(self, mock_data: Optional[List[Dict[str, Any]]] = None):
        self._data = mock_data or self._default_mock_data()

    @staticmethod
    def _default_mock_data() -> List[Dict[str, Any]]:
        return [
            {
                "journey_name": "homepage_load",
                "region": "us-east-1",
                "steps": [
                    {"action": "navigate", "url": "https://example.com/", "expect_status": 200},
                    {"action": "wait", "selector": "#hero", "timeout_ms": 3000},
                ],
                "tags": {"team": "platform", "priority": "high"},
            },
            {
                "journey_name": "login_flow",
                "region": "eu-west-1",
                "steps": [
                    {"action": "navigate", "url": "https://example.com/login", "expect_status": 200},
                    {"action": "fill", "selector": "#email", "value": "user@test.com"},
                    {"action": "fill", "selector": "#password", "value": "secret"},
                    {"action": "click", "selector": "#submit", "expect_status": 302},
                ],
                "tags": {"team": "auth", "priority": "critical"},
            },
            {
                "journey_name": "api_health",
                "region": "ap-southeast-1",
                "steps": [
                    {"action": "request", "url": "https://api.example.com/health", "method": "GET", "expect_status": 200},
                ],
                "tags": {"team": "backend", "priority": "medium"},
            },
        ]

    def read(self) -> List[Dict[str, Any]]:
        logger.info("MockDataSource: read %d journeys", len(self._data))
        return list(self._data)


class TransformationPipeline:
    """Applies a chain of transformations to raw journey data."""

    def __init__(self, transformers: Optional[List[Callable]] = None):
        self._transformers = transformers or [
            self._enrich_metadata,
            self._compute_step_stats,
            self._normalize_timestamps,
        ]

    @staticmethod
    def _enrich_metadata(journey: Dict[str, Any]) -> Dict[str, Any]:
        journey.setdefault("check_id", str(uuid.uuid4()))
        journey.setdefault("worker_id", f"worker-{uuid.uuid4().hex[:8]}")
        journey.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        return journey

    @staticmethod
    def _compute_step_stats(journey: Dict[str, Any]) -> Dict[str, Any]:
        steps = journey.get("steps", [])
        journey["steps_total"] = len(steps)
        journey["steps_completed"] = journey.get("steps_completed", len(steps))
        return journey

    @staticmethod
    def _normalize_timestamps(journey: Dict[str, Any]) -> Dict[str, Any]:
        ts = journey.get("created_at", datetime.now(timezone.utc).isoformat())
        if not ts.endswith("+00:00") and not ts.endswith("Z"):
            ts += "+00:00"
        journey["created_at"] = ts
        return journey

    def apply(self, journeys: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for journey in journeys:
            transformed = journey
            for transformer in self._transformers:
                transformed = transformer(transformed)
            result.append(transformed)
        logger.info("TransformationPipeline: processed %d journeys", len(result))
        return result


class SimulationEngine:
    """Simulates execution of journey steps and produces MetricResult objects."""

    LATENCY_BASE_MS = 50.0
    LATENCY_PER_STEP_MS = 120.0

    def execute(self, journeys: List[Dict[str, Any]]) -> List[MetricResult]:
        results = []
        for journey in journeys:
            start = time.monotonic()
            steps_total = journey.get("steps_total", 0)
            steps_completed = steps_total
            error = None
            status = "ok"
            status_code = 200

            for step in journey.get("steps", []):
                expected = step.get("expect_status", 200)
                if expected >= 400:
                    steps_completed = steps_total - 1
                    status = "error"
                    status_code = expected
                    error = f"Step failed: expected {expected}"
                    break

            elapsed_ms = (time.monotonic() - start) * 1000
            latency = round(self.LATENCY_BASE_MS + self.LATENCY_PER_STEP_MS * steps_completed + elapsed_ms, 2)

            result = MetricResult(
                check_id=journey.get("check_id", str(uuid.uuid4())),
                worker_id=journey.get("worker_id", "unknown"),
                timestamp=journey.get("created_at", datetime.now(timezone.utc).isoformat()),
                journey_name=journey.get("journey_name", "unknown"),
                latency_ms=latency,
                status=status,
                status_code=status_code,
                region=journey.get("region", "unknown"),
                tags=journey.get("tags", {}),
                steps_completed=steps_completed,
                steps_total=steps_total,
                error=error,
            )
            results.append(result)
        logger.info("SimulationEngine: executed %d journeys", len(results))
        return results


class ConsoleSink:
    """Outputs MetricResult objects to stdout as JSON lines."""

    def __init__(self, output_path: Optional[str] = None):
        self._output_path = output_path

    def write(self, results: List[MetricResult]) -> int:
        lines = []
        for result in results:
            line = json.dumps(asdict(result), sort_keys=True)
            lines.append(line)
            print(line)

        if self._output_path:
            with open(self._output_path, "a") as f:
                for line in lines:
                    f.write(line + "\n")

        logger.info("ConsoleSink: wrote %d metric results", len(results))
        return len(results)


class CoreProcessingEngine:
    """Orchestrates the full pipeline: read → transform → execute → sink."""

    def __init__(
        self,
        source: Optional[MockDataSource] = None,
        pipeline: Optional[TransformationPipeline] = None,
        engine: Optional[SimulationEngine] = None,
        sink: Optional[ConsoleSink] = None,
    ):
        self.source = source or MockDataSource()
        self.pipeline = pipeline or TransformationPipeline()
        self.engine = engine or SimulationEngine()
        self.sink = sink or ConsoleSink()

    def run(self) -> int:
        logger.info("CoreProcessingEngine: starting run")
        raw = self.source.read()
        transformed = self.pipeline.apply(raw)
        results = self.engine.execute(transformed)
        count = self.sink.write(results)
        logger.info("CoreProcessingEngine: completed, %d results written", count)
        return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    engine = CoreProcessingEngine()
    engine.run()