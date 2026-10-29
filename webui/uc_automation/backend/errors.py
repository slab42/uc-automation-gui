"""Base class for errors whose message is meant for the user (AXL faults, Webex API errors, login problems)."""


class UserError(Exception):
    pass
