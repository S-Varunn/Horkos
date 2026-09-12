import logging
from aiohttp import web
from typing import Optional, Callable, Awaitable, Dict, Any

logger = logging.getLogger("CommitmentRadar.OAuthServer")

SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Google Calendar Connected | Commitment Radar</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        .card {
            background: #1e293b;
            border: 1px solid #334155;
            padding: 2.5rem;
            border-radius: 16px;
            text-align: center;
            max-width: 440px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
        }
        .icon {
            font-size: 3.5rem;
            margin-bottom: 1rem;
        }
        h1 {
            color: #38bdf8;
            font-size: 1.5rem;
            margin-bottom: 0.75rem;
        }
        p {
            color: #94a3b8;
            line-height: 1.5;
            font-size: 0.95rem;
        }
        .badge {
            background: #065f46;
            color: #34d399;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            display: inline-block;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🎯</div>
        <h1>Calendar Connected!</h1>
        <p>Your Google Calendar is now linked to <strong>Commitment Radar</strong>.</p>
        <p>Your commitments will automatically sync with native notifications and popup reminders.</p>
        <div class="badge">Active & Ready</div>
        <p style="margin-top: 1.5rem; font-size: 0.85rem; color: #64748b;">You can safely close this window and return to Discord.</p>
    </div>
</body>
</html>
"""

ERROR_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Authentication Failed | Commitment Radar</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; border: 1px solid #ef4444; padding: 2.5rem; border-radius: 16px; text-align: center; max-width: 440px; }
        h1 { color: #ef4444; }
        p { color: #94a3b8; }
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 3rem;">❌</div>
        <h1>Connection Failed</h1>
        <p>{error_msg}</p>
        <p>Please try running <code>/calendar-connect</code> again in Discord.</p>
    </div>
</body>
</html>
"""


class OAuthCallbackServer:
    def __init__(
        self,
        port: int = 8080,
        token_handler: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None
    ):
        self.port = port
        self.token_handler = token_handler
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

    async def _handle_callback(self, request: web.Request) -> web.Response:
        code = request.query.get("code")
        state = request.query.get("state")  # Contains discord_user_id
        error = request.query.get("error")

        if error:
            html = ERROR_HTML.replace("{error_msg}", f"Google returned error: {error}")
            return web.Response(text=html, content_type="text/html", status=400)

        if not code or not state:
            html = ERROR_HTML.replace("{error_msg}", "Missing code or state parameter from Google OAuth callback.")
            return web.Response(text=html, content_type="text/html", status=400)

        discord_user_id = state
        try:
            if self.token_handler:
                result = await self.token_handler(code, discord_user_id)
                if not result.get("success"):
                    err = result.get("error", "Failed to store token")
                    html = ERROR_HTML.replace("{error_msg}", err)
                    return web.Response(text=html, content_type="text/html", status=500)

            return web.Response(text=SUCCESS_HTML, content_type="text/html")
        except Exception as e:
            logger.error(f"Error handling OAuth callback for user {discord_user_id}: {e}", exc_info=True)
            html = ERROR_HTML.replace("{error_msg}", str(e))
            return web.Response(text=html, content_type="text/html", status=500)

    async def start(self):
        """Starts the aiohttp OAuth callback listener."""
        app = web.Application()
        app.router.add_get("/oauth/callback", self._handle_callback)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        try:
            await self.site.start()
            logger.info(f"OAuthCallbackServer running on http://localhost:{self.port}/oauth/callback")
        except OSError as e:
            logger.warning(f"Could not bind OAuthCallbackServer to port {self.port} ({e}). Manual code flow will be available.")

    async def stop(self):
        """Stops the OAuth callback listener."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("OAuthCallbackServer stopped.")
