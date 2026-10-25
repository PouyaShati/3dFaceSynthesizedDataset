from pathlib import Path

import pytest

from desk.config import ConfigError, load_config


EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_example_config_loads_the_published_rules():
    config = load_config(EXAMPLE)
    assert config.risk_fraction == 0.005
    assert config.max_positions == 5
    assert config.account_type == "non_registered"
    assert config.exit_plan == "scale"
    assert config.enable_breakout is False
    assert config.usd_conversion_fee == 2.0
    assert config.journal_min_trades == 30
    assert [spec.symbol for spec in config.watchlist] == ["EXAMPLE.TO", "EXAMPLE"]


def test_position_cap_and_risk_fraction_are_fixed(tmp_path):
    source = tmp_path / "config.yaml"
    source.write_text(
        (EXAMPLE.read_text(encoding="utf-8")).replace("max_positions: 5", "max_positions: 7"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="4, 5, or 6"):
        load_config(source)
