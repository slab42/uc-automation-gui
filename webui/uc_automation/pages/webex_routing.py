import reflex as rx

from ..backend.webex_groups import POLICIES
from ..backend.webex_routing import NUMBER_STATES, NUMBER_TYPES, USAGE_TYPES
from ..components.tool_widgets import code_block, csv_dropzone, field, file_dropzone, run_results
from ..components.webex_nav import GROUPS, webex_page
from ..components.webex_picker import picker
from ..state.webex_groups import CallQueuesState, HuntGroupsState, VirtualLinesState
from ..state.webex_routing import AddNumbersState, CallForwardState, WebexSession


def need_login(body: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.cond(
            WebexSession.webex_ok,
            rx.fragment(),
            rx.callout(
                rx.hstack(rx.text(WebexSession.webex_message), rx.link("Open Credentials", href="/credentials"),
                          spacing="2"),
                icon="triangle-alert", color_scheme="red", width="100%",
            ),
        ),
        body,
        spacing="4", align="start", width="100%",
    )


def _home_card(icon, title, desc, href):
    return rx.link(
        rx.card(
            rx.hstack(
                rx.icon(icon, size=20),
                rx.vstack(rx.text(title, weight="bold"), rx.text(desc, size="2", color="var(--gray-11)"),
                          spacing="0", align="start"),
                spacing="3", align="center",
            ),
            _hover={"border_color": "var(--accent-8)"}, width="100%",
        ),
        href=href, underline="none",
    )


def webex_home() -> rx.Component:
    return webex_page(
        "Webex",
        rx.vstack(
            rx.text("Webex Calling / Control Hub", color="var(--gray-11)"),
            *[
                rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[_home_card(icon, name, desc, route) for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"), spacing="4", width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                )
                for label, items in GROUPS
            ],
            spacing="4", align="start",
        ),
    )


def add_numbers() -> rx.Component:
    S = AddNumbersState
    return webex_page(
        "Add Numbers",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("One number", size="4"),
                    rx.grid(
                        field("Location name", rx.input(value=S.form_location, on_change=S.set_form_location,
                                                        width="100%"), "Must already exist in Control Hub."),
                        field("Phone number", rx.input(value=S.form_number, on_change=S.set_form_number,
                                                       width="100%", placeholder="12704435531"),
                              "10 digit US numbers get a leading 1; the + is added for you."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    rx.hstack(
                        field("Number type", rx.select(list(NUMBER_TYPES), value=S.form_type,
                                                       on_change=S.set_form_type)),
                        field("Usage", rx.select(list(USAGE_TYPES), value=S.form_usage, on_change=S.set_form_usage)),
                        field("State", rx.select(list(NUMBER_STATES), value=S.form_state,
                                                 on_change=S.set_form_state)),
                        spacing="4", wrap="wrap",
                    ),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add number",
                              on_click=S.add_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("From CSV", size="4"),
                    rx.text("Header row required. Only locationId and phoneNumber are needed (DID, NONE, ACTIVE "
                            "are then assumed); the other columns are optional.", size="2", color="var(--gray-11)"),
                    code_block("locationId,phoneNumber,numberType,numberUsageType,state\n"
                               "Location1,12704435531,DID,NONE,ACTIVE\n"),
                    csv_dropzone("numbers_upload"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), "Add numbers",
                              on_click=S.add_from_csv(rx.upload_files(upload_id="numbers_upload")),
                              disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Number"),
            spacing="4", align="start", width="100%",
        )),
    )


def call_forward() -> rx.Component:
    S = CallForwardState
    setting = S.cf_mode == "set"
    return webex_page(
        "Call Forward",
        need_login(rx.vstack(
            rx.segmented_control.root(
                rx.segmented_control.item("Set Call Forward All", value="set"),
                rx.segmented_control.item("Remove Call Forward All", value="remove"),
                value=S.cf_mode, on_change=S.set_cf_mode,
            ),
            rx.card(
                rx.vstack(
                    rx.text(
                        rx.cond(
                            setting,
                            "Looks up each number's owner (person, workspace, virtual line, hunt group, call queue "
                            "or auto attendant) and forwards all calls to the prefix followed by the number.",
                            "Looks up each number's owner and switches Call Forward All off.",
                        ),
                        size="2", color="var(--gray-11)",
                    ),
                    rx.cond(
                        setting,
                        field("Forward prefix", rx.input(value=S.cf_prefix, on_change=S.set_cf_prefix, width="16rem"),
                              "Added in front of the number to make the destination."),
                        rx.fragment(),
                    ),
                    field("Phone number", rx.input(value=S.cf_number, on_change=S.set_cf_number, width="100%",
                                                   placeholder="12704435531 or an extension")),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("play", size=16)),
                              rx.cond(setting, "Set forward", "Remove forward"),
                              on_click=S.run_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("From CSV", size="4"),
                    rx.text("Header row required. The column named phoneNumber or pattern is used, "
                            "otherwise the first column.", size="2", color="var(--gray-11)"),
                    code_block("phoneNumber\n12704435531\n12704435532\n"),
                    csv_dropzone("forward_upload"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                              rx.cond(setting, "Set forward for all", "Remove forward for all"),
                              on_click=S.run_csv(rx.upload_files(upload_id="forward_upload")), disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Number"),
            spacing="4", align="start", width="100%",
        )),
    )


# --- Call Queues, Hunt Groups, Virtual Lines ---

_CREATE_HEADER = "name,location,firstName,lastName,phoneNumber,extension,policy,destination,agent1,agent2,agent3\n"


def _create_card(S, noun: str, upload_id: str, example: str, agent_help: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading(f"Create {noun}s from CSV", size="4"),
            rx.text(
                "Header row required. name, location (a location name), policy and destination are required, plus "
                "at least one agent column. Add as many agent1, agent2, ... columns as you need. "
                f"policy is one of {', '.join(POLICIES)}. destination is the no-answer and business continuity "
                f"forward number. {agent_help}",
                size="2", color="var(--gray-11)",
            ),
            code_block(_CREATE_HEADER + example),
            file_dropzone(upload_id, {"text/csv": [".csv"]}, "Drop a CSV here or click to choose"),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), f"Create {noun}s",
                      on_click=S.create_from_csv(rx.upload_files(upload_id=upload_id)), disabled=S.busy),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _agents_card(S, noun: str, upload_id: str, agent_help: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading(f"Replace {noun} agents", size="4"),
            rx.text("Select the " + noun + " above, then upload a CSV. The agents in the CSV REPLACE the current "
                    "agent list. " + agent_help, size="2", color="var(--gray-11)"),
            code_block("agent\njsmith@example.com\nadoe@example.com\n"),
            file_dropzone(upload_id, {"text/csv": [".csv"]}, "Drop a CSV here or click to choose"),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("users", size=16)), "Replace agents",
                      on_click=S.update_agents(rx.upload_files(upload_id=upload_id)),
                      disabled=S.busy | ~S.has_selection),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def call_queues() -> rx.Component:
    S = CallQueuesState
    creating = S.mode == "create"
    return webex_page(
        "Call Queues",
        need_login(rx.vstack(
            rx.segmented_control.root(
                rx.segmented_control.item("Create", value="create"),
                rx.segmented_control.item("Update agents", value="agents"),
                value=S.mode, on_change=S.set_mode,
            ),
            rx.cond(
                creating,
                _create_card(S, "call queue", "queue_create_upload",
                             "Support,Dallas,Support,Queue,12704435531,5000,CIRCULAR,12704439999,"
                             "jsmith@example.com,12704435532\n",
                             "An agent is an email address, or the phone number of a virtual line. Agents that "
                             "cannot be found are skipped and listed in the result."),
                rx.vstack(
                    picker(S, "Call queues"),
                    _agents_card(S, "call queue", "queue_agents_upload", "Agents must be email addresses."),
                    spacing="4", width="100%",
                ),
            ),
            run_results(S, "Call queue"),
            spacing="4", align="start", width="100%",
        )),
    )


def hunt_groups() -> rx.Component:
    S = HuntGroupsState
    plan = rx.card(
        rx.vstack(
            rx.heading("Migrate to a call queue", size="4"),
            rx.text("Reads the selected hunt group, saves a JSON backup, deletes the hunt group (this frees its "
                    "name, number and extension), creates a call queue with the same settings and joins the "
                    "agents.", size="2", color="var(--gray-11)"),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("search", size=16)), "Review",
                      on_click=S.review_migration, disabled=S.busy | ~S.has_selection),
            rx.cond(
                S.plan_for == S.selected_id,
                rx.vstack(
                    rx.foreach(S.plan_lines, lambda t: rx.text(t, size="2")),
                    rx.cond(
                        S.plan_notes.length() > 0,
                        rx.callout.root(
                            rx.callout.icon(rx.icon("triangle-alert")),
                            rx.callout.text(
                                rx.text("Not migrated (no call queue equivalent):", weight="bold"),
                                rx.foreach(S.plan_notes, lambda t: rx.text("- " + t, size="2")),
                            ),
                            color_scheme="amber", width="100%",
                        ),
                        rx.fragment(),
                    ),
                    rx.button(rx.icon("arrow-right-left", size=16), "Migrate...", color_scheme="red",
                              on_click=S.set_confirm_open(True), disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )
    confirm = rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete the hunt group and create the call queue?"),
            rx.alert_dialog.description(
                "The hunt group " + S.selected_label + " is deleted first. If creating the queue then fails, the "
                "hunt group is gone and has to be re-created from the JSON backup saved in webui/logs."),
            rx.hstack(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.set_confirm_open(False)),
                rx.button("Delete and migrate", color_scheme="red", on_click=S.run_migration),
                spacing="3", justify="end", margin_top="1rem",
            ),
        ),
        open=S.confirm_open,
    )
    return webex_page(
        "Hunt Groups",
        need_login(rx.vstack(
            rx.segmented_control.root(
                rx.segmented_control.item("Create", value="create"),
                rx.segmented_control.item("Update agents", value="agents"),
                rx.segmented_control.item("Migrate to Call Queue", value="migrate"),
                value=S.mode, on_change=S.set_mode,
            ),
            rx.cond(
                S.mode == "create",
                _create_card(S, "hunt group", "hunt_create_upload",
                             "Sales,Dallas,Sales,Group,12704435541,6000,CIRCULAR,12704439999,"
                             "jsmith@example.com,6001\n",
                             "An agent is an email address, or an extension. Agents that cannot be found are "
                             "skipped and listed in the result."),
                rx.vstack(
                    picker(S, "Hunt groups"),
                    rx.cond(
                        S.mode == "agents",
                        _agents_card(S, "hunt group", "hunt_agents_upload",
                                     "An agent is an email address, or the phone number of a virtual line."),
                        plan,
                    ),
                    spacing="4", width="100%",
                ),
            ),
            run_results(S, "Hunt group"),
            confirm,
            spacing="4", align="start", width="100%",
        )),
    )


def virtual_lines() -> rx.Component:
    S = VirtualLinesState
    return webex_page(
        "Virtual Lines",
        need_login(rx.vstack(
            picker(S, "Virtual lines"),
            rx.card(
                rx.vstack(
                    rx.heading("Voicemail greeting", size="4"),
                    rx.text("Select a virtual line above, then upload a .wav file of 5000 KB or less. The same file "
                            "becomes the busy and the unanswered voicemail greeting, and both are set to Custom. "
                            "Whether each is enabled, and the number of rings, are left as they are.",
                            size="2", color="var(--gray-11)"),
                    file_dropzone("greeting_upload", {"audio/wav": [".wav"], "audio/x-wav": [".wav"]},
                                  "Drop a .wav here or click to choose"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), "Upload greeting",
                              on_click=S.upload_greeting(rx.upload_files(upload_id="greeting_upload")),
                              disabled=S.busy | ~S.has_selection),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Virtual line"),
            spacing="4", align="start", width="100%",
        )),
    )
