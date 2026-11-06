"""SQLite-backed Persistent Experiment Storage Engine.

Persists historical experiment and benchmark runs across server restarts,
supporting genuine comparative evaluation by architecture, task, and persona.
Enhanced with production-grade durability: Write-Ahead Logging (WAL),
busy timeout, safe transaction isolation, and explicit connection lifecycle management.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Generator

from config.settings import settings
from core.schemas.metrics import PerformanceMetrics


class ExperimentStorage:
    """Thread-safe SQLite storage for experiment and benchmark metrics."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or settings.EXPERIMENTS_DB_PATH).resolve()
        self._lock = threading.RLock()
        self._init_db()

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        """Applies durability and concurrency PRAGMA directives to a SQLite connection."""
        conn.row_factory = sqlite3.Row
        # Set busy timeout in milliseconds to gracefully handle concurrent access
        conn.execute("PRAGMA busy_timeout = 5000;")
        # Enable Write-Ahead Logging (WAL) for non-blocking concurrent reads and writes
        conn.execute("PRAGMA journal_mode = WAL;")
        # Synchronous NORMAL provides high performance while maintaining integrity in WAL mode
        conn.execute("PRAGMA synchronous = NORMAL;")
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")

    def _get_connection(self) -> sqlite3.Connection:
        """Creates and configures a SQLite connection with durability settings."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        self._configure_connection(conn)
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a managed read-only or standalone connection with guaranteed lifecycle closure."""
        conn = self._get_connection()
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides an atomic transaction context with automatic commit/rollback and connection closure."""
        conn = self._get_connection()
        try:
            with conn:
                yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_journal_mode(self) -> str:
        """Returns the active SQLite journal mode (e.g. 'wal')."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute("PRAGMA journal_mode;")
                return str(cur.fetchone()[0]).lower()

    def get_busy_timeout(self) -> int:
        """Returns the active SQLite busy timeout in milliseconds."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute("PRAGMA busy_timeout;")
                return int(cur.fetchone()[0])

    def _init_db(self) -> None:
        """Initializes tables and indexes without modifying or overwriting existing data."""
        with self._lock:
            with self.transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS experiments (
                        run_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        architecture_pattern TEXT NOT NULL,
                        benchmark_task TEXT NOT NULL,
                        persona TEXT NOT NULL,
                        execution_status TEXT NOT NULL,
                        tests_passed INTEGER NOT NULL DEFAULT 0,
                        tests_total INTEGER NOT NULL DEFAULT 0,
                        test_pass_rate REAL NOT NULL DEFAULT 0.0,
                        success INTEGER NOT NULL DEFAULT 0,
                        execution_time_seconds REAL NOT NULL DEFAULT 0.0,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                        model_name TEXT NOT NULL DEFAULT 'gemini-3.8-flash',
                        tool_call_count INTEGER NOT NULL DEFAULT 0,
                        a2a_message_count INTEGER NOT NULL DEFAULT 0,
                        failure_recovery_cycles INTEGER NOT NULL DEFAULT 0,
                        is_measurement_estimated INTEGER NOT NULL DEFAULT 0,
                        error_details TEXT,
                        metadata_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pull_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        pr_number INTEGER NOT NULL,
                        pr_url TEXT NOT NULL,
                        repo_url TEXT NOT NULL,
                        base_branch TEXT NOT NULL,
                        head_branch TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'open',
                        created_at TEXT NOT NULL,
                        metadata_json TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_arch ON experiments(architecture_pattern)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_persona ON experiments(persona)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_task ON experiments(benchmark_task)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_timestamp ON experiments(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_run_id ON pull_requests(run_id)")

    def record_run(
        self,
        metrics: PerformanceMetrics,
        benchmark_task: Optional[str] = None,
        persona: Optional[str] = None,
        execution_status: str = "completed",
        error_details: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Saves a real experiment execution record into SQLite with atomic commit."""
        task_str = benchmark_task or metrics.benchmark_task or "Unspecified Task"
        persona_str = persona or metrics.persona or "Balanced-Engineer"
        ts = metrics.completed_at.isoformat() if metrics.completed_at else datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {}, default=str)

        with self._lock:
            with self.transaction() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO experiments (
                        run_id, timestamp, architecture_pattern, benchmark_task, persona,
                        execution_status, tests_passed, tests_total, test_pass_rate, success,
                        execution_time_seconds, prompt_tokens, completion_tokens, total_tokens,
                        estimated_cost_usd, model_name, tool_call_count, a2a_message_count,
                        failure_recovery_cycles, is_measurement_estimated, error_details, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metrics.run_id,
                        ts,
                        metrics.architecture_pattern,
                        task_str,
                        persona_str,
                        execution_status,
                        metrics.tests_passed,
                        metrics.tests_total,
                        metrics.test_pass_rate_percentage,
                        1 if metrics.success else 0,
                        metrics.total_execution_time_seconds,
                        metrics.total_prompt_tokens,
                        metrics.total_completion_tokens,
                        metrics.total_tokens,
                        metrics.total_cost_usd,
                        metrics.model_name,
                        metrics.tool_call_count,
                        metrics.a2a_message_count,
                        metrics.failure_recovery_cycles,
                        1 if metrics.is_measurement_estimated else 0,
                        error_details or metrics.error_details,
                        meta_json,
                    ),
                )

    def count(self) -> int:
        """Returns total count of genuine recorded experiments."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM experiments")
                return cur.fetchone()[0]

    def get_all(
        self,
        architecture: Optional[str] = None,
        persona: Optional[str] = None,
        task: Optional[str] = None,
        success_only: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Queries historical records with optional filtering."""
        query = "SELECT * FROM experiments WHERE 1=1"
        params: List[Any] = []

        if architecture:
            query += " AND architecture_pattern = ?"
            params.append(architecture)
        if persona:
            query += " AND persona = ?"
            params.append(persona)
        if task:
            query += " AND benchmark_task LIKE ?"
            params.append(f"%{task}%")
        if success_only is not None:
            query += " AND success = ?"
            params.append(1 if success_only else 0)

        query += " ORDER BY timestamp DESC"
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"

        with self._lock:
            with self.connection() as conn:
                cur = conn.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def get_recent_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves most recent experiment records ordered by timestamp descending."""
        return self.get_all(limit=limit)

    def get_by_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single experiment record by ID."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute("SELECT * FROM experiments WHERE run_id = ?", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_summary_statistics(self) -> Dict[str, Any]:
        """Calculates global aggregate metrics across all historical runs."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute(
                    """
                    SELECT 
                        COUNT(*) as total_runs,
                        COALESCE(SUM(success), 0) as successful_runs,
                        COALESCE(AVG(execution_time_seconds), 0.0) as avg_time,
                        COALESCE(AVG(total_tokens), 0.0) as avg_tokens,
                        COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost,
                        COALESCE(AVG(test_pass_rate), 0.0) as avg_pass_rate
                    FROM experiments
                    """
                )
                row = cur.fetchone()
                total = row["total_runs"]
                success_rate = (row["successful_runs"] / total * 100.0) if total > 0 else 0.0

                return {
                    "total_runs": total,
                    "successful_runs": row["successful_runs"],
                    "failed_runs": total - row["successful_runs"],
                    "success_rate_percentage": round(success_rate, 2),
                    "avg_execution_time_seconds": round(row["avg_time"], 2),
                    "avg_total_tokens": int(row["avg_tokens"]),
                    "total_cost_usd": round(row["total_cost"], 6),
                    "avg_test_pass_rate_percentage": round(row["avg_pass_rate"], 2),
                }

    def get_architecture_comparison(self) -> List[Dict[str, Any]]:
        """Computes summary statistics grouped by Architecture Pattern."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute(
                    """
                    SELECT 
                        architecture_pattern,
                        COUNT(*) as runs,
                        COALESCE(SUM(success), 0) as passed_runs,
                        ROUND(COALESCE(SUM(success), 0) * 100.0 / COUNT(*), 2) as success_rate,
                        ROUND(AVG(execution_time_seconds), 2) as avg_time_sec,
                        CAST(ROUND(AVG(total_tokens)) AS INTEGER) as avg_tokens,
                        ROUND(AVG(estimated_cost_usd), 6) as avg_cost_usd,
                        ROUND(AVG(test_pass_rate), 2) as avg_pass_rate,
                        CAST(ROUND(AVG(a2a_message_count)) AS INTEGER) as avg_a2a_messages,
                        CAST(ROUND(AVG(tool_call_count)) AS INTEGER) as avg_tool_calls
                    FROM experiments
                    GROUP BY architecture_pattern
                    ORDER BY success_rate DESC, avg_time_sec ASC
                    """
                )
                return [dict(row) for row in cur.fetchall()]

    def get_persona_comparison(self) -> List[Dict[str, Any]]:
        """Computes summary statistics grouped by Persona Configuration."""
        with self._lock:
            with self.connection() as conn:
                cur = conn.execute(
                    """
                    SELECT 
                        persona,
                        COUNT(*) as runs,
                        COALESCE(SUM(success), 0) as passed_runs,
                        ROUND(COALESCE(SUM(success), 0) * 100.0 / COUNT(*), 2) as success_rate,
                        ROUND(AVG(execution_time_seconds), 2) as avg_time_sec,
                        CAST(ROUND(AVG(total_tokens)) AS INTEGER) as avg_tokens,
                        ROUND(AVG(estimated_cost_usd), 6) as avg_cost_usd,
                        ROUND(AVG(test_pass_rate), 2) as avg_pass_rate
                    FROM experiments
                    GROUP BY persona
                    ORDER BY success_rate DESC
                    """
                )
                return [dict(row) for row in cur.fetchall()]

    def export_to_csv(self, filepath: Union[str, Path]) -> Path:
        """Exports all genuine experiment records to a CSV file."""
        import csv
        path = Path(filepath).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        runs = self.get_all()
        if not runs:
            fieldnames = [
                "run_id", "timestamp", "architecture_pattern", "benchmark_task", "persona",
                "execution_status", "tests_passed", "tests_total", "test_pass_rate", "success",
                "execution_time_seconds", "prompt_tokens", "completion_tokens", "total_tokens",
                "estimated_cost_usd", "model_name", "tool_call_count", "a2a_message_count",
                "failure_recovery_cycles", "is_measurement_estimated", "error_details", "metadata_json"
            ]
        else:
            fieldnames = list(runs[0].keys())

        with self._lock:
            with open(path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in runs:
                    writer.writerow(r)
        return path

    def export_to_json(self, filepath: Union[str, Path]) -> Path:
        """Exports all genuine experiment records to a JSON file."""
        path = Path(filepath).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        runs = self.get_all()
        with self._lock:
            path.write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")
        return path

    def record_pull_request(
        self,
        run_id: str,
        pr_number: int,
        pr_url: str,
        repo_url: str,
        base_branch: str,
        head_branch: str,
        title: str,
        status: str = "open",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stores a published Pull Request record in SQLite with atomic commit."""
        created_at = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {}, default=str)
        with self._lock:
            with self.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO pull_requests (
                        run_id, pr_number, pr_url, repo_url, base_branch, head_branch, title, status, created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, pr_number, pr_url, repo_url, base_branch, head_branch, title, status, created_at, meta_json),
                )

    def get_pull_requests(self, run_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves stored Pull Request records."""
        with self._lock:
            with self.connection() as conn:
                if run_id:
                    cursor = conn.execute(
                        "SELECT * FROM pull_requests WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                        (run_id, limit),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM pull_requests ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    if d.get("metadata_json"):
                        try:
                            d["metadata"] = json.loads(d["metadata_json"])
                        except Exception:
                            d["metadata"] = {}
                    results.append(d)
                return results

    def clear(self) -> None:
        """Clears all records (used for test setup/teardown)."""
        with self._lock:
            with self.transaction() as conn:
                conn.execute("DELETE FROM experiments")


# Global Singleton Storage Instance
experiment_storage = ExperimentStorage()
