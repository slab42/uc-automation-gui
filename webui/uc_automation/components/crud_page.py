"""Reusable page for a CUCM resource: search, select, add, import, export, delete, bulk delete."""

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import reflex as rx

from .cucm_nav import cucm_page
from .search_input import search_input


@dataclass
class Column:
    header: str
    field: str
    code: bool = False


@dataclass
class CrudPageConfig:
    title: str                      # "Partitions"
    noun: str                       # "partition"
    key: str                        # row key field
    columns: list[Column]
    add_body: Callable[[type], rx.Component] | None = None   # builds the add-form fields for state S
    add_required: str = ""          # form field that must be filled to enable Add (default: key)
    import_notes: str = ""
    can_add: bool = True
    can_import: bool = True
    can_modify: bool = True
    import_add: bool = True          # show the Add button in the import dialog
    modify_label: str = "Modify"     # label of the import dialog's second button (it runs update_fn)
    can_copy: bool = False           # Copy button: Add dialog pre-filled from the one selected row
    can_delete: bool = True          # delete selected + bulk delete
    delete_note: str = ""
    extra_toolbar: Callable[[type], list[rx.Component]] | None = None
    extra_dialogs: Callable[[type, SimpleNamespace], list[rx.Component]] | None = None


def form_field(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(rx.text(label, size="2", weight="medium"), control, spacing="1", align="start", width="100%")


def text_input(S, field: str, placeholder: str = "", **kw) -> rx.Component:
    return rx.input(value=S.new_form[field], placeholder=placeholder,
                    on_change=lambda v: S.set_new(field, v), width="100%", **kw)


def dependency_toolbar(S) -> list[rx.Component]:
    """Check dependencies button for states that use DepCheckMixin."""
    return [
        rx.button(rx.icon("search-check", size=16), "Check dependencies", variant="soft",
                  disabled=S.selected_count == 0, on_click=S.check_dependencies),
    ]


def dependency_dialogs(S, h, title: str, noun_header: str, checking_text: str) -> list[rx.Component]:
    return [
        h.dialog(
            "deps", title,
            rx.vstack(
                rx.cond(
                    S.dep_checking,
                    rx.hstack(rx.spinner(size="2"),
                              rx.text(checking_text, size="2"),
                              align="center", spacing="2"),
                    rx.fragment(),
                ),
                rx.foreach(S.dep_warnings, lambda w: rx.callout(w, icon="triangle-alert", color_scheme="amber",
                                                               size="2", width="100%")),
                rx.cond(
                    S.dep_results.length() > 0,
                    rx.vstack(
                        rx.hstack(
                            rx.badge(S.dep_unused.length().to_string() + " unused", color_scheme="green"),
                            rx.badge(S.dep_in_use_count.to_string() + " in use",
                                     color_scheme=rx.cond(S.dep_in_use_count > 0, "red", "gray")),
                            spacing="2",
                        ),
                        rx.scroll_area(
                            rx.table.root(
                                rx.table.header(rx.table.row(
                                    rx.table.column_header_cell(noun_header),
                                    rx.table.column_header_cell("Status"),
                                    rx.table.column_header_cell("Refs"),
                                    rx.table.column_header_cell("Used by"),
                                )),
                                rx.table.body(rx.foreach(S.dep_results, lambda r: rx.table.row(
                                    rx.table.cell(rx.code(r["key"])),
                                    rx.table.cell(rx.badge(r["status"], color_scheme=rx.match(
                                        r["status"], ("Unused", "green"), ("In use", "red"), "amber"))),
                                    rx.table.cell(r["count"]),
                                    rx.table.cell(r["detail"]),
                                ))),
                                size="2",
                            ),
                            max_height="calc(70vh - 15rem)",
                        ),
                        spacing="2", align="start", width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.hstack(
                    h.close_button(),
                    rx.spacer(),
                    rx.button(rx.icon("list-checks", size=16), "Keep only unused selected",
                              variant="soft", on_click=S.select_unused,
                              disabled=S.dep_checking | (S.dep_unused.length() == 0)),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="70vw",
            height="70vh",
        ),
    ]


def build_crud_page(S, cfg: CrudPageConfig) -> Callable[[], rx.Component]:
    """Return a page function for state class S (a CucmState + CrudMixin subclass)."""

    def dialog(name: str, title: str, *body: rx.Component, width: str = "640px", height: str = "") -> rx.Component:
        size = {"width": width, "height": height} if height else {}
        return rx.dialog.root(
            rx.dialog.content(rx.dialog.title(title), *body, max_width=width, **size),
            open=S.dialog == name,
            on_open_change=lambda o: S.set_dialog(name, o),
        )

    def close_button(label: str = "Close") -> rx.Component:
        return rx.button(label, variant="soft", color_scheme="gray",
                         on_click=S.set_dialog("", False), disabled=S.busy)

    def results() -> rx.Component:
        return rx.cond(
            S.results.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.badge(S.result_ok_count.to_string() + " succeeded", color_scheme="green"),
                    rx.badge(S.result_fail_count.to_string() + " failed",
                             color_scheme=rx.cond(S.result_fail_count > 0, "red", "gray")),
                    spacing="2",
                ),
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell(cfg.noun.capitalize()),
                            rx.table.column_header_cell("Result"),
                            rx.table.column_header_cell("Detail"),
                        )),
                        rx.table.body(rx.foreach(S.results, lambda r: rx.table.row(
                            rx.table.cell(rx.code(r["key"])),
                            rx.table.cell(rx.badge(r["status"],
                                                   color_scheme=rx.cond(r["status"] == "OK", "green", "red"))),
                            rx.table.cell(r["detail"]),
                        ))),
                        size="1",
                    ),
                    max_height="220px",
                ),
                spacing="2", align="start", width="100%",
            ),
            rx.fragment(),
        )

    def progress() -> rx.Component:
        return rx.cond(
            S.busy,
            rx.hstack(rx.spinner(size="2"), rx.text(S.progress, size="2"), align="center", spacing="2"),
            rx.fragment(),
        )

    def dropzone(upload_id: str) -> rx.Component:
        return rx.vstack(
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=22, color="var(--gray-10)"),
                    rx.text("Drop a CSV here or click to choose", size="2"),
                    align="center", spacing="1",
                ),
                id=upload_id,
                accept={"text/csv": [".csv"]},
                max_files=1,
                multiple=False,
                padding="1.25rem",
                border="1px dashed var(--gray-7)",
                border_radius="var(--radius-3)",
                width="100%",
            ),
            rx.foreach(rx.selected_files(upload_id), lambda f: rx.badge(f, variant="soft")),
            spacing="2", align="start", width="100%",
        )

    def code_block(text) -> rx.Component:
        return rx.box(
            rx.el.pre(text, style={"margin": "0", "font_size": "12px", "font_family": "var(--code-font-family)"}),
            padding="0.75rem", background="var(--gray-3)", border_radius="var(--radius-3)",
            overflow_x="auto", width="100%",
        )

    def add_dialog() -> rx.Component:
        return dialog(
            "add", f"Add {cfg.noun}",
            rx.vstack(
                cfg.add_body(S),
                rx.cond(S.add_error != "",
                        rx.callout(S.add_error, icon="triangle-alert", color_scheme="red", width="100%"),
                        rx.fragment()),
                rx.hstack(
                    close_button("Cancel"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add",
                              on_click=S.add_one, disabled=S.busy | (S.new_form[cfg.add_required or cfg.key] == "")),
                    justify="end", spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
        )

    def import_dialog() -> rx.Component:
        return dialog(
            "import", "Import from CSV",
            rx.vstack(
                rx.text(f"The CSV needs a header row with these columns. Only {cfg.key} is required.",
                        size="2", color="var(--gray-11)"),
                code_block(S.template_text),
                rx.text(cfg.import_notes + (
                    (" Add uses defaults for blank cells; Modify leaves blank cells unchanged."
                     if cfg.can_modify else " Add uses defaults for blank cells.") if cfg.import_add else ""),
                        size="1", color="var(--gray-10)"),
                rx.button(rx.icon("download", size=15), "Download template", variant="ghost", size="1",
                          on_click=S.download_template),
                dropzone("import_upload"),
                progress(),
                results(),
                rx.hstack(
                    close_button(),
                    rx.spacer(),
                    *([rx.button(rx.icon("plus", size=16), "Add",
                                 on_click=S.import_add(rx.upload_files(upload_id="import_upload")),
                                 disabled=S.busy)] if cfg.import_add else []),
                    *([rx.button(rx.icon("pencil", size=16), cfg.modify_label,
                                 variant="soft" if cfg.import_add else "solid",
                                 on_click=S.import_modify(rx.upload_files(upload_id="import_upload")),
                                 disabled=S.busy)] if cfg.can_modify else []),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="720px",
        )

    def bulk_dialog() -> rx.Component:
        return dialog(
            "bulk", "Bulk delete from CSV",
            rx.vstack(
                rx.callout(f"Every {cfg.noun} listed in the CSV is removed from CUCM.", icon="triangle-alert",
                           color_scheme="red", size="1", width="100%"),
                rx.text(f"The CSV needs a header row with a single {cfg.key} column:", size="2",
                        color="var(--gray-11)"),
                code_block(S.bulk_template_text),
                rx.button(rx.icon("download", size=15), "Download template", variant="ghost", size="1",
                          on_click=S.download_bulk_template),
                dropzone("bulk_upload"),
                progress(),
                results(),
                rx.hstack(
                    close_button(),
                    rx.spacer(),
                    rx.button(rx.icon("trash-2", size=16), f"Delete {cfg.noun}s", color_scheme="red",
                              on_click=S.bulk_delete(rx.upload_files(upload_id="bulk_upload")), disabled=S.busy),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
        )

    def confirm_dialog() -> rx.Component:
        return dialog(
            "confirm", f"Delete selected {cfg.noun}s?",
            rx.vstack(
                rx.text("This removes ", S.selected_count.to_string(), f" {cfg.noun}(s) from CUCM. It cannot be undone. "
                        + cfg.delete_note, size="2"),
                progress(),
                rx.hstack(
                    close_button("Cancel"),
                    rx.button(rx.icon("trash-2", size=16), "Delete", color_scheme="red",
                              on_click=S.delete_selected, disabled=S.busy),
                    justify="end", spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="440px",
        )

    def result_dialog() -> rx.Component:
        return dialog(
            "result", "Some removals failed",
            rx.vstack(results(), rx.hstack(close_button(), justify="end", width="100%"),
                      spacing="3", align="start", width="100%"),
        )

    def export_choice_dialog() -> rx.Component:
        return dialog(
            "exportchoice", "Export",
            rx.vstack(
                rx.text("Some rows are selected. What should the CSV contain?", size="2"),
                rx.hstack(
                    close_button("Cancel"),
                    rx.button("Selected (", S.selected_count.to_string(), ")", variant="soft",
                              on_click=S.export_csv("selected")),
                    rx.button("All (", S.items.length().to_string(), ")", on_click=S.export_csv("all")),
                    justify="end", spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="440px",
        )

    def row(item) -> rx.Component:
        cells = [
            rx.table.cell(
                rx.checkbox(checked=S.selected.contains(item[cfg.key]),
                            on_change=lambda c: S.toggle_row(item[cfg.key], c)),
                width="40px",
            )
        ]
        for col in cfg.columns:
            cells.append(rx.table.cell(rx.code(item[col.field]) if col.code else item[col.field]))
        return rx.table.row(*cells)

    def table() -> rx.Component:
        return rx.card(
            rx.scroll_area(
                rx.table.root(
                    rx.table.header(rx.table.row(
                        rx.table.column_header_cell(
                            rx.checkbox(checked=S.all_selected, on_change=S.toggle_all), width="40px"),
                        *[rx.table.column_header_cell(c.header) for c in cfg.columns],
                    )),
                    rx.table.body(rx.foreach(S.shown, row)),
                    variant="ghost",
                    width="100%",
                ),
                max_height="60vh",
            ),
            padding="0",
            width="100%",
        )

    def toolbar() -> rx.Component:
        return rx.hstack(
            search_input(S.search, S.set_search, width="320px", max_width="100%"),
            rx.text(
                rx.cond(S.search != "",
                        S.filtered.length().to_string() + " of " + S.items.length().to_string(),
                        S.items.length().to_string() + " total"),
                size="2", color="var(--gray-11)",
            ),
            rx.spacer(),
            rx.icon_button(rx.icon("refresh-cw", size=16), variant="soft", on_click=S.fetch, loading=S.loading,
                           title="Reload from CUCM"),
            *([rx.button(rx.icon("plus", size=16), "Add", on_click=S.set_dialog("add", True))] if cfg.can_add else []),
            *([rx.button(rx.icon("copy", size=16), "Copy", variant="soft",
                         disabled=S.selected_count != 1, on_click=S.copy_selected,
                         title="Add a new row based on the selected one")] if cfg.can_copy and cfg.can_add else []),
            *([rx.button(rx.icon("upload", size=16), "Import", variant="soft",
                         on_click=S.set_dialog("import", True))] if cfg.can_import else []),
            rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_click),
            *(cfg.extra_toolbar(S) if cfg.extra_toolbar else []),
            *([rx.button(rx.icon("list-x", size=16), "Bulk delete", variant="soft", color_scheme="red",
                         on_click=S.set_dialog("bulk", True)),
               rx.button(rx.icon("trash-2", size=16), "Delete selected (", S.selected_count.to_string(), ")",
                         color_scheme="red", disabled=S.selected_count == 0,
                         on_click=S.set_dialog("confirm", True))] if cfg.can_delete else []),
            align="center", spacing="3", wrap="wrap", width="100%",
        )

    def render() -> rx.Component:
        return cucm_page(
            cfg.title,
            rx.cond(
                S.has_active,
                rx.vstack(
                    toolbar(),
                    rx.cond(S.error != "",
                            rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                            rx.fragment()),
                    rx.cond(
                        S.loading & (S.items.length() == 0),
                        rx.center(rx.spinner(size="3"), padding="3rem", width="100%"),
                        table(),
                    ),
                    rx.cond(
                        S.hidden_count > 0,
                        rx.text("Showing the first 500 rows. ", S.hidden_count.to_string(),
                                " more match; refine the search to see them. Select-all covers every match.",
                                size="1", color="var(--gray-10)"),
                        rx.fragment(),
                    ),
                    spacing="4", align="start", width="100%",
                ),
                rx.callout(
                    rx.hstack(
                        rx.text("No CUCM connection is set up yet."),
                        rx.link("Add one on the Credentials page", href="/credentials?tab=cucm"),
                        spacing="2",
                    ),
                    icon="info", width="100%",
                ),
            ),
            export_choice_dialog(),
            *([add_dialog()] if cfg.can_add else []),
            *([import_dialog()] if cfg.can_import else []),
            *([bulk_dialog(), confirm_dialog(), result_dialog()] if cfg.can_delete else []),
            *(cfg.extra_dialogs(S, SimpleNamespace(
                dialog=dialog, close_button=close_button, results=results, progress=progress,
                dropzone=dropzone, code_block=code_block)) if cfg.extra_dialogs else []),
            on_connection_change=S.switch_connection,
            on_org_change=S.switch_org,
        )

    render.__name__ = f"{S.__name__}_page"
    return render
