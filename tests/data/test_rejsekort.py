import argparse
import datetime as dt

import pandas as pd
import pytest

from msc_thesis.data.rejsekort.ingestion import (
    REGION_COL,
    REGION_VALUE,
    _day_strings,
    _filter_chunk,
    add_span_args,
    parse_span,
    span_name,
)


def test_span_name():
    assert span_name(2017) == "2017"
    assert span_name(2017, dt.date(2017, 6, 19)) == "2017-06-19"
    assert span_name(2017, dt.date(2017, 6, 19), dt.date(2017, 6, 19)) == "2017-06-19"
    assert span_name(2017, dt.date(2017, 6, 19), dt.date(2017, 6, 26)) == "2017-06-19_2017-06-26"


def test_day_strings_cover_inclusive_range():
    days = _day_strings(dt.date(2017, 6, 29), dt.date(2017, 7, 1))
    assert days == {"29JUN2017", "30JUN2017", "01JUL2017"}
    with pytest.raises(ValueError, match="before start"):
        _day_strings(dt.date(2017, 6, 2), dt.date(2017, 6, 1))


def test_filter_chunk_keeps_region_and_days():
    chunk = pd.DataFrame({
        REGION_COL: [REGION_VALUE, REGION_VALUE, "Other"],
        "RejseDato": ["19jun2017", "18JUN2017", "19JUN2017"],
    })
    kept = _filter_chunk(chunk, {"19JUN2017"})
    assert kept.index.tolist() == [0]


def _parse(argv: list[str]):
    parser = argparse.ArgumentParser()
    add_span_args(parser)
    return parse_span(parser, parser.parse_args(argv))


def test_parse_span():
    assert _parse([]) == (None, None)
    assert _parse(["--day", "2017-06-19"]) == (dt.date(2017, 6, 19),) * 2
    assert _parse(["--start", "2017-06-19"]) == (dt.date(2017, 6, 19),) * 2
    assert _parse(["--start", "2017-06-19", "--end", "2017-06-26"]) == (
        dt.date(2017, 6, 19), dt.date(2017, 6, 26),
    )
    with pytest.raises(SystemExit):
        _parse(["--day", "2017-06-19", "--start", "2017-06-19"])
    with pytest.raises(SystemExit):
        _parse(["--end", "2017-06-26"])
