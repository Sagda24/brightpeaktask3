from datetime import datetime


class EpisodicMemory:
    def __init__(self):
        self.episodes = []

    def add_episode(self, student_id, event, importance=0.5):
        episode = {
            "student_id": student_id,
            "event": event,
            "importance": importance,
            "timestamp": datetime.now().isoformat()
        }

        self.episodes.append(episode)

    def get_episodes(self, student_id=None):
        if student_id is None:
            return self.episodes.copy()

        return [
            episode
            for episode in self.episodes
            if episode["student_id"] == student_id
        ]

    def clear(self):
        self.episodes.clear()