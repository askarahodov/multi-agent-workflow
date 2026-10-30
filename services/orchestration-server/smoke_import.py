from orchestration_server.api import build_app

app = build_app()
print("api import ok", app.title)