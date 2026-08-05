===
import json
import random
import time
import uuid
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from enum import Enum


class JourneyStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    FLAKY = "flaky"


class StepType(Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    WAIT = "wait"
    ASSERT = "assert"
    API_CALL = "api_call"


DOMAINS = ["shop.example.com", "app.example.com", "portal.example.com", "api.example.com"]
PATHS = ["/dashboard", "/login", "/checkout", "/profile", "/search", "/api/v1/health"]
ERROR_MESSAGES = [
    "Connection refused", "Timeout after 30s", "SSL handshake failed",
    "DNS resolution failed", "HTTP 503 Service Unavailable", "Element not found",
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)",
]
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]


@dataclass
class JourneyStep:
    step_id: str
    step_type: str
    target: str
    duration_ms: float
    status: str
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class UserJourney:
    journey_id: str
    name: str
    region: str
    worker_id: str
    started_at: str
    completed_at: str
    total_duration_ms: float
    status: str
    steps: List[Dict]
    tags: Dict = field(default_factory=dict)


@dataclass
class MetricPoint:
    metric_id: str
    journey_id: str
    metric_name: str
    value: float
    unit: str
    timestamp: str
    dimensions: Dict = field(default_factory=dict)


def _ts(offset_ms: int = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_ms / 1000.0))


def _id() -> str:
    return uuid.uuid4().hex[:12]


def generate_step(status: Optional[str] = None) -> JourneyStep:
    step_type = random.choice(list(StepType)).value
    step_status = status or (random.choice([JourneyStatus.SUCCESS.value] * 8 + [JourneyStatus.FAILURE.value]))
    duration = random.uniform(5, 2000) if step_status == JourneyStatus.SUCCESS.value else random.uniform(1000, 30000)
    target = random.choice(PATHS) if step_type in ("navigate", "api_call") else f"#{random.choice(['btn-submit', 'input-email', 'nav-cart', 'modal-close'])}"
    error = random.choice(ERROR_MESSAGES) if step_status != JourneyStatus.SUCCESS.value else None
    return JourneyStep(step_id=_id(), step_type=step_type, target=target, duration_ms=round(duration, 2), status=step_status, error=error)


def generate_journey(name: Optional[str] = None, region: Optional[str] = None, force_status: Optional[str] = None) -> UserJourney:
    journey_name = name or f"journey-{random.choice(['login', 'checkout', 'browse', 'search', 'api-health'])}"
    journey_region = region or random.choice(REGIONS)
    num_steps = random.randint(2, 8)
    steps = []
    status = force_status or JourneyStatus.SUCCESS.value
    for i in range(num_steps):
        step_status = JourneyStatus.FAILURE.value if (status != JourneyStatus.SUCCESS.value and i == num_steps - 1) else JourneyStatus.SUCCESS.value
        steps.append(asdict(generate_step(step_status)))
    total_ms = sum(s["duration_ms"] for s in steps)
    started = _ts(-int(total_ms))
    return UserJourney(
        journey_id=_id(), name=journey_name, region=journey_region, worker_id=f"worker-{_id()}",
        started_at=started, completed_at=_ts(), total_duration_ms=round(total_ms, 2),
        status=status, steps=steps, tags={"env": "test", "run": hashlib.md5(str(time.time()).encode()).hexdigest()[:8]},
    )


def generate_metrics(journey: UserJourney) -> List[MetricPoint]:
    points = []
    base = {
        "journey_id": journey.journey_id,
        "timestamp": journey.completed_at,
        "dimensions": {"region": journey.region, "worker_id": journey.worker_id, "journey_name": journey.name},
    }
    points.append(MetricPoint(metric_id=_id(), metric_name="journey.duration_ms", value=journey.total_duration_ms, unit="ms", **base))
    points.append(MetricPoint(metric_id=_id(), metric_name="journey.step_count", value=float(len(journey.steps)), unit="count", **base))
    points.append(MetricPoint(metric_id=_id(), metric_name="journey.success", value=1.0 if journey.status == "success" else 0.0, unit="bool", **base))
    for step in journey.steps:
        dim = {**base["dimensions"], "step_type": step["step_type"]}
        points.append(MetricPoint(metric_id=_id(), metric_name="step.duration_ms", value=step["duration_ms"], unit="ms", timestamp=journey.completed_at, dimensions=dim))
    return points


def generate_dataset(num_journeys: int = 10, failure_rate: float = 0.15) -> Dict:
    journeys = []
    metrics = []
    for _ in range(num_journeys):
        status = JourneyStatus.FAILURE.value if random.random() < failure_rate else JourneyStatus.SUCCESS.value
        j = generate_journey(force_status=status)
        journeys.append(asdict(j))
        metrics.extend([asdict(m) for m in generate_metrics(j)])
    return {"generated_at": _ts(), "journey_count": len(journeys), "metric_count": len(metrics), "journeys": journeys, "metrics": metrics}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate mock synthetic monitoring datasets")
    parser.add_argument("-n", "--count", type=int, default=10, help="Number of journeys to generate")
    parser.add_argument("-f", "--failure-rate", type=float, default=0.15, help="Failure rate (0.0-1.0)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output file path (stdout if omitted)")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent level")
    args = parser.parse_args()

    dataset = generate_dataset(num_journeys=args.count, failure_rate=args.failure_rate)
    output = json.dumps(dataset, indent=args.indent)

    if args.output:
        with open(args.output, "w") as fh:
            fh.write(output)
        print(f"Wrote {dataset['journey_count']} journeys, {dataset['metric_count']} metrics to {args.output}")
    else:
        print(output)