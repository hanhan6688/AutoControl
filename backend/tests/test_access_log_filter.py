import logging

from app.main import SuppressAccessPathFilter


def make_access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:62805", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_access_log_filter_hides_devices_polling_endpoint() -> None:
    filter_item = SuppressAccessPathFilter({"/api/devices"})

    assert filter_item.filter(make_access_record("/api/devices")) is False
    assert filter_item.filter(make_access_record("/api/devices?refresh=1")) is False


def test_access_log_filter_keeps_other_endpoints_visible() -> None:
    filter_item = SuppressAccessPathFilter({"/api/devices"})

    assert filter_item.filter(make_access_record("/api/test-plans")) is True
    assert filter_item.filter(make_access_record("/api/devices/abc/screen")) is True
