"""Point-in-time market-data contracts and validated venue adapters."""

from .binance import (
    BinanceDerivativeReference,
    BinanceInstrument,
    BinanceKline,
    BinanceKlinePage,
    BinanceMarket,
    BinanceMarketDataClient,
    ProviderRateLimited,
    ProviderResponseError,
)
from .features import Bar, FeatureDefinition, FeatureResult, asof_join, build_bars
from .instruments import InstrumentSpec, LifecycleEvent, LifecycleEventKind, SymbolMaster
from .ml import LabelDefinition, ModelArtifact, PredictionSanity, TrainingRun, prediction_sanity
from .monitoring import ClockMeasurement, DisagreementClass, ReconciliationRecord
from .models import (
    CanonicalMarketRecord,
    DatasetManifest,
    FidelityTier,
    PriceKind,
    QualityStatus,
    RawPayload,
)
from .orderbook import OrderBook, OrderBookDelta, OrderBookSnapshot, SequenceGapError
from .provenance import RawPayloadStore, canonical_content_hash
from .validation import DataQualityError, DatasetValidator, ValidationFinding

__all__ = [
    "Bar",
    "BinanceDerivativeReference",
    "BinanceInstrument",
    "BinanceKline",
    "BinanceKlinePage",
    "BinanceMarket",
    "BinanceMarketDataClient",
    "CanonicalMarketRecord",
    "ClockMeasurement",
    "DataQualityError",
    "DatasetManifest",
    "DatasetValidator",
    "DisagreementClass",
    "FeatureDefinition",
    "FeatureResult",
    "FidelityTier",
    "InstrumentSpec",
    "LabelDefinition",
    "LifecycleEvent",
    "LifecycleEventKind",
    "OrderBook",
    "OrderBookDelta",
    "OrderBookSnapshot",
    "ModelArtifact",
    "PredictionSanity",
    "PriceKind",
    "ProviderRateLimited",
    "ProviderResponseError",
    "QualityStatus",
    "RawPayload",
    "RawPayloadStore",
    "ReconciliationRecord",
    "SequenceGapError",
    "SymbolMaster",
    "TrainingRun",
    "ValidationFinding",
    "asof_join",
    "build_bars",
    "canonical_content_hash",
    "prediction_sanity",
]
