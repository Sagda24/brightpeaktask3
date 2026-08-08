from .short_term import ShortTermMemory
from .scratchpad import Scratchpad
from .episodic import EpisodicMemory
from .router import MemoryRouter
from .semantic import SemanticMemory
from .consolidation import MemoryConsolidator


class MemoryManager:
    # How many newly-promoted episodes accumulate before an automatic
    # consolidation pass runs. This is what makes consolidation genuinely
    # "periodic" rather than tied to any single write: it's a batch trigger,
    # decoupled from add_message(). In production, swap this for (or combine
    # with) a time-based scheduler -- see run_consolidation_pass().
    CONSOLIDATION_BATCH_SIZE = 3

    def __init__(self, max_messages=10):
        self.short_term = ShortTermMemory(max_messages)
        self.scratchpad = Scratchpad()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

        self.router = MemoryRouter(self.episodic)
        self.consolidator = MemoryConsolidator(self.semantic)

        self._promotions_since_consolidation = 0

    def add_message(self, role, content, student_id=None):
        # Every message goes into the rolling short-term buffer. The router
        # only ever evaluates the message the buffer EVICTS on overflow -- not
        # every incoming message -- which is the actual "decision point on
        # short-term memory overflow" the lab asks for.
        evicted = self.short_term.add_message(role, content)

        if evicted is None or evicted.get("role") != "student" or student_id is None:
            return {
                "decision": "NONE",
                "reason": "No aging item evicted from short-term memory yet.",
            }

        decision = self.router.decide(evicted["content"], student_id)

        if decision["decision"] == "PROMOTE":
            self._promotions_since_consolidation += 1
            if self._promotions_since_consolidation >= self.CONSOLIDATION_BATCH_SIZE:
                self.run_consolidation_pass()

        return decision

    def run_consolidation_pass(self):
        """Explicit, periodic consolidation entrypoint. Never called inline for
        a single episode -- only as a batch pass (here: after enough promotions
        accumulate; in production: also/instead call this from a cron job)."""
        actions = self.consolidator.run_pass(self.episodic)
        self._promotions_since_consolidation = 0
        return actions

    def get_recent_messages(self):
        return self.short_term.get_messages()

    # --- Scratchpad: the agent's CURRENT working state (active plan, sub-goal,
    # in-flight tool call) -- distinct from the short-term message buffer above.
    # Pruning short_term never touches this. Callers (the agent loop) should
    # update it as the plan evolves, e.g.:
    #   memory.set_working_state("current_subgoal", "check prereqs for CS401")
    #   memory.set_working_state("pending_tool_call", "get_student_profile")
    def set_working_state(self, key, value):
        self.scratchpad.set(key, value)

    def clear_working_state(self, key):
        self.scratchpad.remove(key)

    def get_scratchpad(self):
        return self.scratchpad.get_all()

    def get_student_memory(self, student_id):
        return self.semantic.get_all_facts(student_id)

    def get_student_episodes(self, student_id):
        return self.episodic.get_episodes(student_id)

    def get_routing_log(self):
        """Every promote-or-drop decision made, with reasoning -- for a grader
        to inspect directly."""
        return self.router.get_log()

    def get_consolidation_log(self):
        """Every fact created / conflict resolved by the periodic consolidation
        pass, across all runs -- for a grader to inspect directly."""
        return self.consolidator.consolidation_log

    def clear_session(self):
        self.short_term.clear()
        self.scratchpad.clear()