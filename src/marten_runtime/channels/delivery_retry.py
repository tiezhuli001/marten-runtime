from pydantic import BaseModel


class DeliveryRetryPolicy(BaseModel):
    progress_max_retries: int = 2
    final_max_retries: int = 5
    error_max_retries: int = 5
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0

    def retry_limit_for(self, event_type: str) -> int:
        if event_type == "progress":
            return self.progress_max_retries
        if event_type == "error":
            return self.error_max_retries
        return self.final_max_retries

    def backoff_for(self, retry_count: int) -> float:
        return min(self.base_backoff_seconds * (2 ** max(retry_count - 1, 0)), self.max_backoff_seconds)
