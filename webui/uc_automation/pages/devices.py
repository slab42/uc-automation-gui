import reflex as rx

from ..components.crud_page import (
    Column, CrudPageConfig, build_crud_page, dependency_dialogs, dependency_toolbar, form_field, text_input,
)
from ..components.tool_widgets import csv_dropzone, paste_csv_tabs
from ..state.devices import (
    CommonDeviceConfigsState,
    CtiRoutePointsState,
    MppPhonesState,
    PhoneButtonTemplatesState,
    PhonesState,
    SoftkeyTemplatesState,
)


def _hint(text: str) -> rx.Component:
    return rx.text(text, size="1", color="var(--gray-10)")


# --- Phones ---

def _phone_form(S) -> rx.Component:
    return rx.vstack(
        rx.grid(
            form_field("Device name", text_input(S, "name", "SEP0123456789AB")),
            form_field("Product", text_input(S, "product", "Cisco 8845")),
            columns="2", spacing="3", width="100%",
        ),
        form_field("Description", text_input(S, "description")),
        rx.grid(
            form_field("Device pool", text_input(S, "devicePoolName")),
            form_field("Calling search space", text_input(S, "callingSearchSpaceName")),
            form_field("Phone button template", text_input(S, "phoneTemplateName")),
            form_field("Protocol", text_input(S, "protocol")),
            form_field("Security profile", text_input(S, "securityProfileName")),
            form_field("SIP profile", text_input(S, "sipProfileName")),
            form_field("Common phone config", text_input(S, "commonPhoneConfigName")),
            form_field("Location", text_input(S, "locationName")),
            columns="2", spacing="3", width="100%",
        ),
        _hint("Names must match existing CUCM objects. Lines are added separately."),
        spacing="3", align="start", width="100%",
    )


phones = build_crud_page(PhonesState, CrudPageConfig(
    title="Phones", noun="phone", key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Product", "product"), Column("Device pool", "devicePoolName"),
             Column("CSS", "callingSearchSpaceName"), Column("Button template", "phoneTemplateName")],
    add_body=_phone_form,
    import_notes="Only name, product and devicePoolName are required. Modify cannot change name, product or protocol.",
    delete_note="Directory numbers on the phone are not removed.",
))


# --- Softkey templates ---

def _softkey_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "SK-Reception")),
        form_field("Description", text_input(S, "description")),
        form_field("Base template", text_input(S, "baseSoftkeyTemplateName")),
        _hint("The new template copies the softkeys of the base template."),
        spacing="3", align="start", width="100%",
    )


softkey_templates = build_crud_page(SoftkeyTemplatesState, CrudPageConfig(
    title="Softkey Templates", noun="softkey template", key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Base template", "baseSoftkeyTemplateName")],
    add_body=_softkey_form,
    import_notes="Modify can only change the description.",
))


# --- Common device configs ---

def _cdc_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "CDC-HQ")),
        form_field("Softkey template", text_input(S, "softkeyTemplateName")),
        form_field("User locale", text_input(S, "userLocale", "English United States")),
        spacing="3", align="start", width="100%",
    )


common_device_configs = build_crud_page(CommonDeviceConfigsState, CrudPageConfig(
    title="Common Device Configs", noun="common device config", key="name",
    columns=[Column("Name", "name", code=True), Column("Softkey template", "softkeyTemplateName"),
             Column("User locale", "userLocale")],
    add_body=_cdc_form,
    import_notes="Modify changes the softkey template and user locale.",
))


# --- Phone button templates ---

def _pbt_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "PBT-8845-Reception")),
        form_field("Base template", text_input(S, "basePhoneTemplateName", "Cisco 8845 SIP")),
        _hint("The new template copies the buttons of the base template."),
        spacing="3", align="start", width="100%",
    )


def _pbt_toolbar(S) -> list[rx.Component]:
    return dependency_toolbar(S)


def _pbt_dialogs(S, h) -> list[rx.Component]:
    return dependency_dialogs(S, h, "Template dependencies", "Template",
                              "Checking phones, device profiles and universal device templates...")


phone_button_templates = build_crud_page(PhoneButtonTemplatesState, CrudPageConfig(
    title="Phone Button Templates", noun="phone button template", key="name",
    columns=[Column("Name", "name", code=True)],
    add_body=_pbt_form,
    import_notes="Both columns are required. CUCM does not return the base template when listing.",
    can_modify=False,
    extra_toolbar=_pbt_toolbar,
    extra_dialogs=_pbt_dialogs,
))


# --- CTI route points ---

def _ctirp_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "CTIRP_MainAA")),
        form_field("Description", text_input(S, "description")),
        rx.grid(
            form_field("Device pool", text_input(S, "devicePoolName")),
            form_field("Calling search space", text_input(S, "callingSearchSpaceName")),
            form_field("Location", text_input(S, "locationName")),
            columns="2", spacing="3", width="100%",
        ),
        _hint("Names must match existing CUCM objects. Lines are added separately."),
        spacing="3", align="start", width="100%",
    )


cti_route_points = build_crud_page(CtiRoutePointsState, CrudPageConfig(
    title="CTI Route Points", noun="CTI route point", key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Device pool", "devicePoolName"), Column("CSS", "callingSearchSpaceName"),
             Column("Location", "locationName")],
    add_body=_ctirp_form,
    import_notes="name and devicePoolName are required to add. Modify changes the other columns that are filled in.",
    delete_note="Directory numbers on the route point that no other device uses are removed too.",
    can_copy=True,
))


# --- Physical phones (MPP) ---

def _mpp_toolbar(S) -> list[rx.Component]:
    return [
        rx.button(rx.icon("cpu", size=16), "Migrate to MPP load", variant="soft",
                  disabled=S.selected_count == 0, on_click=S.ask_mpp("migrate")),
        rx.button(rx.icon("cloud-upload", size=16), "Prep for Webex Calling", variant="soft",
                  disabled=S.selected_count == 0, on_click=S.ask_mpp("prep")),
    ]


def _mpp_buttons(run) -> rx.Component:
    return rx.hstack(
        rx.button(rx.icon("cpu", size=16), "Migrate to MPP load", on_click=run("migrate"), disabled=MppPhonesState.busy),
        rx.button(rx.icon("cloud-upload", size=16), "Prep for Webex Calling", variant="soft",
                  on_click=run("prep"), disabled=MppPhonesState.busy),
        spacing="3",
    )


def _mpp_dialogs(S, h) -> list[rx.Component]:
    return [
        h.dialog(
            "mppconfirm", S.mpp_action_label + "?",
            rx.vstack(
                rx.text(S.mpp_action_detail, size="2"),
                rx.text("Applies to ", S.selected_count.to_string(),
                        " selected phone(s). The phones reset, which interrupts service for a moment.", size="2"),
                h.progress(),
                h.results(),
                rx.hstack(
                    h.close_button("Cancel"),
                    rx.button(rx.icon("play", size=16), "Run", on_click=S.run_selected, disabled=S.busy),
                    justify="end", spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="480px",
        ),
        h.dialog(
            "mppresult", S.mpp_action_label + ": results",
            rx.vstack(h.results(), rx.hstack(h.close_button(), justify="end", width="100%"),
                      spacing="3", align="start", width="100%"),
        ),
    ]


def _mpp_search_by(S) -> rx.Component:
    return rx.segmented_control.root(
        rx.segmented_control.item("Name Or Description", value="name"),
        rx.segmented_control.item("Device Pool", value="pool"),
        value=S.search_by, on_change=S.set_search_by,
    )


def _mpp_tabs(S, h, search_body: rx.Component) -> rx.Component:
    bulk = rx.vstack(
        paste_csv_tabs(
            S.paste_phones, S.set_paste_phones,
            "One phone per line (commas, tabs and spaces also separate). Device names work with or without "
            "SEP, and a MAC address in any format becomes SEP plus the MAC. A header row is optional.",
            "SEP0123456789AB\n0123456789AC\n0123.4567.89ad",
            _mpp_buttons(lambda a: S.list_run(a)),
            [
                rx.text("One column: phone (mac, device or name also work). The file fills the Paste Text box.",
                        size="2", color="var(--gray-11)"),
                h.code_block(S.template_text),
                csv_dropzone("mpp_upload"),
                rx.button(rx.icon("upload", size=16), "Load CSV",
                          on_click=S.load_phone_csv(rx.upload_files(upload_id="mpp_upload"))),
            ],
            paste_top=rx.text(S.phone_count.to_string(), " phone(s) in the list", size="2", color="var(--gray-11)"),
        ),
        rx.text("Migrate sets the MPP 12.0(7) load. Prep sets the 14.4(1) load and the Webex cloud "
                "load server and disables peer firmware sharing. Both reset the phones.",
                size="1", color="var(--gray-10)"),
        h.progress(),
        h.results(),
        spacing="3", align="start", width="100%",
    )
    return rx.tabs.root(
        rx.tabs.list(rx.tabs.trigger("Search", value="search"), rx.tabs.trigger("Bulk", value="bulk")),
        rx.tabs.content(rx.box(search_body, padding_top="1rem"), value="search"),
        rx.tabs.content(rx.box(bulk, padding_top="1rem"), value="bulk"),
        default_value="search", width="100%",
    )


mpp_phones = build_crud_page(MppPhonesState, CrudPageConfig(
    title="Physical Phones (MPP)", noun="phone", key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Model", "model"), Column("Device pool", "devicePoolName"),
             Column("Active Load ID", "activeLoad"), Column("Load Override", "loadInformation")],
    can_add=False, can_import=False, can_modify=False, can_delete=False, search_first=True, wrap_body=_mpp_tabs, search_options=_mpp_search_by,
    extra_toolbar=_mpp_toolbar, extra_dialogs=_mpp_dialogs,
))
