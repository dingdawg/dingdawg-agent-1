from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from statistics import mean
from threading import RLock
from time import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple


class CodingImprovementError(Exception):
    """Raised when coding improvement validation or execution fails."""


class CodingValidationError(CodingImprovementError):
    """Raised when coding improvement inputs are invalid."""


def _validate_non_empty_string(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise CodingValidationError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise CodingValidationError(f"{field_name} must not be empty.")
    return cleaned


def _validate_finite_float(
    value: float,
    field_name: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CodingValidationError(f"{field_name} must be a number.")
    numeric = float(value)
    if not isfinite(numeric):
        raise CodingValidationError(f"{field_name} must be finite.")
    if minimum is not None and numeric < minimum:
        raise CodingValidationError(f"{field_name} must be greater than or equal to {minimum}.")
    if maximum is not None and numeric > maximum:
        raise CodingValidationError(f"{field_name} must be less than or equal to {maximum}.")
    return numeric


def _validate_positive_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CodingValidationError(f"{field_name} must be an integer.")
    if value <= 0:
        raise CodingValidationError(f"{field_name} must be greater than 0.")
    return value


def _validate_optional_timestamp(value: Optional[float], field_name: str) -> Optional[float]:
    if value is None:
        return None
    return _validate_finite_float(value, field_name, minimum=0.0)


def _validate_string_mapping(values: Mapping[str, Any], field_name: str) -> Dict[str, Any]:
    if not isinstance(values, Mapping):
        raise CodingValidationError(f"{field_name} must be a mapping.")
    normalized: Dict[str, Any] = {}
    for key, item in values.items():
        normalized_key = _validate_non_empty_string(str(key), f"{field_name}.key")
        normalized[normalized_key] = item
    return normalized


def _validate_string_sequence(values: Sequence[str], field_name: str) -> List[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CodingValidationError(f"{field_name} must be a sequence of strings.")
    normalized: List[str] = []
    for index, value in enumerate(values):
        normalized.append(_validate_non_empty_string(value, f"{field_name}[{index}]"))
    return normalized


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class CodeQualitySignal:
    """A normalized quality signal for a generated coding outcome."""

    name: str
    score: float
    weight: float
    details: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validate_non_empty_string(self.name, "signal.name"))
        object.__setattr__(
            self,
            "score",
            _validate_finite_float(self.score, "signal.score", minimum=0.0, maximum=1.0),
        )
        object.__setattr__(
            self,
            "weight",
            _validate_finite_float(self.weight, "signal.weight", minimum=0.0),
        )
        object.__setattr__(self, "details", self.details.strip())


@dataclass(frozen=True)
class ImprovementRecommendation:
    """A prioritized recommendation for future coding improvements."""

    action: str
    priority: int
    rationale: str
    target_area: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _validate_non_empty_string(self.action, "action"))
        object.__setattr__(
            self,
            "priority",
            _validate_positive_int(self.priority, "priority"),
        )
        object.__setattr__(self, "rationale", _validate_non_empty_string(self.rationale, "rationale"))
        object.__setattr__(
            self,
            "target_area",
            _validate_non_empty_string(self.target_area, "target_area"),
        )


@dataclass(frozen=True)
class ImprovementStrategy:
    """Reusable strategy state that guides future code generation and review."""

    emphasis: Dict[str, float] = field(default_factory=dict)
    required_checks: List[str] = field(default_factory=list)
    repair_playbook: List[str] = field(default_factory=list)
    max_retry_attempts: int = 2

    def __post_init__(self) -> None:
        normalized_emphasis = _validate_string_mapping(self.emphasis, "strategy.emphasis")
        normalized_weights: Dict[str, float] = {}
        for key, value in normalized_emphasis.items():
            normalized_weights[key] = _validate_finite_float(
                float(value),
                f"strategy.emphasis[{key}]",
                minimum=0.0,
            )
        object.__setattr__(self, "emphasis", normalized_weights)
        object.__setattr__(
            self,
            "required_checks",
            _validate_string_sequence(self.required_checks, "strategy.required_checks"),
        )
        object.__setattr__(
            self,
            "repair_playbook",
            _validate_string_sequence(self.repair_playbook, "strategy.repair_playbook"),
        )
        object.__setattr__(
            self,
            "max_retry_attempts",
            _validate_positive_int(self.max_retry_attempts, "strategy.max_retry_attempts"),
        )


@dataclass(frozen=True)
class CodingImprovementReport:
    """Deterministic report describing quality, adjustments, and execution readiness."""

    generated_at: float
    objective: str
    overall_score: float
    weighted_signal_score: float
    quality_signals: List[CodeQualitySignal]
    recommendations: List[ImprovementRecommendation]
    strategy: ImprovementStrategy
    metrics: Dict[str, float]
    notes: List[str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generated_at",
            _validate_finite_float(self.generated_at, "report.generated_at", minimum=0.0),
        )
        object.__setattr__(self, "objective", _validate_non_empty_string(self.objective, "report.objective"))
        object.__setattr__(
            self,
            "overall_score",
            _validate_finite_float(self.overall_score, "report.overall_score", minimum=0.0, maximum=1.0),
        )
        object.__setattr__(
            self,
            "weighted_signal_score",
            _validate_finite_float(
                self.weighted_signal_score,
                "report.weighted_signal_score",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        for index, signal in enumerate(self.quality_signals):
            if not isinstance(signal, CodeQualitySignal):
                raise CodingValidationError(
                    f"report.quality_signals[{index}] must be a CodeQualitySignal."
                )
        for index, recommendation in enumerate(self.recommendations):
            if not isinstance(recommendation, ImprovementRecommendation):
                raise CodingValidationError(
                    f"report.recommendations[{index}] must be an ImprovementRecommendation."
                )
        if not isinstance(self.strategy, ImprovementStrategy):
            raise CodingValidationError("report.strategy must be an ImprovementStrategy.")
        normalized_metrics = _validate_string_mapping(self.metrics, "report.metrics")
        validated_metrics: Dict[str, float] = {}
        for key, value in normalized_metrics.items():
            validated_metrics[key] = _validate_finite_float(
                float(value),
                f"report.metrics[{key}]",
            )
        object.__setattr__(self, "metrics", validated_metrics)
        object.__setattr__(self, "notes", _validate_string_sequence(self.notes, "report.notes"))


@dataclass
class CodingImprovementEngine:
    """Scores coding outcomes, updates strategy, and records reusable improvement state."""

    baseline_strategy: ImprovementStrategy = field(default_factory=ImprovementStrategy)
    score_floor: float = 0.7
    recommendation_limit: int = 5
    _history: List[CodingImprovementReport] = field(default_factory=list, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.baseline_strategy, ImprovementStrategy):
            raise CodingValidationError("baseline_strategy must be an ImprovementStrategy.")
        self.score_floor = _validate_finite_float(
            self.score_floor,
            "score_floor",
            minimum=0.0,
            maximum=1.0,
        )
        self.recommendation_limit = _validate_positive_int(
            self.recommendation_limit,
            "recommendation_limit",
        )

    def evaluate(
        self,
        *,
        objective: str,
        quality_signals: Sequence[CodeQualitySignal],
        execution_metrics: Optional[Mapping[str, float]] = None,
        notes: Optional[Sequence[str]] = None,
        current_time: Optional[float] = None,
    ) -> CodingImprovementReport:
        normalized_objective = _validate_non_empty_string(objective, "objective")
        normalized_signals = self._normalize_signals(quality_signals)
        normalized_metrics = self._normalize_metrics(execution_metrics)
        normalized_notes = self._normalize_notes(notes)
        timestamp = _validate_optional_timestamp(current_time, "current_time")
        generated_at = time() if timestamp is None else timestamp

        weighted_signal_score = self._compute_weighted_signal_score(normalized_signals)
        coverage_score = self._compute_coverage_score(normalized_signals)
        stability_score = self._compute_stability_score(normalized_metrics)
        overall_score = _clamp_score(
            round((weighted_signal_score * 0.75) + (coverage_score * 0.15) + (stability_score * 0.10), 6)
        )

        strategy = self._derive_strategy(
            quality_signals=normalized_signals,
            execution_metrics=normalized_metrics,
            overall_score=overall_score,
        )
        recommendations = self._build_recommendations(
            quality_signals=normalized_signals,
            execution_metrics=normalized_metrics,
            overall_score=overall_score,
            strategy=strategy,
        )

        report_metrics: Dict[str, float] = dict(normalized_metrics)
        report_metrics["coverage_score"] = coverage_score
        report_metrics["stability_score"] = stability_score
        report_metrics["signal_count"] = float(len(normalized_signals))

        report = CodingImprovementReport(
            generated_at=generated_at,
            objective=normalized_objective,
            overall_score=overall_score,
            weighted_signal_score=weighted_signal_score,
            quality_signals=normalized_signals,
            recommendations=recommendations,
            strategy=strategy,
            metrics=report_metrics,
            notes=normalized_notes,
        )

        with self._lock:
            self._history.append(report)
        return report

    def latest_report(self) -> Optional[CodingImprovementReport]:
        with self._lock:
            if not self._history:
                return None
            return self._history[-1]

    def history(self) -> List[CodingImprovementReport]:
        with self._lock:
            return list(self._history)

    def current_strategy(self) -> ImprovementStrategy:
        latest = self.latest_report()
        if latest is None:
            return self.baseline_strategy
        return latest.strategy

    def upgrade_foundation(
        self,
        *,
        objective: str,
        quality_signals: Sequence[CodeQualitySignal],
        execution_metrics: Optional[Mapping[str, float]] = None,
        notes: Optional[Sequence[str]] = None,
        current_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        report = self.evaluate(
            objective=objective,
            quality_signals=quality_signals,
            execution_metrics=execution_metrics,
            notes=notes,
            current_time=current_time,
        )
        return {
            "objective": report.objective,
            "overall_score": report.overall_score,
            "meets_floor": report.overall_score >= self.score_floor,
            "strategy": {
                "emphasis": dict(report.strategy.emphasis),
                "required_checks": list(report.strategy.required_checks),
                "repair_playbook": list(report.strategy.repair_playbook),
                "max_retry_attempts": report.strategy.max_retry_attempts,
            },
            "recommendations": [
                {
                    "action": item.action,
                    "priority": item.priority,
                    "rationale": item.rationale,
                    "target_area": item.target_area,
                }
                for item in report.recommendations
            ],
            "metrics": dict(report.metrics),
            "notes": list(report.notes),
        }

    def _normalize_signals(self, quality_signals: Sequence[CodeQualitySignal]) -> List[CodeQualitySignal]:
        if not isinstance(quality_signals, Sequence) or isinstance(quality_signals, (str, bytes)):
            raise CodingValidationError("quality_signals must be a sequence of CodeQualitySignal values.")
        normalized: List[CodeQualitySignal] = []
        for index, signal in enumerate(quality_signals):
            if not isinstance(signal, CodeQualitySignal):
                raise CodingValidationError(
                    f"quality_signals[{index}] must be a CodeQualitySignal."
                )
            normalized.append(signal)
        if not normalized:
            raise CodingValidationError("quality_signals must not be empty.")
        return normalized

    def _normalize_metrics(self, execution_metrics: Optional[Mapping[str, float]]) -> Dict[str, float]:
        if execution_metrics is None:
            return {}
        normalized_mapping = _validate_string_mapping(execution_metrics, "execution_metrics")
        normalized_metrics: Dict[str, float] = {}
        for key, value in normalized_mapping.items():
            normalized_metrics[key] = _validate_finite_float(
                float(value),
                f"execution_metrics[{key}]",
            )
        return normalized_metrics

    def _normalize_notes(self, notes: Optional[Sequence[str]]) -> List[str]:
        if notes is None:
            return []
        return _validate_string_sequence(notes, "notes")

    def _compute_weighted_signal_score(self, quality_signals: Sequence[CodeQualitySignal]) -> float:
        total_weight = sum(signal.weight for signal in quality_signals)
        if total_weight <= 0.0:
            raise CodingImprovementError("At least one quality signal must have positive weight.")
        weighted_sum = sum(signal.score * signal.weight for signal in quality_signals)
        return _clamp_score(round(weighted_sum / total_weight, 6))

    def _compute_coverage_score(self, quality_signals: Sequence[CodeQualitySignal]) -> float:
        signal_names = {signal.name for signal in quality_signals}
        desired_categories = {
            "typing",
            "error_handling",
            "validation",
            "integration",
            "testing",
            "maintainability",
        }
        matched = len(signal_names.intersection(desired_categories))
        return _clamp_score(round(matched / len(desired_categories), 6))

    def _compute_stability_score(self, execution_metrics: Mapping[str, float]) -> float:
        if not execution_metrics:
            return 0.5
        normalized_components: List[float] = []
        for key, value in execution_metrics.items():
            lowered = key.lower()
            if "fail" in lowered or "error" in lowered or "regression" in lowered:
                normalized_components.append(_clamp_score(1.0 - min(1.0, value)))
            elif "pass" in lowered or "success" in lowered or "coverage" in lowered:
                normalized_components.append(_clamp_score(min(1.0, value)))
            elif "retry" in lowered or "latency" in lowered or "duration" in lowered:
                normalized_components.append(_clamp_score(1.0 - min(1.0, value)))
        if not normalized_components:
            return 0.5
        return _clamp_score(round(mean(normalized_components), 6))

    def _derive_strategy(
        self,
        *,
        quality_signals: Sequence[CodeQualitySignal],
        execution_metrics: Mapping[str, float],
        overall_score: float,
    ) -> ImprovementStrategy:
        emphasis: MutableMapping[str, float] = dict(self.baseline_strategy.emphasis)
        required_checks: List[str] = list(self.baseline_strategy.required_checks)
        repair_playbook: List[str] = list(self.baseline_strategy.repair_playbook)

        for signal in quality_signals:
            current_weight = emphasis.get(signal.name, 1.0)
            if signal.score < self.score_floor:
                emphasis[signal.name] = round(current_weight + (self.score_floor - signal.score), 6)
                check_name = f"verify_{signal.name}"
                if check_name not in required_checks:
                    required_checks.append(check_name)
                repair_step = f"repair_{signal.name}"
                if repair_step not in repair_playbook:
                    repair_playbook.append(repair_step)
            else:
                emphasis[signal.name] = round(max(0.5, current_weight * 0.95), 6)

        if execution_metrics.get("retry_rate", 0.0) > 0.0:
            if "retry_budget_review" not in required_checks:
                required_checks.append("retry_budget_review")
            if "reduce_retry_cycles" not in repair_playbook:
                repair_playbook.append("reduce_retry_cycles")

        max_retry_attempts = self.baseline_strategy.max_retry_attempts
        if overall_score < self.score_floor:
            max_retry_attempts = max(max_retry_attempts, 3)

        return ImprovementStrategy(
            emphasis=dict(emphasis),
            required_checks=required_checks,
            repair_playbook=repair_playbook,
            max_retry_attempts=max_retry_attempts,
        )

    def _build_recommendations(
        self,
        *,
        quality_signals: Sequence[CodeQualitySignal],
        execution_metrics: Mapping[str, float],
        overall_score: float,
        strategy: ImprovementStrategy,
    ) -> List[ImprovementRecommendation]:
        recommendations: List[ImprovementRecommendation] = []

        sorted_signals = sorted(
            quality_signals,
            key=lambda item: (item.score, -item.weight, item.name),
        )
        for signal in sorted_signals:
            if signal.score >= self.score_floor:
                continue
            recommendations.append(
                ImprovementRecommendation(
                    action=f"Increase {signal.name} guardrails",
                    priority=len(recommendations) + 1,
                    rationale=(
                        f"{signal.name} scored {signal.score:.2f}, below floor {self.score_floor:.2f}."
                    ),
                    target_area=signal.name,
                )
            )

        if execution_metrics.get("failure_rate", 0.0) > 0.0:
            recommendations.append(
                ImprovementRecommendation(
                    action="Strengthen post-generation repair loop",
                    priority=len(recommendations) + 1,
                    rationale="Failure rate indicates generated outputs require additional repair passes.",
                    target_area="repair_loop",
                )
            )

        if execution_metrics.get("retry_rate", 0.0) > 0.0:
            recommendations.append(
                ImprovementRecommendation(
                    action="Reduce retry churn through preflight checks",
                    priority=len(recommendations) + 1,
                    rationale="Retry activity suggests preventable issues are escaping first-pass validation.",
                    target_area="preflight_validation",
                )
            )

        if overall_score >= self.score_floor and not recommendations:
            recommendations.append(
                ImprovementRecommendation(
                    action="Promote current strategy as reusable baseline",
                    priority=1,
                    rationale="Current coding quality meets threshold and is suitable for reuse.",
                    target_area="baseline_strategy",
                )
            )

        if "verify_integration" in strategy.required_checks and len(recommendations) < self.recommendation_limit:
            recommendations.append(
                ImprovementRecommendation(
                    action="Expand local convention detection before code generation",
                    priority=len(recommendations) + 1,
                    rationale="Integration checks are required, indicating convention-aware generation should be strengthened.",
                    target_area="integration",
                )
            )

        recommendations.sort(key=lambda item: item.priority)
        return recommendations[: self.recommendation_limit]


def build_coding_improvement_engine() -> CodingImprovementEngine:
    return CodingImprovementEngine()