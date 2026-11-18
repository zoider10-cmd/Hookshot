| Date | Build | OS / desktop | GPU / driver | CPU / RAM | Settings | Where | Result |
|---|---|---|---|---|---|---|---|
| 2026-11-13 | main fbd42024 | Linux (CachyOS, kernel 7.3.3), KDE Wayland | RTX 3060 Laptop 6 GB, 620.70.06 | Ryzen 7 6800H, 15 GB | 1920x1080, upscaler Off, no frame generation, `HOS_FPS_MAX=1000` (uncapped), `HOS_AUDIO=0` | The start: intro and title, 75 s a run, frames from 20 s on (`RX_VK_FRAME_LOG`), 3 runs interleaved with the two others | Median of 3: 150.9 fps, 1% low 96.7, frame time 5.69 ms (run perf-stats-main-fbd4) |
