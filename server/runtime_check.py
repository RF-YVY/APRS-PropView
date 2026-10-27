"""Offline smoke check for source and frozen releases; never starts radio services."""
import json
import tempfile
import sys
from pathlib import Path


async def check_runtime():
    from server.app import create_app
    from server.config import Config
    from server.database import Database
    from server.packet_handler import PacketHandler
    from server.station_tracker import StationTracker
    from server.websocket_manager import WebSocketManager
    # Exercise native libraries and desktop dependencies in the packaged build.
    import netCDF4
    import PIL.Image
    import certifi
    if sys.platform == 'win32':
        import tkinter
        import pystray

    config = Config()
    database = Database(':memory:')
    sockets = WebSocketManager()
    try:
        await database.initialize()
        tracker = StationTracker(database, config, sockets)
        handler = PacketHandler(config, tracker, None, None, sockets)
        with tempfile.TemporaryDirectory(prefix='propview-runtime-check-') as directory:
            app = create_app(config, database, tracker, sockets, handler,
                             config_path=Path(directory) / 'config.toml')
            paths = {getattr(route, 'path', '') for route in app.routes}
            assert {'/api/auth/login', '/api/map-tiles/{z}/{x}/{y}', '/api/update-install'} <= paths
            assert Path(certifi.where()).is_file()
            assert app.state.public_limits.MAX_ACTIVE == 16
        print(json.dumps({'ok': True, 'checks': ['database', 'application', 'resource-limits',
                                               'certificate-bundle', 'native-libraries', 'desktop-imports']}))
    finally:
        await sockets.close()
        await database.close()
