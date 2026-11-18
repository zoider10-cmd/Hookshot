| Date | Build | OS / desktop | GPU / driver | CPU / RAM | Settings | Where | Result |
|---|---|---|---|---|---|---|---|
| 2026-11-15 | main 9e6f231d0ded199793e8270d20ec60cdb765d28f production sources with the new test from ed097a30 | Windows; OS build unknown; no window | Not used; game-free fixture | CPU/RAM not recorded | Python 3.14; LLVM-MinGW 20261104; fake SDL; 70 recording endpoints | tests/test_audio_in.py, unchanged-main control | win-control01: expected failure at expanded-list/boundary assertion, native exit 43; Python driver exit 1; no real audio capture |
