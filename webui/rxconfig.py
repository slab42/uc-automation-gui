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
    # Keep page state in memory only. The default disk mode pickles every state var, including the
    # backend-only passwords, into .states/ (CLAUDE.md: passwords are never written outside credentials.env).
    state_manager_mode="memory",
)
