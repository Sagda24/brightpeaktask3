from datetime import datetime


class SemanticMemory:
    def __init__(self):
        self.facts = {}

    def add_fact(self, student_id, key, value, expires_at=None):
        student_facts = self.facts.setdefault(student_id, {})

        if key not in student_facts:
            student_facts[key] = []

        versions = student_facts[key]

        # Deactivate the previous active version
        for fact in versions:
            if fact["active"]:
                fact["active"] = False

        version = len(versions) + 1

        new_fact = {
            "value": value,
            "version": version,
            "active": True,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at
        }

        versions.append(new_fact)

    def get_fact(self, student_id, key):
        student_facts = self.facts.get(student_id, {})

        versions = student_facts.get(key, [])

        for fact in reversed(versions):
            if not fact["active"]:
                continue

            # Check expiration
            if fact["expires_at"] is not None:
                expiration = datetime.fromisoformat(fact["expires_at"])

                if datetime.now() >= expiration:
                    fact["active"] = False
                    continue

            return fact

        return None

    def get_all_facts(self, student_id):
        student_facts = self.facts.get(student_id, {})

        active_facts = {}

        for key, versions in student_facts.items():
            fact = self.get_fact(student_id, key)

            if fact is not None:
                active_facts[key] = fact

        return active_facts

    def get_history(self, student_id, key):
        student_facts = self.facts.get(student_id, {})

        return student_facts.get(key, []).copy()

    def remove_fact(self, student_id, key):
        student_facts = self.facts.get(student_id, {})

        versions = student_facts.get(key, [])

        for fact in versions:
            fact["active"] = False

    def clear(self):
        self.facts.clear()