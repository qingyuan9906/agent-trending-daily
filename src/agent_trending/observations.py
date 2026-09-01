from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_trending.models import DailyObservation, DailySnapshot, TrendingRepository
from agent_trending.publish import AtomicPublisher
from agent_trending.sources import TRENDING_URL


class ObservationError(RuntimeError):
    """Raised when a complete weekly observation window is unavailable."""


class ObservationStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "data" / "observations"

    def collect(
        self,
        repositories: list[TrendingRepository],
        *,
        now: datetime,
        dry_run: bool = False,
    ) -> DailyObservation:
        if now.tzinfo is None:
            raise ValueError("observation clock must be timezone-aware")
        local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
        observation = DailyObservation(
            schema_version=1,
            observed_date=local_now.date().isoformat(),
            generated_at=local_now.isoformat(timespec="seconds"),
            timezone="Asia/Shanghai",
            source_url=TRENDING_URL,
            repositories=repositories,
        )
        payload = json.dumps(
            observation.model_dump(mode="json"), ensure_ascii=False, indent=2
        ) + "\n"
        DailyObservation.model_validate_json(payload, strict=True)
        if not dry_run:
            AtomicPublisher(self.root).publish_observation(
                observed_date=observation.observed_date,
                snapshot_json=payload,
            )
        return observation

    def load_period(self, period_start: date, period_end: date) -> list[DailyObservation]:
        if period_end - period_start != timedelta(days=6):
            raise ValueError("observation period must contain seven days")
        observations: list[DailyObservation] = []
        missing: list[str] = []
        current = period_start
        while current <= period_end:
            observation = self._load_date(current)
            if observation is None:
                missing.append(current.isoformat())
            else:
                observations.append(observation)
            current += timedelta(days=1)
        if missing:
            raise ObservationError("missing daily observations: " + ", ".join(missing))
        return observations

    def _load_date(self, observed_date: date) -> DailyObservation | None:
        path = self.directory / f"{observed_date.isoformat()}.json"
        try:
            return DailyObservation.model_validate_json(
                path.read_text(encoding="utf-8"), strict=True
            )
        except FileNotFoundError:
            return self._from_legacy_snapshot(observed_date)
        except (OSError, ValueError) as error:
            raise ObservationError(f"invalid daily observation: {path}") from error

    def _from_legacy_snapshot(self, observed_date: date) -> DailyObservation | None:
        path = self.root / "data" / f"{observed_date.isoformat()}.json"
        if not path.exists():
            return None
        try:
            snapshot = DailySnapshot.model_validate_json(
                path.read_text(encoding="utf-8"), strict=True
            )
        except (OSError, ValueError) as error:
            raise ObservationError(f"invalid legacy daily snapshot: {path}") from error
        repositories = [
            TrendingRepository(
                rank=candidate.repository.rank,
                full_name=candidate.repository.full_name,
                url=candidate.repository.url,
                page_description=candidate.repository.description,
                language=candidate.repository.language,
                stars_today=candidate.repository.stars_today,
            )
            for candidate in snapshot.candidates
        ]
        return DailyObservation(
            schema_version=1,
            observed_date=snapshot.run_date,
            generated_at=snapshot.generated_at,
            timezone="Asia/Shanghai",
            source_url=TRENDING_URL,
            repositories=repositories,
        )

    def history_metrics(
        self, full_names: list[str], period_end: date
    ) -> dict[str, tuple[str, int]]:
        dates: set[date] = set()
        for path in self.directory.glob("????-??-??.json"):
            dates.add(date.fromisoformat(path.stem))
        for path in (self.root / "data").glob("????-??-??.json"):
            dates.add(date.fromisoformat(path.stem))
        observations = {
            observed_date: self._load_date(observed_date)
            for observed_date in dates
            if observed_date <= period_end
        }
        members = {
            observed_date: {
                repository.full_name.casefold() for repository in observation.repositories
            }
            for observed_date, observation in observations.items()
            if observation is not None
        }
        metrics: dict[str, tuple[str, int]] = {}
        for full_name in full_names:
            key = full_name.casefold()
            seen_dates = sorted(day for day, names in members.items() if key in names)
            first_seen = seen_dates[0].isoformat() if seen_dates else period_end.isoformat()
            consecutive = 0
            cursor = period_end
            while key in members.get(cursor, set()):
                consecutive += 1
                cursor -= timedelta(days=1)
            metrics[key] = (first_seen, consecutive)
        return metrics
