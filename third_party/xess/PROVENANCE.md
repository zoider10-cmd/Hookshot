# Intel XeSS Super Resolution API headers

Intel's MIT-licensed XeSS-SR API headers, the Vulkan path only: `inc/xess/xess.h`, `inc/xess/xess_vk.h` and their licence
`inc/MIT.txt`, at the same paths as in <https://github.com/intel/xess>, commit `de0fb9c1c510661c571164e1418ceca8101dab69`
(main, after the 3.0.2 release). Licence: MIT (`inc/MIT.txt`, Copyright (c) 2026 Intel Corporation; each header says
`SPDX-License-Identifier: MIT`).

Not the `v3.0.2` tag: its headers carry Intel's proprietary notice, not the MIT one; the commit above is the first whose
`inc/` is MIT. Only these headers are taken. Nothing else of the SDK is here: not the D3D12 or D3D11 headers, not XeSS Frame
Generation or XeLL (D3D12 only), not the import library, and never `libxess.dll`, which is Intel's under the Intel Simplified
Software License: the player puts it beside the game, or a build with `--fetch-xess-runtime` downloads it on the player's PC
from this same commit, checked against its SHA-256 (`scripts/xess_sdk.py`; README, Intel XeSS). `gpu/vk/vk_xess.cpp` compiles
against these headers for their types and loads the player's `libxess.dll` at run time through `GetProcAddress`.

The files are upstream's, unmodified but for their line endings: upstream stores them with CRLF, and this repository keeps
text files with LF (`.gitattributes`). With CRLF put back they are upstream's blobs byte for byte (git blob ids:
`inc/xess/xess.h` 5d16b101994190f22cdf43e695ca1fccc9a79a1d, `inc/xess/xess_vk.h` 1349d81d4474975e8dccd5783ceae5d8dc2d9de8,
`inc/MIT.txt` 478eb06298afb556e6248b434b7aec2c93ea4bdb).

Nothing in this folder is edited. A change belongs in a new folder with its own note, per `CONTRIBUTING.md`.

tree-sha256: 2ad625a8596454f22f0474f3af8d3b121b0ed746428f2bac0cadd4bfd580a91d
