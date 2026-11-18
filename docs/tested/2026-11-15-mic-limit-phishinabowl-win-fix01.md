| Date | Build | OS / desktop | GPU / driver | CPU / RAM | Settings | Where | Result |
|---|---|---|---|---|---|---|---|
| 2026-11-15 | ed097a30aeaa424cc25a7d9ade43b110312877fc | Windows; OS build unknown; no window | Not used; game-free fixture | CPU/RAM not recorded | Python 3.14; LLVM-MinGW 20261104; fake SDL; 70 recording endpoints | tests/test_audio_in.py, rebased mic-limit branch | win-fix01: 55 native input-stream cases and expanded-device menu fixture passed; includes high index, endpoint 63, truncation, reconnect and Default; no real audio capture |
