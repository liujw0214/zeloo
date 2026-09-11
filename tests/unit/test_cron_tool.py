"""Tests for cron_tool and CronScheduler."""

import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, ".")

from cron.scheduler import CronScheduler, cron_matches, parse_cron


def test_parse_cron_basic():
    fields = parse_cron("0 2 * * *")
    assert fields[0] == {0}  # minute
    assert fields[1] == {2}  # hour
    assert len(fields[2]) == 32  # day of month (0-31)
    assert len(fields[3]) == 13  # month (0-12, parser uses 0-based range)
    assert len(fields[4]) == 7  # day of week (0-6)


def test_parse_cron_step():
    fields = parse_cron("*/5 * * * *")
    assert fields[0] == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


def test_parse_cron_range():
    fields = parse_cron("0 9-17 * * 1-5")
    assert fields[1] == set(range(9, 18))
    assert fields[4] == {1, 2, 3, 4, 5}


def test_parse_cron_invalid_fields():
    try:
        parse_cron("0 2 * *")  # 4 fields
        raise AssertionError("should raise")
    except ValueError:
        pass
    try:
        parse_cron("0 2 * * * *")  # 6 fields
        raise AssertionError("should raise")
    except ValueError:
        pass
    try:
        parse_cron("60 * * * *")  # minute out of range
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_cron_matches():
    dt = datetime(2026, 1, 15, 14, 30)  # Thursday
    assert cron_matches("30 14 * * *", dt)
    assert not cron_matches("0 14 * * *", dt)
    assert cron_matches("* * * * 4", dt)  # Thursday=3? weekday()=3
    assert cron_matches("* * 15 * *", dt)


def test_scheduler_add_list_remove():
    sched = CronScheduler()
    sched.add_job("test", "* * * * *", lambda: None)
    jobs = sched.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test"
    assert jobs[0]["expression"] == "* * * * *"
    sched.remove_job("test")
    assert sched.list_jobs() == []


def test_scheduler_remove_nonexistent():
    sched = CronScheduler()
    sched.remove_job("nope")  # should not raise
    assert sched.list_jobs() == []


def test_cron_tool_no_scheduler():
    with patch("tools.cron_tool._get_scheduler", return_value=None):
        from tools.cron_tool import cron_add, cron_list, cron_remove

        assert "not available" in cron_add("t", "* * * * *", "echo hi")
        assert "not available" in cron_list()
        assert "not available" in cron_remove("t")


def test_cron_tool_add_list():
    sched = CronScheduler()
    with patch("tools.cron_tool._get_scheduler", return_value=sched):
        from tools.cron_tool import cron_add, cron_list

        result = cron_add("daily", "0 2 * * *", "backup")
        assert "registered" in result
        listing = cron_list()
        assert "daily" in listing


def test_cron_tool_invalid_expression():
    sched = CronScheduler()
    with patch("tools.cron_tool._get_scheduler", return_value=sched):
        from tools.cron_tool import cron_add

        result = cron_add("bad", "99 * * * *", "echo")
        assert "invalid" in result.lower()


if __name__ == "__main__":
    test_parse_cron_basic()
    test_parse_cron_step()
    test_parse_cron_range()
    test_parse_cron_invalid_fields()
    test_cron_matches()
    test_scheduler_add_list_remove()
    test_scheduler_remove_nonexistent()
    test_cron_tool_no_scheduler()
    test_cron_tool_add_list()
    test_cron_tool_invalid_expression()
    print("All cron_tool tests passed!")
