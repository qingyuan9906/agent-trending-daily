from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from agent_trending.models import CandidateRecord, DailySnapshot


class HistoryError(RuntimeError):
    """Raised when a committed historical snapshot is invalid."""


class HistoryIndex:
    def __init__(
        self,
        *,
        earliest_by_repository: dict[str, str],
        previous_included: dict[str, CandidateRecord],
    ) -> None:
        self.earliest_by_repository = earliest_by_repository
        self.previous_included = previous_included

    @classmethod
    def load(cls, data_dir: Path, run_date: date) -> HistoryIndex:
        earliest: dict[str, str] = {}
        previous: dict[str, CandidateRecord] = {}
        previous_date = (run_date - timedelta(days=1)).isoformat()
        for path in sorted(data_dir.glob("????-??-??.json")):
            if path.stem >= run_date.isoformat():
                continue
            try:
                snapshot = DailySnapshot.model_validate_json(
                    path.read_text(encoding="utf-8"), strict=True
                )
            except (OSError, ValueError) as error:
                raise HistoryError(f"invalid historical snapshot: {path}") from error
            for candidate in snapshot.candidates:
                if not candidate.included:
                    continue
                full_name = candidate.repository.full_name.casefold()
                first_seen = candidate.first_seen_date or snapshot.run_date
                earliest[full_name] = min(earliest.get(full_name, first_seen), first_seen)
                if snapshot.run_date == previous_date:
                    previous[full_name] = candidate
        return cls(earliest_by_repository=earliest, previous_included=previous)

    def active_history(self, full_name: str, run_date: date) -> tuple[str, int]:
        key = full_name.casefold()
        first_seen = self.earliest_by_repository.get(key, run_date.isoformat())
        previous = self.previous_included.get(key)
        consecutive_days = previous.consecutive_days + 1 if previous else 1
        return first_seen, consecutive_days
