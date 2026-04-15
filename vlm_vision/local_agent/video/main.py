# vlm_vision/local_agent/video/main.py
"""
Entry point for Process 3 — Video Recorder.
Starts multi-camera recording, video segmentation, cloud upload,
and retention management.
"""
import os
import signal
import sys
import threading
import time


def main():
    fps = int(os.environ.get("VIDEO_FPS", "15"))
    resolution_str = os.environ.get("VIDEO_RESOLUTION", "1920x1080")
    w, h = (int(x) for x in resolution_str.split("x"))
    resolution = (w, h)
    segment_minutes = int(os.environ.get("VIDEO_SEGMENT_MINUTES", "5"))
    codec = os.environ.get("VIDEO_CODEC", "h264")
    bitrate = int(os.environ.get("VIDEO_BITRATE", "2000000"))
    retention_days = int(os.environ.get("VIDEO_RETENTION_DAYS", "60"))
    local_buffer_hours = int(os.environ.get("VIDEO_LOCAL_BUFFER_HOURS", "24"))
    cloud_url = os.environ.get("CLOUD_SYNC_URL", "http://localhost:8080")
    output_dir = os.environ.get("VIDEO_OUTPUT_DIR", "data/video")
    clip_dir = os.environ.get("VIDEO_CLIP_DIR", "data/clips")
    db_path = os.environ.get("VIDEO_DB_PATH", "data/video_queue.db")

    # Parse camera IDs from env (comma-separated)
    camera_ids_str = os.environ.get("VIDEO_CAMERA_IDS", "0,1")
    camera_ids = [int(x.strip()) for x in camera_ids_str.split(",")]

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(clip_dir, exist_ok=True)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    from local_agent.video.cloud_uploader import CloudUploader
    from local_agent.video.multi_camera_recorder import MultiCameraRecorder
    from local_agent.video.retention_manager import RetentionManager
    from local_agent.video.video_segmenter import VideoSegmenter

    # Cloud uploader (background thread)
    uploader = CloudUploader(
        cloud_base_url=cloud_url,
        db_path=db_path,
    )
    uploader.start()

    # Video segmenter (receives frames, writes segments, notifies uploader)
    segmenter = VideoSegmenter(
        output_dir=output_dir,
        segment_minutes=segment_minutes,
        fps=fps,
        resolution=resolution,
        retention_days=retention_days,
        on_segment_complete=uploader.enqueue,
    )

    # Multi-camera recorder (captures frames, passes to segmenter)
    recorder = MultiCameraRecorder(
        camera_ids=camera_ids,
        fps=fps,
        resolution=resolution,
        codec=codec,
        bitrate=bitrate,
        on_frame=segmenter.write_frame,
    )

    # Retention manager (periodic cleanup)
    retention = RetentionManager(
        db_path=db_path,
        local_buffer_hours=local_buffer_hours,
        retention_days=retention_days,
    )

    def retention_loop():
        while not stop_event.is_set():
            retention.cleanup_local()
            stop_event.wait(timeout=3600)  # run hourly

    stop_event = threading.Event()
    retention_thread = threading.Thread(target=retention_loop, daemon=True)
    retention_thread.start()

    # Start recording
    print(f"Video Recorder starting: {len(camera_ids)} cameras at {fps} FPS, {resolution[0]}x{resolution[1]}")
    print(f"Segments: {segment_minutes} min, retention: {retention_days} days")
    print(f"Output: {output_dir}, DB: {db_path}")
    recorder.start()

    # Graceful shutdown
    def shutdown(signum, frame):
        print("\nShutting down Video Recorder...")
        stop_event.set()
        recorder.stop()
        segmenter.close_all()
        uploader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep main thread alive
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
