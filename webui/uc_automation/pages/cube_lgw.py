"""CUBE > Configuration > Webex Local Gateway Config Generator."""

import reflex as rx

from ..backend import cube_lgw as lgw
from ..components.cube_nav import cube_page
from ..components.tool_widgets import code_block, field
from ..state.cube_lgw import LgwState

S = LgwState


def _text(key: str, label: str, hint: str = "", placeholder: str = "") -> rx.Component:
    return field(label, rx.input(value=S.form[key], on_change=lambda v: S.set_field(key, v), placeholder=placeholder,
                                 auto_complete="off", width="100%"), hint)


def _secret(label: str, on_change, hint: str = "") -> rx.Component:
    return field(label, rx.input(type="password", key=S.password_key.to_string(), on_change=on_change,
                                 auto_complete="new-password", width="100%"), hint)


def _grid(*children: rx.Component) -> rx.Component:
    return rx.grid(*children, columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%")


def lgw_config() -> rx.Component:
    webex = rx.card(
        rx.vstack(
            rx.heading("Webex Local Gateway Trunk", size="4"),
            rx.text("Enter the values shown when the trunk was added in Control Hub.", size="2", color="var(--gray-11)"),
            _grid(
                _text("tenant_id", "Tenant ID", "Used for the tenant, SIP profile, URI and dial peer IDs"),
                _text("otg", "Trunk Group OTG/DTG"),
                _text("proxy", "Outbound Proxy Address"),
                _text("domain", "Registrar Domain"),
                _text("lgu_raw", "Line/Port", "Anything after an @ is dropped"),
                _text("username", "Username"),
                _secret("Password", S.set_password, "Shown in the generated config"),
                _secret("STUN Password", S.set_stun_password, "Optional. Random shared secret for STUN"),
                _text("out_interface", "Webex Bound Interface", "Binding on the outside dial peer"),
                _text("public_gateway", "Public Gateway IP", "Next hop for the Webex network routes"),
            ),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )
    cucm = rx.card(
        rx.vstack(
            rx.heading("CUCM Trunk", size="4"),
            rx.text("Up to 6 CUCM nodes running the CallManager service. Leave unused rows blank.", size="2",
                    color="var(--gray-11)"),
            _grid(
                _text("cucm_dialpeer_id", "CUCM Dial Peer", "Used for the CUCM tenant, URI and dial peer IDs"),
                _text("inside_interface", "CUCM Bound Interface", "Binding on the inside dial peer"),
            ),
            *[
                _grid(
                    _text(f"cm{n}host", f"CUCM {n} Hostname"),
                    _text(f"cm{n}ip", f"CUCM {n} IP"),
                )
                for n in range(1, lgw.CUCM_SLOTS + 1)
            ],
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )
    return cube_page("Webex Local Gateway Config Generator", rx.vstack(
        rx.text("Generates the CUBE configuration for a registration based Webex Calling local gateway with a CUCM trunk "
                "on port 5065. Example only: review it before use, a SIP PSTN provider may need more.",
                size="2", color="var(--gray-11)"),
        webex,
        cucm,
        rx.hstack(
            rx.button(rx.icon("file-cog", size=16), "Generate", on_click=S.generate),
            rx.button(rx.icon("eraser", size=16), "Clear", variant="soft", color_scheme="gray", on_click=S.clear),
            spacing="3",
        ),
        rx.cond(
            S.config_view != "",
            rx.vstack(
                rx.hstack(
                    rx.heading("Generated Config", size="4"),
                    rx.spacer(),
                    rx.button(rx.icon("download", size=16), "Export TXT", variant="soft", on_click=S.export_txt),
                    align="center", width="100%",
                ),
                code_block(S.config_view),
                spacing="3", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    ))
