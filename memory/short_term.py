class ShortTermMemory:
    """Rolling message buffer. Distinct from the Scratchpad (working state) --
    pruning this buffer never touches the scratchpad."""

    def __init__(self, max_messages=10):
        self.max_messages = max_messages
        self.messages = []

    def add_message(self, role, content):
        message = {
            "role": role,
            "content": content
        }

        self.messages.append(message)

        # Keep only the latest messages. When the buffer overflows, return the
        # evicted (aging) message so the caller can route it through
        # promote-or-drop -- this is the "decision point on short-term memory
        # overflow" the router is supposed to act on, not on every new message.
        evicted = None
        if len(self.messages) > self.max_messages:
            evicted = self.messages.pop(0)

        return evicted

    def get_messages(self):
        return self.messages.copy()

    def clear(self):
        self.messages.clear()

    def __len__(self):
        return len(self.messages)