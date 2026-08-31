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

    def publish_reports(
        self, *, run_date: str, report: str, html_report: str, update_latest: bool = True
    ) -> None:
        payloads = {
            self.root / "reports" / f"{run_date}.md": report,
            self.root / "reports" / f"{run_date}.html": html_report,
        }
        if update_latest:
            payloads[self.root / "reports" / "latest.md"] = report
            payloads[self.root / "reports" / "latest.html"] = html_report
        self._replace_group(payloads)

    @staticmethod
    def _replace_group(payloads: dict[Path, str]) -> None:
        originals: dict[Path, bytes | None] = {}
        modes: dict[Path, int] = {}
        staged: dict[Path, Path] = {}
        try:
            for target, content in payloads.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                originals[target] = target.read_bytes() if target.exists() else None
                modes[target] = target.stat().st_mode & 0o777 if target.exists() else 0o644
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
                os.chmod(staged[target], modes[target])
            for target, staged_path in staged.items():
                os.replace(staged_path, target)
        except Exception as error:
            AtomicPublisher._restore(originals, modes)
            raise PublishError("failed to publish validated artifacts") from error
        finally:
            for staged_path in staged.values():
                staged_path.unlink(missing_ok=True)

    @staticmethod
    def _restore(originals: dict[Path, bytes | None], modes: dict[Path, int]) -> None:
        for target, content in originals.items():
            try:
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    restore_path: Path | None = None
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, delete=False
                    ) as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                        restore_path = Path(handle.name)
                    os.chmod(restore_path, modes[target])
                    os.replace(restore_path, target)
            except OSError:
                # Preserve the original publishing error; recovery is best effort.
                pass
            finally:
                if content is not None and restore_path is not None:
                    restore_path.unlink(missing_ok=True)
