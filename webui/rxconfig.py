import reflex as rx

config = rx.Config(
    app_name="uc_automation",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="inherit", accent_color="cyan", gray_color="slate", radius="large"),
        ),
    ],
    telemetry_enabled=False,
)
