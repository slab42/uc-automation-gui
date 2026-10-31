"""A bordered box around one organization's entries in a saved list on the Credentials page."""

import reflex as rx


def org_box(group, row) -> rx.Component:
    """`group` is {"org", "items"} from a state's saved_groups; `row` builds one entry."""
    return rx.vstack(
        rx.text(group["org"], size="2", weight="bold", color="var(--gray-11)"),
        rx.foreach(group["items"].to(list[dict[str, str]]), row),
        spacing="2",
        width="100%",
        padding="0.75rem",
        border="1px solid var(--gray-6)",
        border_radius="var(--radius-4)",
        background="var(--gray-2)",
    )
