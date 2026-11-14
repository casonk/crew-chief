import logging

import pytest

from crew_chief.log_policy import LogLevelPolicy


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def parts():
    clock = Clock()
    logger = logging.getLogger("crew_chief.test_log_policy")
    logger.handlers.clear()
    logger.propagate = False
    policy = LogLevelPolicy(
        start="DEBUG", floor="WARNING", degrade_after=100, clock=clock, logger=logger
    )
    yield policy, clock, logger
    logger.handlers.clear()


def level(logger):
    return logging.getLevelName(logger.level)


def test_it_starts_verbose(parts):
    policy, _, logger = parts
    assert policy.level == "DEBUG" == level(logger)


def test_it_steps_down_one_level_per_clean_period_and_stops_at_the_floor(parts):
    policy, clock, logger = parts
    seen = []
    for _ in range(5):
        clock.now += 100
        seen.append(policy.tick())
    assert seen == ["INFO", "WARNING", "WARNING", "WARNING", "WARNING"]
    assert level(logger) == "WARNING"


def test_it_does_nothing_before_the_period_has_passed(parts):
    policy, clock, _ = parts
    clock.now = 99
    assert policy.tick() == "DEBUG"


def test_a_warning_restores_full_detail_and_restarts_the_clock(parts):
    policy, clock, logger = parts
    clock.now = 100
    policy.tick()
    assert policy.level == "INFO"
    logger.warning("something failed")
    assert policy.level == "DEBUG" == level(logger)
    clock.now = 199
    assert policy.tick() == "DEBUG", "the clean period restarts at the issue"
    clock.now = 200
    assert policy.tick() == "INFO"


def test_info_records_do_not_count_as_issues(parts):
    policy, clock, logger = parts
    clock.now = 100
    policy.tick()
    logger.info("routine")
    assert policy.level == "INFO"


def test_a_floor_more_verbose_than_the_start_never_degrades():
    clock = Clock()
    logger = logging.getLogger("crew_chief.test_log_policy_floor")
    logger.propagate = False
    policy = LogLevelPolicy(
        start="INFO", floor="DEBUG", degrade_after=1, clock=clock, logger=logger
    )
    clock.now = 10_000
    assert policy.tick() == "INFO"
    logger.handlers.clear()


def test_unknown_levels_are_rejected():
    with pytest.raises(ValueError):
        LogLevelPolicy(start="LOUD")
