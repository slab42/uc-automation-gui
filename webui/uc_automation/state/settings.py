"""State for the Settings page: log retention."""

import reflex as rx

from ..backend import app_settings, applog


class SettingsState(rx.State):
    retention_days: str = ""
    max_mb: str = ""

    @rx.event
    def on_page_load(self):
        cfg = app_settings.load()
        self.retention_days = str(cfg["log_retention_days"])
        self.max_mb = str(cfg["log_max_mb"])

    @rx.event
    def set_retention_days(self, value: str):
        self.retention_days = value

    @rx.event
    def set_max_mb(self, value: str):
        self.max_mb = value

    @rx.event
    def save_log_settings(self):
        try:
            days, mb = int(self.retention_days.strip()), int(self.max_mb.strip())
            if days < 0 or mb < 0:
                raise ValueError
        except ValueError:
            return rx.toast.error("Enter whole numbers, 0 or more. 0 turns that limit off.")
        app_settings.save({"log_retention_days": days, "log_max_mb": mb})
        removed = applog.prune_logs()
        return rx.toast.success(f"Saved. {removed} old log(s) deleted." if removed else "Saved.")

    @rx.event
    def reset_log_settings(self):
        self.retention_days = str(app_settings.DEFAULTS["log_retention_days"])
        self.max_mb = str(app_settings.DEFAULTS["log_max_mb"])
