"""Constants for EV Charge Controller."""

DOMAIN = "ev_charge_controller"
VERSION = "0.3.1"
PLATFORMS = [
    "switch",
    "number",
    "select",
    "datetime",
    "sensor",
    "binary_sensor",
    "button",
    "calendar",
]
MODES = ("cheap_top_up", "deadline", "flexible")
DEFAULTS = {
    "capacity_kwh": 60.0,
    "voltage": 230.0,
    "efficiency": 0.92,
    "fixed_power_kw": 7.0,
    "planning_margin": 0.1,
    "preconditioning_policy": "keep_existing",
    "preconditioning_minutes": 60,
    "boost_hours": 12,
    "max_retries": 3,
    "retry_seconds": 60,
    "manual_hold_minutes": 120,
    # A second unrequested charge start inside this window is a manual override.
    "repeat_start_minutes": 2,
    "external_change_policy": "respect",
    "maintenance_margin": 2,
    "stale_minutes": 30,
    "max_cheap_rate": 12.0,
    "target_percent": 80.0,
    "mode": "cheap_top_up",
    "hard_price_ceiling": False,
    "monitoring_only": True,
    "automatic_control": True,
    "learn_power": False,
}
ENTITY_KEYS = (
    "charge_switch",
    "charging_sensor",
    "cable_sensor",
    "location_entity",
    "home_zone",
    "soc_entity",
    "car_limit_entity",
    "current_entity",
    "preconditioning_entity",
    "completion_entity",
    "rate_entity",
    "today_rates_entity",
    "tomorrow_rates_entity",
    "free_session_entity",
    "power_entity",
)
