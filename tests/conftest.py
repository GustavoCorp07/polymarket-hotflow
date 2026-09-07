from __future__ import annotations

import pytest

from hotflow.config import HotflowConfig
from hotflow.pipeline import demo_market
from hotflow.types import FeeSchedule, MarketRecord


@pytest.fixture
def config() -> HotflowConfig:
    return HotflowConfig()


@pytest.fixture
def hot_market() -> MarketRecord:
    return demo_market(hot=True)


@pytest.fixture
def unknown_fee_market(hot_market: MarketRecord) -> MarketRecord:
    clone = hot_market.model_copy(deep=True)
    clone.fees = FeeSchedule(source="missing")
    return clone
