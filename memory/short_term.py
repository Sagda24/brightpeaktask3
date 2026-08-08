class ShortTermMemory:
    def __init__(self, max_messages=10):
        self.max_messages = max_messages
        self.messages = []

    def add_message(self, role, content):
        message = {
            "role": role,
            "content": content
        }

        self.messages.append(message)

        # Keep only the latest messages
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def get_messages(self):
        return self.messages.copy()

    def clear(self):
        self.messages.clear()

    def __len__(self):
        return len(self.messages)