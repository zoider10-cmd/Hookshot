@echo off
rem The game's code (image.bin, loaded at 0x80000000) into the Ghidra project OotRemake, without the whole-program analysis
rem (it ran out of memory, then failed): functions are made and decompiled one at a time when asked (decompile.bat).
rem It stays on this PC.
set JAVA_HOME=C:\Users\beerc\tools\jdk-25.0.5+8
set GHIDRA_HEADLESS_MAXMEM=8G
call "C:\Users\beerc\tools\ghidra_12.2_PUBLIC\support\analyzeHeadless.bat" "C:\Users\beerc\tools\ghidra-projects" OotRemake -import "F:\Games\OOT Remake Rando\image.bin" -loader BinaryLoader -loader-baseAddr 0x80000000 -processor AARCH64:LE:64:v8A -noanalysis -overwrite
