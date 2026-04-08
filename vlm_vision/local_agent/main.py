"""
Entry point. Wires all components and runs the pick loop for each bay.
"""
import asyncio
import threading
import time
from queue import Queue
from typing import Optional

import uvicorn

from local_agent.camera_agent import CameraAgent
from local_agent.config import Config
from local_agent.detector import Detector
from local_agent.display_server import app, broadcast
from local_agent.models import BayStatus, PickOrder
from local_agent.modula_client import ModulaClient
from local_agent.offline_queue import OfflineQueue
from local_agent.pick_verifier import PickVerifier

FRAME_QUEUE_SIZE = 3
PICK_SETTLE_SECONDS = 1.5  # wait after motion stops before comparing before/after


def run_bay(
    bay_id: int,
    camera_id: int,
    config: Config,
    detector: Detector,
    modula: ModulaClient,
    queue: OfflineQueue,
    loop: asyncio.AbstractEventLoop,
):
    frame_queue: Queue = Queue(maxsize=FRAME_QUEUE_SIZE)
    camera = CameraAgent(camera_id=camera_id, frame_queue=frame_queue, fps=config.detection_fps)
    camera.start()
    verifier = PickVerifier(bay_id=bay_id, worker_id="operator")

    active_order: Optional[PickOrder] = None

    while True:
        # Poll for active pick order
        try:
            active_order = modula.fetch_active_order(bay_id=bay_id)
        except Exception:
            pass  # network error — keep last known order

        if frame_queue.empty():
            time.sleep(0.05)
            continue

        frame = frame_queue.get()
        detections = detector.detect(frame)

        status = BayStatus.ACTIVE if active_order else BayStatus.WAITING
        asyncio.run_coroutine_threadsafe(
            broadcast(bay_id, status, detections, active_order), loop
        )

        if active_order is None:
            continue

        # Capture before snapshot, wait for pick, capture after snapshot
        before = detections
        time.sleep(PICK_SETTLE_SECONDS)

        if not frame_queue.empty():
            after_frame = frame_queue.get()
            after = detector.detect(after_frame)
            event = verifier.verify(order=active_order, before=before, after=after)

            if event:
                queue.enqueue(event)
                try:
                    modula.confirm_pick(order_id=event.order_id, result=event.result)
                except Exception:
                    pass  # queued locally; cloud sync handles retry
                asyncio.run_coroutine_threadsafe(
                    broadcast(bay_id, BayStatus.CONFIRMING, after, None), loop
                )
                active_order = None


def main():
    config = Config.from_env()
    detector = Detector(model_path=config.model_path)
    modula = ModulaClient(base_url=config.modula_wms_url)
    queue = OfflineQueue(db_path=config.db_path)

    loop = asyncio.new_event_loop()

    for i, camera_id in enumerate(config.camera_ids):
        bay_id = i + 1
        t = threading.Thread(
            target=run_bay,
            args=(bay_id, camera_id, config, detector, modula, queue, loop),
            daemon=True,
        )
        t.start()

    # Run FastAPI WebSocket server on the main thread's event loop
    asyncio.set_event_loop(loop)
    config_uvicorn = uvicorn.Config(
        app, host="0.0.0.0", port=config.websocket_port, loop="asyncio"
    )
    server = uvicorn.Server(config_uvicorn)
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
