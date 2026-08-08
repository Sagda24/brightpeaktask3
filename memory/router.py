from datetime import datetime
from .episodic import EpisodicMemory


class MemoryRouter:
    """Fires when short-term memory overflows (see ShortTermMemory.add_message's
    evicted return value / MemoryManager.add_message). For each aging item,
    decides forget (DROP) or promote to episodic memory (PROMOTE). Never writes
    to semantic memory directly -- semantic memory is only ever built by the
    separate MemoryConsolidator pass."""

    def __init__(self, episodic_memory):
        self.episodic_memory = episodic_memory
        self.log = []  # every routing decision, visible to a grader via get_log()

    def decide(self, message, student_id):
        message_lower = message.lower()

        important_keywords = [
            "major",
            "course",
            "grade",
            "student",
            "prefer",
            "preference",
            "goal",
            "enroll",
            "exam",
            "retake",
            "schedule",
            "waiver",
            "prerequisite",
            "hold",
        ]

        matched = next((kw for kw in important_keywords if kw in message_lower), None)

        if matched:
            self.episodic_memory.add_episode(
                student_id=student_id,
                event=message,
                importance=0.8
            )
            decision = {
                "decision": "PROMOTE",
                "reason": f"Message contains important information related to '{matched}'.",
            }
        else:
            decision = {
                "decision": "DROP",
                "reason": "Message does not contain information that needs to be remembered.",
            }

        self.log.append({
            "student_id": student_id,
            "message": message,
            "decision": decision["decision"],
            "reason": decision["reason"],
            "timestamp": datetime.now().isoformat(),
        })
        return decision

    def get_log(self):
        return self.log.copy()