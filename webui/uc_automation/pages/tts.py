"""Tools > Text To U-Law Audio."""

import reflex as rx

from ..components.layout import page
from ..components.tool_widgets import code_block, csv_dropzone, one_multiple_card, field, paste_csv_tabs, run_results
from ..state.tts import TtsState

S = TtsState


def text_to_ulaw() -> rx.Component:
    return page(
        "Tools - Text To U-Law Audio",
        rx.vstack(
            rx.text("Turns text into speech and saves it as a G.711 u-law WAV (8 kHz, 8 bit, mono) for CUCM, Unity "
                    "Connection or CUBE prompts. Everything runs inside this app. The text is spoken by Google "
                    "Text To Speech, so this computer needs internet access and the text is sent to Google.",
                    size="2", color="var(--gray-11)"),
            one_multiple_card(
"One Prompt", [
field("File Name", rx.input(value=S.one_name, on_change=S.set_one_name, width="260px",
                                                placeholder="1001", auto_complete="off"),
                          "Saved as <name>.wav"),
field("Text", rx.text_area(value=S.one_text, on_change=S.set_one_text, width="100%", rows="4",
                                               placeholder="Thank you for calling. For sales, press 1.")),
rx.button(rx.icon("audio-lines", size=16), "Convert", on_click=S.convert_one, disabled=S.busy),
], "Multiple Prompts", [
paste_csv_tabs(
                        S.paste_prompts, lambda v: S.set_paste("prompts", v),
                        "Paste one prompt per line as file name, text. The name ends at the first tab, pipe or comma, "
                        "so the text can contain commas. A header row is optional.",
                        "1001, Thank you for calling. For sales, press 1.\n1099, Our offices are closed.",
                        rx.button(rx.icon("audio-lines", size=16), "Convert", on_click=S.load_text, disabled=S.busy),
                        [
                            rx.text("Header row optional. Columns: Prompt Number (file name), Verbiage (text). Put "
                                    "text that has commas in quotes.", size="2", color="var(--gray-11)"),
                            code_block('Prompt Number,Verbiage\n1001,"Thank you for calling. For sales, press 1."\n'),
                            csv_dropzone("tts_upload"),
                            rx.button(rx.icon("audio-lines", size=16), "Convert",
                                      on_click=S.load_csv(rx.upload_files(upload_id="tts_upload")), disabled=S.busy),
                        ],
                    ),
]),
            run_results(S, "Prompt"),
            rx.cond(
                S.file_count > 0,
                rx.button(rx.icon("download", size=16),
                          rx.cond(S.file_count == 1, "Download WAV", "Download ZIP"), on_click=S.download),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        ),
    )
