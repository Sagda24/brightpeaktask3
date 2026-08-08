class MemoryConsolidator:
    def __init__(self, semantic_memory):
        self.semantic_memory = semantic_memory

    def consolidate(self, episode):
        student_id = episode["student_id"]
        event = episode["event"]

        # Simple fact extraction
        event_lower = event.lower()

        if "major" in event_lower:
            if "computer science" in event_lower:
                self.semantic_memory.add_fact(
                    student_id,
                    "major",
                    "Computer Science"
                )

            elif "data science" in event_lower:
                self.semantic_memory.add_fact(
                    student_id,
                    "major",
                    "Data Science"
                )

        if "prefer" in event_lower and "evening" in event_lower:
            self.semantic_memory.add_fact(
                student_id,
                "preferred_class_time",
                "evening"
            )

        if "prefer" in event_lower and "morning" in event_lower:
            self.semantic_memory.add_fact(
                student_id,
                "preferred_class_time",
                "morning"
            )