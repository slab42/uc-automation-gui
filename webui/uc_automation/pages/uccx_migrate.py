"""UCCX > Migrate."""

import reflex as rx

from ..components.tool_widgets import confirm_dialog, field, run_results
from ..components.uccx_nav import SCRIPT_REPORT, uccx_page
from ..state.uccx_migrate import UccxMigrateState

S = UccxMigrateState
MUTED = "var(--gray-11)"


def _stored_facts() -> rx.Component:
    return rx.vstack(
        rx.text("From " + S.stored["source"] + " (" + S.stored["server"] + "), downloaded " + S.stored["created"]
                + ", " + S.stored["size"], size="2"),
        rx.text(S.stored["xml"] + " settings files, " + S.stored["finesse"] + " Finesse files, " + S.stored["scripts"]
                + " scripts, " + S.stored["prompts"] + " prompts", size="2", color=MUTED),
        rx.cond(S.stored["complete"] == "no",
                rx.badge("Incomplete: some areas failed or the download was interrupted", color_scheme="orange"),
                rx.fragment()),
        spacing="1", align="start",
    )


def _stored_card() -> rx.Component:
    return rx.cond(
        S.has_stored,
        rx.card(
            rx.vstack(
                rx.heading("Stored Download", size="4"),
                _stored_facts(),
                rx.text("Kept only for a short time (7 days) and removed when you delete it.", size="1", color=MUTED),
                rx.hstack(
                    rx.button(rx.icon("archive", size=16), "Export As Zip", variant="soft", on_click=S.export_stored,
                              disabled=S.busy),
                    rx.link(rx.button(rx.icon("file-search", size=16), "Script Report", variant="soft"),
                            href=SCRIPT_REPORT),
                    rx.button(rx.icon("trash-2", size=16), "Delete", variant="soft", color_scheme="red",
                              on_click=S.delete_stored, disabled=S.busy),
                    spacing="2", wrap="wrap",
                ),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.fragment(),
    )


def _existing_dialog() -> rx.Component:
    """Asked every time the page opens while a download is stored. No way out except one of the three choices."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Previous Download Found"),
            rx.dialog.description("A UCCX download is still stored. Continue with it, export it as a zip file, or "
                                  "delete it.", size="2", margin_bottom="1rem"),
            rx.cond(S.has_stored, _stored_facts(), rx.fragment()),
            rx.hstack(
                rx.button("Delete It", color_scheme="red", variant="soft", on_click=S.delete_stored, disabled=S.busy),
                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("archive", size=16)), "Export As Zip",
                          variant="soft", on_click=S.export_stored, disabled=S.busy),
                rx.button("Continue With It", on_click=S.keep_existing),
                spacing="3", justify="end", margin_top="1.25rem", wrap="wrap",
            ),
            max_width="520px",
        ),
        open=S.existing_open,
    )


def _download_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("1. Download From Origin", size="4"),
            rx.text("Reads the skills, CSQs, agents, teams, calendars, applications, triggers, call control groups, "
                    "Finesse settings, scripts and prompts. Nothing on the origin is changed.", size="2", color=MUTED),
            field("Origin", rx.select(S.connection_names, value=S.origin_sel, on_change=S.set_origin, width="100%")),
            rx.cond(
                S.has_stored,
                rx.button(rx.icon("download", size=16), "Download Everything", on_click=S.set_replace_open(True),
                          disabled=S.busy | (S.origin_sel == "")),
                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("download", size=16)), "Download Everything",
                          on_click=S.download_all, disabled=S.busy | (S.origin_sel == "")),
            ),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _step_box(step) -> rx.Component:
    return rx.checkbox(step["label"], checked=S.selected_steps.contains(step["key"]),
                       on_change=lambda on: S.toggle_step(step["key"], on))


def _upload_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("2. Upload To Destination", size="4"),
            rx.text("Writes the stored download to the destination, in the order below. Items that already exist by "
                    "name are skipped. Anything the destination lacks (for example an agent that is not in CUCM yet) "
                    "is reported, not created.", size="2", color=MUTED),
            field("Destination", rx.select(S.dest_names, value=S.dest_sel, on_change=S.set_dest, width="100%"),
                  "Another connection of the same organization."),
            rx.text("Steps", size="2", weight="medium"),
            rx.grid(rx.foreach(S.steps, _step_box), columns=rx.breakpoints(initial="1", sm="2"), spacing="2",
                    width="100%"),
            rx.text("Delete Existing Triggers removes every trigger on the destination first. It is off by default.",
                    size="1", color=MUTED),
            rx.text("Options", size="2", weight="medium"),
            rx.checkbox("Keep skill IDs as on the origin (needed by third party APIs such as Calabrio)",
                        checked=S.opt_original_ids, on_change=lambda on: S.set_opt("original_ids", on)),
            rx.checkbox("Update CSQs, teams and calendars in place by ID instead of creating them",
                        checked=S.opt_in_place, on_change=lambda on: S.set_opt("in_place", on)),
            rx.cond(
                S.ccgs_selected,
                rx.checkbox("Both servers are LAN deployments (call control groups only import between LAN deployments)",
                            checked=S.opt_lan, on_change=lambda on: S.set_opt("lan", on)),
                rx.fragment(),
            ),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), "Upload Selected...",
                      on_click=S.set_confirm_open(True),
                      disabled=S.busy | ~S.has_stored | (S.dest_sel == "") | (S.selected_count == 0)),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def migrate() -> rx.Component:
    return uccx_page(
        "Migrate",
        rx.cond(
            S.connection_names.length() > 0,
            rx.vstack(
                rx.text("Download everything it can from a UCCX server, keep it briefly, then upload it to a new UCCX "
                        "server. Choose the organization above; both servers are its saved UCCX connections.",
                        size="2", color=MUTED),
                _stored_card(),
                _download_card(),
                _upload_card(),
                rx.cond(S.last_op != "", rx.heading(S.last_op + " Results", size="4"), rx.fragment()),
                run_results(S, "Item"),
                _existing_dialog(),
                confirm_dialog(S, "Replace The Stored Download?",
                               "Downloading again deletes the stored download and replaces it.", "Replace And Download",
                               S.download_all, open_var=S.replace_open, set_open=S.set_replace_open),
                confirm_dialog(S, "Upload To The Destination?",
                               "Upload " + S.selected_count.to_string() + " step(s) of the stored download to "
                               + S.dest_sel + ". This creates and changes things on that server.",
                               "Upload", S.upload_selected),
                spacing="4", align="start", width="100%",
            ),
            rx.callout(
                rx.hstack(rx.text("No UCCX connection is set up for this organization."),
                          rx.link("Add one on the Credentials page", href="/credentials?tab=uccx"), spacing="2"),
                icon="info", width="100%",
            ),
        ),
        show_instance=False,
    )
