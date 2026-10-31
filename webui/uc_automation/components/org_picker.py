"""The labelled organization and instance dropdowns shown on every platform page."""

import reflex as rx


def labeled(label: str, control: rx.Component) -> rx.Component:
    return rx.hstack(rx.text(label, size="1", color="var(--gray-11)"), control, align="center", spacing="1")


def org_select(S, on_change=None) -> rx.Component:
    """Org: dropdown for a platform state (hidden until an organization exists)."""
    return rx.cond(
        S.org_options.length() > 0,
        labeled("Org:", rx.select(S.org_options, value=S.active_org, on_change=on_change or S.select_org, size="1",
                                  placeholder="Organization")),
        rx.fragment(),
    )


def instance_select(names, value, on_change) -> rx.Component:
    """Instance: dropdown (the cluster, server or Webex org of the chosen organization)."""
    return labeled("Instance:", rx.select(names, value=value, on_change=on_change, size="1"))
