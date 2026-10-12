"""Alert episodes persist through rule changes and gaps in usable evidence."""

from copy import deepcopy


class AlertTracker:
    def __init__(self, recovery_samples: int):
        self.recovery_samples = recovery_samples
        self.state = "warming"
        self.observation = "insufficient"
        self.episode: dict | None = None
        self.recovery_streak = 0
        self.abnormal_streak = 0
        self.episode_count = 0

    @property
    def active(self) -> bool:
        return self.episode is not None and self.episode["ended_frame"] is None

    def observe(self, frame: int, generation: int, drift_type: str,
                drift_detected: bool, status: str, ready: bool) -> str | None:
        noteworthy = drift_detected or status != "ok"
        self.observation = ("unavailable" if status != "ok" else "drift" if drift_detected
                            else "clear" if ready else "insufficient")
        if noteworthy:
            self.recovery_streak = 0
            self.abnormal_streak += 1
            transition = None
            if not self.active:
                self.episode_count += 1
                self.episode = {"number": self.episode_count, "baseline_generation": generation,
                                "incident_id": None, "started_frame": frame, "last_abnormal_frame": frame,
                                "ended_frame": None, "drift_types": [], "unavailable_statuses": []}
                transition = "opened"
            self.episode["last_abnormal_frame"] = frame
            if drift_detected and drift_type not in self.episode["drift_types"]:
                self.episode["drift_types"].append(drift_type)
                transition = transition or "updated"
            if status != "ok" and status not in self.episode["unavailable_statuses"]:
                self.episode["unavailable_statuses"].append(status)
                transition = transition or "updated"
            self.state = "active"
            return transition
        self.abnormal_streak = 0
        if not ready:
            self.recovery_streak = 0
            self.state = "blocked" if self.active else "warming"
            return None
        if self.active:
            self.recovery_streak += 1
            if self.recovery_streak >= self.recovery_samples:
                self.episode["ended_frame"] = frame
                self.state = "recovered"
                return "recovered"
            self.state = "recovering"
        else:
            self.state = "recovered" if self.episode else "clear"
        return None

    def interrupt(self):
        """A failed capture never counts as a clear frame or preserves a streak."""
        self.recovery_streak = 0
        self.abnormal_streak = 0
        self.observation = "unavailable"
        self.state = "blocked" if self.active else "unavailable"

    def snapshot(self) -> dict:
        return {"state": self.state, "observation": self.observation, "active": self.active,
                "recovery_samples": self.recovery_samples, "recovery_streak": self.recovery_streak,
                "abnormal_streak": self.abnormal_streak, "episode": deepcopy(self.episode)}
