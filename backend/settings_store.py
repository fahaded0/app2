"""Default SLA / alert settings — overridable from the Settings screen."""
from typing import Any

DEFAULT_SETTINGS_ID = "alert_sla"

DEFAULT_SLA: dict[str, Any] = {
    "id": DEFAULT_SETTINGS_ID,
    # All values in minutes. 0 means "immediate" (escalate as soon as opened).
    "zero_level_normal_minutes":       360,    # 6h
    "zero_level_lifesaving_minutes":   0,      # immediate
    "critical_level_escalation_minutes": 1440, # 24h
    "backorder_escalation_minutes":    2880,   # 48h
    "no_update_minutes":               1440,   # 24h
    "scheduler_interval_minutes":      15,
}


async def get_settings(db) -> dict:
    doc = await db.settings.find_one({"id": DEFAULT_SETTINGS_ID}, {"_id": 0})
    if not doc:
        await db.settings.insert_one(DEFAULT_SLA.copy())
        return DEFAULT_SLA.copy()
    # Backfill any missing keys (forward-compat with future fields)
    for k, v in DEFAULT_SLA.items():
        if k not in doc:
            doc[k] = v
    return doc


async def update_settings(db, patch: dict) -> dict:
    allowed_keys = set(DEFAULT_SLA.keys()) - {"id"}
    clean = {k: int(v) for k, v in patch.items() if k in allowed_keys}
    if not clean:
        return await get_settings(db)
    await db.settings.update_one(
        {"id": DEFAULT_SETTINGS_ID},
        {"$set": clean},
        upsert=True,
    )
    return await get_settings(db)
