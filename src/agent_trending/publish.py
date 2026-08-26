from __future__ import annotations

import os
import tempfile
from pathlib import Path


class PublishError(RuntimeError):
    """Raised when validated artifacts cannot be atomically promoted."""


class AtomicPublisher:
    def __init__(self, root: Path) -> None:
        self.root = root

    def publish_daily(
        self, *, run_date: str, snapshot_json: str, report: str, html_report: str
    ) -> None:
        self._replace_group(
            {
                self.root / "data" / f"{run_date}.json": snapshot_json,
                self.root / "reports" / f"{run_date}.md": report,
                self.root / "reports" / "latest.md": report,
                self.root / "reports" / f"{run_date}.html": html_report,
                self.root / "reports" / "latest.html": html_report,
            }
        )

    def publish_reports(self, *, run_date: str, report: str, html_report: str) -> None:
        self._replace_group(
            {
                self.root / "reports" / f"{run_date}.md": report,
                self.root / "reports" / "latest.md": report,
                self.root / "reports" / f"{run_date}.html": html_report,
                self.root / "reports" / "latest.html": html_report,
            }
        )

    @staticmethod
    def _replace_group(payloads: dict[Path, str]) -> None:
        originals: dict[Path, bytes | None] = {}
        staged: dict[Path, Path] = {}
        try:
            for target, content in payloads.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                originals[target] = target.read_bytes() if target.exists() else None
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged[target] = Path(handle.name)
            for target, staged_path in staged.items():
                os.replace(staged_path, target)
        except Exception as error:
            AtomicPublisher._restore(originals)
            raise PublishError("failed to publish validated artifacts") from error
        finally:
            for staged_path in staged.values():
                staged_path.unlink(missing_ok=True)

    @staticmethod
    def _restore(originals: dict[Path, bytes | None]) -> None:
        for target, content in originals.items():
            try:
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, delete=False
                    ) as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                        restore_path = Path(handle.name)
                    os.replace(restore_path, target)
            except OSError:
                # Preserve the original publishing error; recovery is best effort.
                pass
