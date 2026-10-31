"""Tools > Make ISO Bootable."""

import reflex as rx

from ..components.layout import page
from ..state.bootable import BootableState

S = BootableState


def make_bootable() -> rx.Component:
    return page(
        "Tools - Make ISO Bootable",
        rx.vstack(
            rx.text("Adds the missing boot record to a Cisco CUCM, IMP or CUC install ISO so a virtual or physical "
                    "machine can boot from it. Everything runs inside this app. The new file downloads "
                    "automatically as Bootable_<name>.iso. Nothing is kept: the upload, the working copy and the "
                    "result are deleted when the download ends (within a minute).",
                    size="2", color="var(--gray-11)"),
            rx.callout("These ISOs are several GB. The computer running this app needs free temporary disk space of "
                       "about twice the ISO size while it works.", icon="info", width="100%"),
            rx.card(
                rx.vstack(
                    rx.upload(
                        rx.vstack(
                            rx.icon("upload", size=22, color="var(--gray-10)"),
                            rx.text("Drop the ISO here or click to choose", size="2"),
                            align="center", spacing="1",
                        ),
                        id="iso_upload",
                        accept={"application/x-iso9660-image": [".iso"], "application/octet-stream": [".iso"]},
                        max_files=1, multiple=False, max_size=32 * 1024 ** 3,
                        padding="1.25rem", border="1px dashed var(--gray-7)", border_radius="var(--radius-3)",
                        width="100%",
                    ),
                    rx.foreach(rx.selected_files("iso_upload"), lambda f: rx.badge(f, variant="soft")),
                    rx.button(
                        rx.cond(S.busy, rx.spinner(size="2"), rx.icon("disc", size=16)), "Make Bootable",
                        on_click=[
                            S.begin(rx.selected_files("iso_upload")),
                            S.make(rx.upload_files_chunk(upload_id="iso_upload",
                                                         on_upload_progress=S.on_upload_progress)),
                        ],
                        disabled=S.busy,
                    ),
                    rx.cond(
                        S.busy,
                        rx.vstack(
                            rx.hstack(
                                rx.text(S.progress, size="2"),
                                rx.cond(S.upload_pct < 100, rx.text(S.upload_pct.to_string() + "%", size="2", weight="medium"),
                                        rx.fragment()),
                                spacing="2",
                            ),
                            rx.cond(
                                S.upload_pct < 100,
                                rx.vstack(
                                    rx.progress(value=S.upload_pct, width="100%"),
                                    rx.button("Cancel Upload", variant="soft", color_scheme="gray", size="1",
                                              on_click=[rx.cancel_upload("iso_upload"), S.cancel]),
                                    spacing="2", width="100%",
                                ),
                                rx.fragment(),
                            ),
                            spacing="2", width="100%",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.done_message != "",
                rx.callout(
                    rx.hstack(rx.text(S.done_message),
                              rx.link("Download did not start? Click here", href=S.download_url), spacing="3",
                              wrap="wrap"),
                    icon="check", color_scheme="green", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        ),
    )
