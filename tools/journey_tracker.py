"""Journey/Goal 目标追踪系统 — 长期目标旅程管理。

支持创建 Journey（旅程）、Goal（目标）、Milestone（里程碑）和 Checkpoint（检查点），
提供统计分析、热力图、周报等功能。

Usage::

    from tools.journey_tracker import JourneyTracker, GoalStatus, Priority

    tracker = JourneyTracker()
    journey = tracker.create_journey("成为 Python 专家", tags=["python", "学习"])
    goal = tracker.create_goal("掌握 async/await", journey_id=journey.id, priority=Priority.HIGH)
    tracker.add_checkpoint(goal.id, "完成了 asyncio 基础学习")
    tracker.complete_goal(goal.id, reflection="async/await 已掌握，继续深入")
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from tools.base import tool

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".Zeloo" / "goals.db"

_TODO_LIST = None
_TODO_LOCK = threading.RLock()


class GoalStatus(Enum):
    """目标状态枚举。"""

    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ABANDONED = "abandoned"


class Priority(Enum):
    """优先级枚举。"""

    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


@dataclass
class Checkpoint:
    """检查点 — 记录目标进展的快照。"""

    id: str
    goal_id: str
    content: str
    created_at: datetime
    tags: list[str] = field(default_factory=list)
    reflection: str | None = None


@dataclass
class Goal:
    """目标 — Journey 中的具体目标。"""

    id: str
    title: str
    description: str
    status: GoalStatus
    priority: Priority
    journey_id: str | None
    parent_goal_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    deadline: datetime | None
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[Checkpoint] = field(default_factory=list)


@dataclass
class Journey:
    """旅程 — 长期目标的容器。"""

    id: str
    name: str
    description: str
    goals: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: list[str] = field(default_factory=list)
    progress: float = 0.0


class JourneyTracker:
    """Journey/Goal 追踪器核心类。

    提供 Journey、Goal、Checkpoint 的 CRUD 操作，以及统计分析和视图渲染功能。
    数据持久化到 SQLite 数据库。

    Args:
        db_path: SQLite 数据库路径，默认为 ~/.Zeloo/goals.db
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """初始化追踪器。"""
        self._db_path = db_path or _DB_PATH
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构。"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS journeys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                goals TEXT DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tags TEXT DEFAULT '[]',
                progress REAL DEFAULT 0.0
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                journey_id TEXT,
                parent_goal_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                deadline REAL,
                tags TEXT DEFAULT '[]',
                metrics TEXT DEFAULT '{}',
                FOREIGN KEY (journey_id) REFERENCES journeys(id) ON DELETE SET NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                tags TEXT DEFAULT '[]',
                reflection TEXT,
                FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_journey ON goals(journey_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_goal ON checkpoints(goal_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at)")
        self._conn.commit()

    def _parse_datetime(self, timestamp: float | None) -> datetime | None:
        """将 Unix 时间戳转换为 datetime 对象。"""
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp)

    def _parse_goal(self, row: tuple[Any, ...]) -> Goal:
        """将数据库行解析为 Goal 对象。"""
        (
            id_, title, description, status, priority,
            journey_id, parent_goal_id,
            created_at, updated_at, completed_at, deadline,
            tags, metrics
        ) = row

        checkpoint_rows = self._conn.execute(
            """
            SELECT id, goal_id, content, created_at, tags, reflection
            FROM checkpoints WHERE goal_id = ? ORDER BY created_at
            """,
            (id_,)
        ).fetchall()

        checkpoints = []
        for cp_row in checkpoint_rows:
            cp_id, cp_goal_id, cp_content, cp_created, cp_tags, cp_reflection = cp_row
            checkpoints.append(Checkpoint(
                id=cp_id,
                goal_id=cp_goal_id,
                content=cp_content,
                created_at=self._parse_datetime(cp_created),
                tags=json.loads(cp_tags) if cp_tags else [],
                reflection=cp_reflection,
            ))

        return Goal(
            id=id_,
            title=title,
            description=description or "",
            status=GoalStatus(status),
            priority=Priority(priority),
            journey_id=journey_id,
            parent_goal_id=parent_goal_id,
            created_at=self._parse_datetime(created_at),
            updated_at=self._parse_datetime(updated_at),
            completed_at=self._parse_datetime(completed_at),
            deadline=self._parse_datetime(deadline),
            tags=json.loads(tags) if tags else [],
            metrics=json.loads(metrics) if metrics else {},
            checkpoints=checkpoints,
        )

    def _parse_journey(self, row: tuple[Any, ...]) -> Journey:
        """将数据库行解析为 Journey 对象。"""
        id_, name, description, goals_str, created_at, updated_at, tags, progress = row
        return Journey(
            id=id_,
            name=name,
            description=description or "",
            goals=json.loads(goals_str) if goals_str else [],
            created_at=self._parse_datetime(created_at) or datetime.now(),
            updated_at=self._parse_datetime(updated_at) or datetime.now(),
            tags=json.loads(tags) if tags else [],
            progress=progress or 0.0,
        )

    # ------------------------------------------------------------------
    # Journey CRUD
    # ------------------------------------------------------------------

    def create_journey(
        self,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Journey:
        """创建新的旅程。

        Args:
            name: 旅程名称。
            description: 旅程描述。
            tags: 标签列表。

        Returns:
            创建的 Journey 对象。
        """
        journey_id = str(uuid.uuid4())
        now = datetime.now()
        now_ts = now.timestamp()

        with self._lock:
            self._conn.execute(
                """INSERT INTO journeys (id, name, description, goals, created_at, updated_at, tags, progress)
                   VALUES (?, ?, ?, '[]', ?, ?, ?, 0.0)""",
                (journey_id, name, description, now_ts, now_ts, json.dumps(tags or [])),
            )
            self._conn.commit()

        return Journey(
            id=journey_id,
            name=name,
            description=description,
            goals=[],
            created_at=now,
            updated_at=now,
            tags=tags or [],
            progress=0.0,
        )

    def get_journey(self, journey_id: str) -> Journey | None:
        """获取旅程。

        Args:
            journey_id: 旅程 ID。

        Returns:
            Journey 对象或 None。
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, name, description, goals, created_at, updated_at, tags, progress
                FROM journeys WHERE id = ?
                """,
                (journey_id,),
            ).fetchone()

            if row is None:
                return None

            journey = self._parse_journey(row)
            journey.goals = [g for g in journey.goals if self.get_goal(g) is not None]
            return journey

    def list_journeys(
        self,
        status: GoalStatus | None = None,
        tags: list[str] | None = None,
    ) -> list[Journey]:
        """列出所有旅程。

        Args:
            status: 按目标状态过滤（如果有目标处于该状态则包含）。
            tags: 按标签过滤。

        Returns:
            Journey 对象列表。
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name, description, goals, created_at, updated_at, tags, progress
                FROM journeys ORDER BY updated_at DESC
                """
            ).fetchall()

        journeys = [self._parse_journey(row) for row in rows]

        if status is not None:
            journeys = [
                j for j in journeys
                if any(self.get_goal(g) and self.get_goal(g).status == status for g in j.goals)
            ]

        if tags:
            journeys = [
                j for j in journeys
                if any(t in j.tags for t in tags)
            ]

        return journeys

    def update_journey(self, journey_id: str, **kwargs: Any) -> Journey:
        """更新旅程。

        Args:
            journey_id: 旅程 ID。
            **kwargs: 要更新的字段（name, description, tags, progress）。

        Returns:
            更新后的 Journey 对象。
        """
        with self._lock:
            journey = self.get_journey(journey_id)
            if journey is None:
                raise ValueError(f"Journey '{journey_id}' not found")

            now_ts = datetime.now().timestamp()

            if "name" in kwargs:
                journey.name = kwargs["name"]
            if "description" in kwargs:
                journey.description = kwargs["description"]
            if "tags" in kwargs:
                journey.tags = kwargs["tags"]
            if "progress" in kwargs:
                journey.progress = kwargs["progress"]

            self._conn.execute(
                """UPDATE journeys SET name=?, description=?, tags=?, progress=?, updated_at=?
                   WHERE id=?""",
                (journey.name, journey.description, json.dumps(journey.tags),
                 journey.progress, now_ts, journey_id),
            )
            self._conn.commit()
            journey.updated_at = datetime.now()
            return journey

    def delete_journey(self, journey_id: str) -> bool:
        """删除旅程。

        Args:
            journey_id: 旅程 ID。

        Returns:
            是否删除成功。
        """
        with self._lock:
            self._conn.execute("DELETE FROM journeys WHERE id = ?", (journey_id,))
            self._conn.commit()
            return True

    def calculate_journey_progress(self, journey_id: str) -> float:
        """计算旅程进度。

        Args:
            journey_id: 旅程 ID。

        Returns:
            0.0 - 1.0 的进度值。
        """
        journey = self.get_journey(journey_id)
        if journey is None or not journey.goals:
            return 0.0

        completed = sum(
            1 for g in journey.goals
            if self.get_goal(g) and self.get_goal(g).status == GoalStatus.COMPLETED
        )
        return completed / len(journey.goals)

    # ------------------------------------------------------------------
    # Goal CRUD
    # ------------------------------------------------------------------

    def create_goal(
        self,
        title: str,
        description: str = "",
        journey_id: str | None = None,
        parent_goal_id: str | None = None,
        priority: Priority = Priority.MEDIUM,
        deadline: datetime | None = None,
        tags: list[str] | None = None,
    ) -> Goal:
        """创建目标。

        Args:
            title: 目标标题。
            description: 目标描述。
            journey_id: 所属旅程 ID。
            parent_goal_id: 父目标 ID（用于子目标/里程碑）。
            priority: 优先级。
            deadline: 截止日期。
            tags: 标签列表。

        Returns:
            创建的 Goal 对象。
        """
        goal_id = str(uuid.uuid4())
        now = datetime.now()
        now_ts = now.timestamp()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO goals (
                    id, title, description, status, priority, journey_id, parent_goal_id,
                    created_at, updated_at, completed_at, deadline, tags, metrics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, '{}')
                """,
                (goal_id, title, description, GoalStatus.ACTIVE.value, priority.value,
                 journey_id, parent_goal_id, now_ts, now_ts,
                 deadline.timestamp() if deadline else None, json.dumps(tags or [])),
            )

            if journey_id:
                journey = self.get_journey(journey_id)
                if journey:
                    goals = list(journey.goals)
                    goals.append(goal_id)
                    self._conn.execute(
                        "UPDATE journeys SET goals=?, updated_at=? WHERE id=?",
                        (json.dumps(goals), now_ts, journey_id),
                    )

            self._conn.commit()

        return Goal(
            id=goal_id,
            title=title,
            description=description,
            status=GoalStatus.ACTIVE,
            priority=priority,
            journey_id=journey_id,
            parent_goal_id=parent_goal_id,
            created_at=now,
            updated_at=now,
            completed_at=None,
            deadline=deadline,
            tags=tags or [],
            metrics={},
            checkpoints=[],
        )

    def get_goal(self, goal_id: str) -> Goal | None:
        """获取目标。

        Args:
            goal_id: 目标 ID。

        Returns:
            Goal 对象或 None。
        """
        with self._lock:
            row = self._conn.execute(
                """SELECT id, title, description, status, priority, journey_id, parent_goal_id,
                          created_at, updated_at, completed_at, deadline, tags, metrics
                   FROM goals WHERE id = ?""",
                (goal_id,),
            ).fetchone()

            if row is None:
                return None

            return self._parse_goal(row)

    def list_goals(
        self,
        journey_id: str | None = None,
        status: GoalStatus | None = None,
        priority: Priority | None = None,
    ) -> list[Goal]:
        """列出目标。

        Args:
            journey_id: 按旅程过滤。
            status: 按状态过滤。
            priority: 按优先级过滤。

        Returns:
            Goal 对象列表。
        """
        query = """SELECT id, title, description, status, priority, journey_id, parent_goal_id,
                          created_at, updated_at, completed_at, deadline, tags, metrics FROM goals WHERE 1=1"""
        params: list[Any] = []

        if journey_id is not None:
            query += " AND journey_id = ?"
            params.append(journey_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if priority is not None:
            query += " AND priority = ?"
            params.append(priority.value)

        query += " ORDER BY created_at DESC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()

        return [self._parse_goal(row) for row in rows]

    def update_goal(self, goal_id: str, **kwargs: Any) -> Goal:
        """更新目标。

        Args:
            goal_id: 目标 ID。
            **kwargs: 要更新的字段。

        Returns:
            更新后的 Goal 对象。
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal '{goal_id}' not found")

        now_ts = datetime.now().timestamp()
        updates: list[str] = []
        params: list[Any] = []

        for key in ["title", "description", "priority", "deadline", "tags", "metrics"]:
            if key in kwargs:
                value = kwargs[key]
                if key == "priority":
                    value = value.value if isinstance(value, Priority) else value
                    updates.append(f"{key} = ?")
                    params.append(value)
                elif key in ("tags", "metrics"):
                    updates.append(f"{key} = ?")
                    params.append(json.dumps(value))
                else:
                    updates.append(f"{key} = ?")
                    params.append(value)

        if updates:
            updates.append("updated_at = ?")
            params.append(now_ts)
            params.append(goal_id)

            with self._lock:
                self._conn.execute(
                    f"UPDATE goals SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                self._conn.commit()

        return self.get_goal(goal_id)

    def delete_goal(self, goal_id: str) -> bool:
        """删除目标。

        Args:
            goal_id: 目标 ID。

        Returns:
            是否删除成功。
        """
        with self._lock:
            goal = self.get_goal(goal_id)
            if goal and goal.journey_id:
                journey = self.get_journey(goal.journey_id)
                if journey and goal_id in journey.goals:
                    goals = [g for g in journey.goals if g != goal_id]
                    self._conn.execute(
                        "UPDATE journeys SET goals=?, updated_at=? WHERE id=?",
                        (json.dumps(goals), datetime.now().timestamp(), goal.journey_id),
                    )

            self._conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
            self._conn.commit()
            return True

    def complete_goal(self, goal_id: str, reflection: str | None = None) -> Goal:
        """完成目标。

        Args:
            goal_id: 目标 ID。
            reflection: 完成反思。

        Returns:
            更新后的 Goal 对象。
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal '{goal_id}' not found")

        now = datetime.now()
        now_ts = now.timestamp()

        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status=?, completed_at=?, updated_at=? WHERE id=?",
                (GoalStatus.COMPLETED.value, now_ts, now_ts, goal_id),
            )
            self._conn.commit()

            if reflection:
                self.add_checkpoint(goal_id, f"[Completed] {reflection}")

            if goal.journey_id:
                progress = self.calculate_journey_progress(goal.journey_id)
                self.update_journey(goal.journey_id, progress=progress)

        return self.get_goal(goal_id)

    def pause_goal(self, goal_id: str) -> Goal:
        """暂停目标。

        Args:
            goal_id: 目标 ID。

        Returns:
            更新后的 Goal 对象。
        """
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status=?, updated_at=? WHERE id=?",
                (GoalStatus.PAUSED.value, datetime.now().timestamp(), goal_id),
            )
            self._conn.commit()
        return self.get_goal(goal_id)

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def add_checkpoint(
        self,
        goal_id: str,
        content: str,
        tags: list[str] | None = None,
    ) -> Checkpoint:
        """添加检查点。

        Args:
            goal_id: 目标 ID。
            content: 检查点内容。
            tags: 标签列表。

        Returns:
            创建的 Checkpoint 对象。
        """
        checkpoint_id = str(uuid.uuid4())
        now = datetime.now()
        now_ts = now.timestamp()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO checkpoints (id, goal_id, content, created_at, tags, reflection)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (checkpoint_id, goal_id, content, now_ts, json.dumps(tags or [])),
            )
            self._conn.execute(
                "UPDATE goals SET updated_at=? WHERE id=?",
                (now_ts, goal_id),
            )
            self._conn.commit()

        return Checkpoint(
            id=checkpoint_id,
            goal_id=goal_id,
            content=content,
            created_at=now,
            tags=tags or [],
            reflection=None,
        )

    def list_checkpoints(self, goal_id: str) -> list[Checkpoint]:
        """列出检查点。

        Args:
            goal_id: 目标 ID。

        Returns:
            Checkpoint 对象列表。
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, goal_id, content, created_at, tags, reflection
                FROM checkpoints WHERE goal_id = ? ORDER BY created_at
                """,
                (goal_id,),
            ).fetchall()

        return [
            Checkpoint(
                id=row[0],
                goal_id=row[1],
                content=row[2],
                created_at=self._parse_datetime(row[3]),
                tags=json.loads(row[4]) if row[4] else [],
                reflection=row[5],
            )
            for row in rows
        ]

    def update_checkpoint(self, checkpoint_id: str, reflection: str) -> Checkpoint:
        """更新检查点反思。

        Args:
            checkpoint_id: 检查点 ID。
            reflection: 反思内容。

        Returns:
            更新后的 Checkpoint 对象。
        """
        with self._lock:
            self._conn.execute(
                "UPDATE checkpoints SET reflection=? WHERE id=?",
                (reflection, checkpoint_id),
            )
            self._conn.commit()

            row = self._conn.execute(
                "SELECT id, goal_id, content, created_at, tags, reflection FROM checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Checkpoint '{checkpoint_id}' not found")

            return Checkpoint(
                id=row[0],
                goal_id=row[1],
                content=row[2],
                created_at=self._parse_datetime(row[3]),
                tags=json.loads(row[4]) if row[4] else [],
                reflection=row[5],
            )

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息。

        Returns:
            包含各状态目标数量、优先级分布等统计数据的字典。
        """
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
            completed = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = ?", (GoalStatus.COMPLETED.value,)
            ).fetchone()[0]
            active = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = ?", (GoalStatus.ACTIVE.value,)
            ).fetchone()[0]
            paused = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = ?", (GoalStatus.PAUSED.value,)
            ).fetchone()[0]
            abandoned = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = ?", (GoalStatus.ABANDONED.value,)
            ).fetchone()[0]

            journey_count = self._conn.execute("SELECT COUNT(*) FROM journeys").fetchone()[0]

            priority_dist = {}
            for p in Priority:
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM goals WHERE priority = ?", (p.value,)
                ).fetchone()[0]
                priority_dist[p.name.lower()] = count

            return {
                "total_goals": total,
                "completed_goals": completed,
                "active_goals": active,
                "paused_goals": paused,
                "abandoned_goals": abandoned,
                "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
                "total_journeys": journey_count,
                "priority_distribution": priority_dist,
            }

    def get_heatmap_data(self, year: int) -> dict[str, int]:
        """获取热力图数据（类似 GitHub contributions）。

        Args:
            year: 年份。

        Returns:
            日期到完成目标数量的映射。
        """
        start_ts = datetime(year, 1, 1).timestamp()
        end_ts = datetime(year, 12, 31, 23, 59, 59).timestamp()

        with self._lock:
            rows = self._conn.execute(
                """SELECT completed_at FROM goals
                   WHERE completed_at >= ? AND completed_at <= ? AND completed_at IS NOT NULL""",
                (start_ts, end_ts),
            ).fetchall()

        heatmap: dict[str, int] = {}
        for row in rows:
            dt = self._parse_datetime(row[0])
            if dt:
                date_str = dt.strftime("%Y-%m-%d")
                heatmap[date_str] = heatmap.get(date_str, 0) + 1

        return heatmap

    def get_weekly_report(self) -> dict[str, Any]:
        """获取周报。

        Returns:
            本周统计数据和目标进展。
        """
        now = datetime.now()
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_ts = week_start.timestamp()

        with self._lock:
            completed_this_week = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE completed_at >= ?", (week_start_ts,)
            ).fetchone()[0]

            created_this_week = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE created_at >= ?", (week_start_ts,)
            ).fetchone()[0]

            active = self._conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = ?", (GoalStatus.ACTIVE.value,)
            ).fetchone()[0]

            recent_checkpoints = self._conn.execute(
                """SELECT id, goal_id, content, created_at, tags, reflection
                   FROM checkpoints WHERE created_at >= ? ORDER BY created_at DESC LIMIT 10""",
                (week_start_ts,),
            ).fetchall()

        checkpoints = [
            {
                "id": row[0],
                "goal_id": row[1],
                "content": row[2],
                "created_at": self._parse_datetime(row[3]).isoformat() if row[3] else None,
            }
            for row in recent_checkpoints
        ]

        return {
            "week_start": week_start.isoformat(),
            "completed_this_week": completed_this_week,
            "created_this_week": created_this_week,
            "active_goals": active,
            "recent_checkpoints": checkpoints,
        }

    def suggest_next_goals(self, count: int = 3) -> list[Goal]:
        """建议下一个目标。

        基于优先级和活跃状态推荐目标。

        Args:
            count: 返回数量。

        Returns:
            建议的目标列表。
        """
        goals = self.list_goals(status=GoalStatus.ACTIVE)

        sorted_goals = sorted(
            goals,
            key=lambda g: (
                g.priority.value,
                g.deadline.timestamp() if g.deadline else float("inf"),
            ),
        )

        return sorted_goals[:count]


class GoalsView:
    """目标视图渲染器。"""

    def __init__(self, tracker: JourneyTracker | None = None) -> None:
        """初始化视图。

        Args:
            tracker: JourneyTracker 实例。
        """
        self._tracker = tracker or JourneyTracker()

    def render_board(self, goals: list[Goal] | None = None, journey_id: str | None = None) -> str:
        """渲染看板视图。

        Args:
            goals: 目标列表，为空则从 tracker 获取。
            journey_id: 旅程 ID。

        Returns:
            格式化文本视图。
        """
        if goals is None:
            if journey_id:
                journey = self._tracker.get_journey(journey_id)
                if journey:
                    goals = [self._tracker.get_goal(g) for g in journey.goals]
                    goals = [g for g in goals if g is not None]
                else:
                    goals = []
            else:
                goals = self._tracker.list_goals()

        by_status: dict[GoalStatus, list[Goal]] = {s: [] for s in GoalStatus}
        for g in goals:
            by_status[g.status].append(g)

        lines = ["=" * 60, "  GOALS BOARD", "=" * 60, ""]

        for status in [GoalStatus.ACTIVE, GoalStatus.PAUSED, GoalStatus.COMPLETED, GoalStatus.ABANDONED]:
            status_goals = by_status[status]
            if status_goals:
                lines.append(f"[{status.value.upper()}] ({len(status_goals)})")
                lines.append("-" * 40)
                for g in sorted(status_goals, key=lambda x: x.priority.value):
                    deadline_str = f" | Due: {g.deadline.strftime('%Y-%m-%d')}" if g.deadline else ""
                    lines.append(f"  [{g.priority.name}] {g.title}{deadline_str}")
                    if g.checkpoints:
                        lines.append(f"    └─ {len(g.checkpoints)} checkpoint(s)")
                lines.append("")

        return "\n".join(lines)

    def render_timeline(self, goals: list[Goal] | None = None) -> str:
        """渲染时间线视图。

        Args:
            goals: 目标列表。

        Returns:
            格式化文本视图。
        """
        if goals is None:
            goals = self._tracker.list_goals()

        goals_sorted = sorted(goals, key=lambda g: g.created_at)

        lines = ["=" * 60, "  GOALS TIMELINE", "=" * 60, ""]

        for g in goals_sorted:
            status_icon = (
                "✓" if g.status == GoalStatus.COMPLETED
                else "○" if g.status == GoalStatus.ACTIVE
                else "⏸"
            )
            deadline_str = f" → {g.deadline.strftime('%Y-%m-%d')}" if g.deadline else ""
            lines.append(
                f"{status_icon} {g.created_at.strftime('%Y-%m-%d')} | "
                f"{g.title} [{g.status.value}]{deadline_str}"
            )

        lines.append("")
        return "\n".join(lines)

    def render_tree(self, journey_id: str) -> str:
        """渲染树形视图。

        Args:
            journey_id: 旅程 ID。

        Returns:
            格式化文本视图。
        """
        journey = self._tracker.get_journey(journey_id)
        if journey is None:
            return f"Journey '{journey_id}' not found"

        lines = ["=" * 60, f"  JOURNEY: {journey.name}", f"  Progress: {journey.progress * 100:.0f}%", "=" * 60, ""]

        def render_goal(goal: Goal, indent: int = 0) -> list[str]:
            prefix = "  " * indent
            status_icon = (
                "✓" if goal.status == GoalStatus.COMPLETED
                else "○" if goal.status == GoalStatus.ACTIVE
                else "⏸"
            )
            lines_g = [f"{prefix}{status_icon} {goal.title} [{goal.priority.name}]"]

            for cp in goal.checkpoints:
                lines_g.append(f"{prefix}  └─ {cp.created_at.strftime('%Y-%m-%d')}: {cp.content[:50]}...")

            child_goals = self._tracker.list_goals(status=None)
            for child in child_goals:
                if child.parent_goal_id == goal.id:
                    lines_g.extend(render_goal(child, indent + 1))

            return lines_g

        for goal_id in journey.goals:
            goal = self._tracker.get_goal(goal_id)
            if goal and goal.parent_goal_id is None:
                lines.extend(render_goal(goal))

        lines.append("")
        return "\n".join(lines)

    def render_summary(self) -> dict[str, Any]:
        """渲染摘要。

        Returns:
            摘要数据字典。
        """
        stats = self._tracker.get_stats()
        journeys = self._tracker.list_journeys()

        journey_summaries = []
        for j in journeys[:5]:
            journey_summaries.append({
                "id": j.id,
                "name": j.name,
                "goals_count": len(j.goals),
                "progress": f"{j.progress * 100:.0f}%",
            })

        return {
            "stats": stats,
            "recent_journeys": journey_summaries,
        }


# ------------------------------------------------------------------
# Global tracker instance
# ------------------------------------------------------------------

def _get_tracker() -> JourneyTracker:
    """获取全局追踪器实例。"""
    global _TODO_LIST
    with _TODO_LOCK:
        if _TODO_LIST is None:
            _TODO_LIST = JourneyTracker()
        return _TODO_LIST


# ------------------------------------------------------------------
# Tool functions
# ------------------------------------------------------------------

@tool(name="goals_create", description="Create a new goal", toolset="goals")
def create_goal(
    title: str,
    description: str = "",
    journey: str | None = None,
    priority: str = "medium",
) -> str:
    """创建新目标。

    Args:
        title: 目标标题。
        description: 目标描述。
        journey: 所属旅程 ID。
        priority: 优先级 (critical/high/medium/low)。
    """
    priority_map = {
        "critical": Priority.CRITICAL,
        "high": Priority.HIGH,
        "medium": Priority.MEDIUM,
        "low": Priority.LOW,
    }
    p = priority_map.get(priority.lower(), Priority.MEDIUM)

    tracker = _get_tracker()
    goal = tracker.create_goal(
        title=title,
        description=description,
        journey_id=journey,
        priority=p,
    )

    result = f"Created goal '{goal.title}' (ID: {goal.id[:8]}...) with priority {p.name}"
    if journey:
        result += f" in journey {journey[:8]}..."
    return result


@tool(name="goals_list", description="List goals", toolset="goals")
def list_goals(journey: str | None = None, status: str | None = None) -> str:
    """列出目标。

    Args:
        journey: 按旅程 ID 过滤。
        status: 按状态过滤 (active/completed/paused/abandoned)。
    """
    tracker = _get_tracker()

    status_filter = None
    if status:
        try:
            status_filter = GoalStatus(status.lower())
        except ValueError:
            valid = ", ".join(s.value for s in GoalStatus)
            return f"Error: Invalid status '{status}'. Use: {valid}"

    goals = tracker.list_goals(journey_id=journey, status=status_filter)

    if not goals:
        return "(no goals found)"

    lines = ["=" * 60, "  GOALS", "=" * 60, ""]
    for g in goals:
        deadline_str = f" | Due: {g.deadline.strftime('%Y-%m-%d')}" if g.deadline else ""
        lines.append(f"[{g.status.value}] [{g.priority.name}] {g.title}{deadline_str}")
        lines.append(f"  ID: {g.id[:16]}...")
        if g.checkpoints:
            lines.append(f"  Checkpoints: {len(g.checkpoints)}")
        lines.append("")

    return "\n".join(lines)


@tool(name="goals_complete", description="Mark a goal as completed", toolset="goals")
def complete_goal(goal_id: str, reflection: str | None = None) -> str:
    """完成目标。

    Args:
        goal_id: 目标 ID。
        reflection: 完成反思。
    """
    tracker = _get_tracker()

    try:
        goal = tracker.complete_goal(goal_id, reflection=reflection)
        result = f"Completed goal '{goal.title}'"
        if reflection:
            result += f" with reflection: {reflection[:50]}..."
        return result
    except ValueError as e:
        return f"Error: {e}"


@tool(name="goals_pause", description="Pause a goal", toolset="goals")
def pause_goal(goal_id: str) -> str:
    """暂停目标。

    Args:
        goal_id: 目标 ID。
    """
    tracker = _get_tracker()
    goal = tracker.pause_goal(goal_id)
    return f"Paused goal '{goal.title}'"


@tool(name="goals_checkpoint", description="Add a checkpoint to a goal", toolset="goals")
def add_checkpoint(goal_id: str, content: str) -> str:
    """添加检查点。

    Args:
        goal_id: 目标 ID。
        content: 检查点内容。
    """
    tracker = _get_tracker()
    tracker.add_checkpoint(goal_id, content)
    return f"Added checkpoint to goal {goal_id[:8]}...: {content[:50]}..."


@tool(name="goals_progress", description="Get journey progress", toolset="goals")
def get_journey_progress(journey_id: str) -> str:
    """获取旅程进度。

    Args:
        journey_id: 旅程 ID。
    """
    tracker = _get_tracker()
    journey = tracker.get_journey(journey_id)

    if journey is None:
        return f"Error: Journey '{journey_id}' not found"

    progress = tracker.calculate_journey_progress(journey_id)
    return f"Journey '{journey.name}': {progress * 100:.0f}% complete ({len(journey.goals)} goals)"


@tool(name="goals_summary", description="Get goals summary statistics", toolset="goals")
def goals_summary() -> str:
    """获取目标统计摘要。"""
    tracker = _get_tracker()
    view = GoalsView(tracker)
    summary = view.render_summary()

    stats = summary["stats"]
    lines = ["=" * 60, "  GOALS SUMMARY", "=" * 60, ""]
    lines.append(f"Total Goals: {stats['total_goals']}")
    lines.append(f"  - Active: {stats['active_goals']}")
    lines.append(f"  - Completed: {stats['completed_goals']} ({stats['completion_rate']}%)")
    lines.append(f"  - Paused: {stats['paused_goals']}")
    lines.append(f"Total Journeys: {stats['total_journeys']}")
    lines.append("")

    lines.append("Priority Distribution:")
    for p, count in stats["priority_distribution"].items():
        lines.append(f"  {p}: {count}")
    lines.append("")

    return "\n".join(lines)


@tool(name="goals_board", description="Render goals board view", toolset="goals")
def render_goals_board(journey_id: str | None = None) -> str:
    """渲染目标看板视图。

    Args:
        journey_id: 旅程 ID（可选）。
    """
    tracker = _get_tracker()
    view = GoalsView(tracker)
    return view.render_board(journey_id=journey_id)


@tool(name="journey_create", description="Create a new journey", toolset="goals")
def create_journey(name: str, description: str = "", tags: str | None = None) -> str:
    """创建新旅程。

    Args:
        name: 旅程名称。
        description: 旅程描述。
        tags: 标签（逗号分隔）。
    """
    tracker = _get_tracker()
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    journey = tracker.create_journey(name=name, description=description, tags=tag_list)
    return f"Created journey '{journey.name}' (ID: {journey.id[:8]}...)"


@tool(name="journey_list", description="List all journeys", toolset="goals")
def list_journeys() -> str:
    """列出所有旅程。"""
    tracker = _get_tracker()
    journeys = tracker.list_journeys()

    if not journeys:
        return "(no journeys found)"

    lines = ["=" * 60, "  JOURNEYS", "=" * 60, ""]
    for j in journeys:
        lines.append(f"[{j.progress * 100:.0f}%] {j.name}")
        lines.append(f"  ID: {j.id[:16]}... | Goals: {len(j.goals)}")
        if j.tags:
            lines.append(f"  Tags: {', '.join(j.tags)}")
        lines.append("")

    return "\n".join(lines)
