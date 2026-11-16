@echo off
rem decompile.bat <out file> <address>...: Ghidra's C of the game's functions at those addresses (the project OotRemake,
rem read only). Made for the Hookshot randomizer's work; everything stays on this PC.
set JAVA_HOME=C:\Users\beerc\tools\jdk-25.0.5+8
set GHIDRA_HEADLESS_MAXMEM=8G
call "C:\Users\beerc\tools\ghidra_12.2_PUBLIC\support\analyzeHeadless.bat" "C:\Users\beerc\tools\ghidra-projects" OotRemake -process image.bin -noanalysis -readOnly -scriptPath "C:\Users\beerc\tools\ghidra-projects\scripts" -postScript Decompile.java %*
