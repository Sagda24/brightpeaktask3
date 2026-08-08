from .short_term import ShortTermMemory
from .scratchpad import Scratchpad
from .episodic import EpisodicMemory
from .router import MemoryRouter
from .semantic import SemanticMemory
from .consolidation import MemoryConsolidator


class MemoryManager:
    def __init__(self, max_messages=10):
        self.short_term = ShortTermMemory(max_messages)
        self.scratchpad = Scratchpad()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

        self.router = MemoryRouter(self.episodic)
        self.consolidator = MemoryConsolidator(self.semantic)

    def add_message(self, role, content, student_id=None):
        # Store every message in short-term memory
        self.short_term.add_message(role, content)

        # Process student messages for long-term memory
        if role == "student" and student_id is not None:
            decision = self.router.decide(content, student_id)

            if decision["decision"] == "PROMOTE":
                episodes = self.episodic.get_episodes(student_id)

                if episodes:
                    latest_episode = episodes[-1]
                    self.consolidator.consolidate(latest_episode)

            return decision

        return {
            "decision": "NONE",
            "reason": "Message was stored in short-term memory."
        }

    def get_recent_messages(self):
        return self.short_term.get_messages()

    def get_scratchpad(self):
        return self.scratchpad.get_all()

    def get_student_memory(self, student_id):
        return self.semantic.get_all_facts(student_id)

    def get_student_episodes(self, student_id):
        return self.episodic.get_episodes(student_id)

    def clear_session(self):
        self.short_term.clear()
        self.scratchpad.clear()