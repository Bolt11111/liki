"""Financial-ML metadata and leakage-safe model artifact integrity checks."""

from __future__ import annotations

from hashlib import sha256
from collections.abc import Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LabelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    label_id: str
    version: str
    decision_time_semantics: str
    prediction_horizon_seconds: int = Field(gt=0)
    event_end_time_semantics: str
    overlapping_label_semantics: str
    return_price_convention: str
    fees_cost_inclusion: str
    censoring_missing_policy: str
    code_hash: str


class TrainingRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    training_run_id: str
    model_class: str
    feature_versions: Mapping[str, str]
    label: LabelDefinition
    train_split_id: str
    validation_split_id: str
    test_split_id: str
    purge_embargo_policy: str
    hyperparameters: Mapping[str, str | int | float | bool]
    random_seeds: tuple[int, ...]
    environment_fingerprint: str
    search_history_record_ids: tuple[str, ...]
    selected_checkpoint_hash: str
    artifact_hash: str
    selection_used_validation: bool
    final_test_unused_for_selection: bool

    @model_validator(mode="after")
    def nested_selection_integrity(self) -> TrainingRun:
        if not self.feature_versions or not self.search_history_record_ids:
            raise ValueError("training run must retain features and Trial Ledger search history")
        if self.selection_used_validation and not self.final_test_unused_for_selection:
            raise ValueError("selected model requires an unused final test split")
        if not self.random_seeds:
            raise ValueError("random seed policy must be recorded")
        return self


class ModelArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    training_run_id: str
    content_hash: str
    bytes_size: int = Field(ge=0)
    pipeline_hash: str

    @classmethod
    def from_bytes(cls, *, training_run_id: str, artifact: bytes, pipeline: bytes) -> ModelArtifact:
        return cls(
            training_run_id=training_run_id,
            content_hash=f"sha256:{sha256(artifact).hexdigest()}",
            bytes_size=len(artifact),
            pipeline_hash=f"sha256:{sha256(pipeline).hexdigest()}",
        )

    def verify(self, artifact: bytes, training_run: TrainingRun) -> None:
        observed = f"sha256:{sha256(artifact).hexdigest()}"
        if observed != self.content_hash or observed != training_run.artifact_hash:
            raise ValueError("unrecognized model artifact hash is prohibited")


class PredictionSanity(BaseModel):
    model_config = ConfigDict(frozen=True)

    class_prevalence: float = Field(ge=0, le=1)
    prediction_prevalence: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0)
    calibration_bins: tuple[tuple[float, float, int], ...]


def prediction_sanity(probabilities: Sequence[float], labels: Sequence[int]) -> PredictionSanity:
    """Report prevalence and calibration rather than allowing accuracy-only promotion."""
    probability_array = np.asarray(probabilities, dtype=float)
    label_array = np.asarray(labels, dtype=float)
    if (
        probability_array.ndim != 1
        or len(probability_array) == 0
        or probability_array.shape != label_array.shape
    ):
        raise ValueError("probabilities and labels must be equal non-empty one-dimensional series")
    if not np.all(np.isfinite(probability_array)) or np.any(
        (probability_array < 0) | (probability_array > 1)
    ):
        raise ValueError("probabilities must be finite values in [0, 1]")
    if not np.all(np.isin(label_array, [0, 1])):
        raise ValueError("labels must be binary")
    bins: list[tuple[float, float, int]] = []
    for lower in np.arange(0.0, 1.0, 0.1):
        mask = (probability_array >= lower) & (
            probability_array < lower + 0.1 if lower < 0.9 else probability_array <= 1
        )
        if np.any(mask):
            bins.append(
                (
                    float(np.mean(probability_array[mask])),
                    float(np.mean(label_array[mask])),
                    int(mask.sum()),
                )
            )
    return PredictionSanity(
        class_prevalence=float(np.mean(label_array)),
        prediction_prevalence=float(np.mean(probability_array >= 0.5)),
        brier_score=float(np.mean((probability_array - label_array) ** 2)),
        calibration_bins=tuple(bins),
    )
