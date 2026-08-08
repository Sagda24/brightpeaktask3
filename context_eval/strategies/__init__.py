from .sliding_window import SlidingWindowStrategy
from .observation_masking import ObservationMaskingStrategy
from .recursive_summarization import RecursiveSummarizationStrategy
from .zone_based_pruning import ZoneBasedPruningStrategy

ALL_STRATEGIES = [
    SlidingWindowStrategy(window=10),
    ObservationMaskingStrategy(keep_last_tool_outputs=3),
    RecursiveSummarizationStrategy(compress_every=15, keep_recent_full=15),
    ZoneBasedPruningStrategy(recent_zone_size=8),
]

__all__ = [
    "SlidingWindowStrategy", "ObservationMaskingStrategy",
    "RecursiveSummarizationStrategy", "ZoneBasedPruningStrategy",
    "ALL_STRATEGIES",
]
