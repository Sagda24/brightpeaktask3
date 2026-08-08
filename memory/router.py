from .episodic import EpisodicMemory
class MemoryRouter:
    def __init__(self, episodic_memory):
        self.episodic_memory = episodic_memory

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
            "schedule"
        ]

        for keyword in important_keywords:
            if keyword in message_lower:

                self.episodic_memory.add_episode(
                    student_id=student_id,
                    event=message,
                    importance=0.8
                )

                return {
                    "decision": "PROMOTE",
                    "reason": f"Message contains important information related to {keyword}."
                }

        return {
            "decision": "DROP",
            "reason": "Message does not contain information that needs to be remembered."
        }