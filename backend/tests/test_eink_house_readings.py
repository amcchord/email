"""Room sensor selection and daily coffee totals for Home Editorial."""
import pytest

from backend.services.eink import ha_client as hc


def state(entity, value, unit=None):
    return {"entity_id": entity, "state": value,
            "attributes": {"unit_of_measurement": unit}}


def test_room_readings_use_room_sensors_and_daily_coffee_meter():
    shape = hc.shape_ha_state([
        state(hc._TEMP_PRIMARY_BEDROOM, "67.2", "°F"),
        state(hc._TEMP_LIVING_ROOM, "71.6", "°F"),
        state(hc._TEMP_FIRST, "80"),
        state(hc._TEMP_SECOND, "81"),
        state("sensor.living_room_bridge_temperature", "30.2", "°F"),
        state(hc._COFFEE_CUPS_TODAY, "4", "cups"),
        state("sensor.kitchen_coffee_cups_total", "1200", "cups"),
    ])
    assert shape["temps"]["primaryBedroom"] == 67.2
    assert shape["temps"]["livingRoom"] == 71.6
    assert shape["coffee"] == {"cupsToday": 4}
    assert shape["temps"]["first"] == 80  # Other designs retain floor data.


def test_celsius_room_reading_is_normalized_to_fahrenheit():
    shape = hc.shape_ha_state([state(hc._TEMP_PRIMARY_BEDROOM, "20", "°C")])
    assert shape["temps"]["primaryBedroom"] == 68


@pytest.mark.parametrize("value", ["unavailable", "unknown", "nan", "inf", "-inf", "bad"])
def test_unavailable_or_nonfinite_room_readings_are_missing(value):
    shape = hc.shape_ha_state([state(hc._TEMP_PRIMARY_BEDROOM, value, "°F")])
    assert shape["temps"]["primaryBedroom"] is None


@pytest.mark.parametrize("value, expected", [("0", 0), ("0.0", 0), ("1", 1),
    ("12", 12), ("unavailable", None), ("unknown", None), ("-1", None),
    ("1.5", None), ("nan", None), ("inf", None), ("-inf", None)])
def test_coffee_preserves_zero_and_rejects_unknown_or_invalid_counts(value, expected):
    shape = hc.shape_ha_state([state(hc._COFFEE_CUPS_TODAY, value)])
    assert shape["coffee"]["cupsToday"] == expected


def test_missing_daily_meter_never_uses_lifetime_counter():
    shape = hc.shape_ha_state([state("sensor.kitchen_coffee_cups_total", "1200")])
    assert shape["coffee"]["cupsToday"] is None
    assert hc.empty_ha_shape()["coffee"]["cupsToday"] is None
    assert shape["temps"]["primaryBedroom"] is None
    assert shape["temps"]["livingRoom"] is None
