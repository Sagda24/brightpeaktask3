from .base import ContextStrategy

# Reuses the same importance vocabulary as memory/router.py's promote-or-drop
# decision, applied here to decide which turns get PINNED into their own
# zone regardless of age -- the context-management analogue of promoting a
# short-term item to episodic memory.
PINNED_KEYWORDS = [
    "waiver", "hold", "exception", "transfer credit", "cleared",
    "approved", "prerequisite", "overload",
]


def _is_pinnable(content: str) -> bool:
    low = content.lower()
    return any(kw in low for kw in PINNED_KEYWORDS)


class ZoneBasedPruningStrategy(ContextStrategy):
    """Four zones, each pruned by a different rule:
      Zone 1 (system)     -- a fixed short system turn, always kept.
      Zone 2 (pinned)      -- any turn matching PINNED_KEYWORDS, kept verbatim
                               no matter how old. This is what protects the
                               waiver/hold/exception fact specifically.
      Zone 3 (recent)      -- the last `recent_zone_size` turns, kept verbatim.
      Zone 4 (archive)     -- everything else, collapsed to a one-line stub
                               per turn (cheap enough to keep for continuity
                               without paying full tool-JSON cost).
    """

    name = "zone_based_pruning"

    def __init__(self, recent_zone_size: int = 8):
        self.recent_zone_size = recent_zone_size

    def apply(self, turns: list) -> dict:
        n = len(turns)
        recent_cutoff = max(0, n - self.recent_zone_size)

        system_zone = [{
            "turn": 0, "speaker": "system", "type": "system", "tool_name": None,
            "is_critical": False,
            "content": "You are BrightPeak Academy's registration advising assistant. "
                       "Always account for any waivers, holds, or exceptions on file.",
        }]

        pinned_zone = []
        archive_zone = []
        recent_zone = []

        for i, t in enumerate(turns):
            if i >= recent_cutoff:
                recent_zone.append(t)
            elif _is_pinnable(t["content"]):
                pinned_zone.append(t)
            else:
                stub = f"[t{t['turn']} {t['speaker']}/{t['type']}"
                if t.get("tool_name"):
                    stub += f" {t['tool_name']}"
                stub += " -- routine, archived]"
                archive_zone.append({**t, "content": stub})

        pruned = system_zone + pinned_zone + archive_zone + recent_zone
        return {
            "pruned_turns": pruned,
            "extra_output_tokens": 0,
            "extra_llm_calls": 0,
            "notes": f"zones -> system:1, pinned:{len(pinned_zone)}, "
                     f"archive(stubbed):{len(archive_zone)}, recent:{len(recent_zone)}",
        }
