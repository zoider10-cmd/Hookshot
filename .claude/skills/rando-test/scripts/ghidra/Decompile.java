// Decompiles the functions at the given addresses of the game's code, into a text file.
// Arguments: <out file> <address>... (hex, 0x...). A function is made where there is none (its code disassembled first).
// Run by decompile.bat, read only (-readOnly): nothing is saved to the project.
//@category Hookshot
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;

public class Decompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: Decompile <out file> <address>...");
            return;
        }
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                Address at = toAddr(Long.decode(args[i]));
                Function f = getFunctionContaining(at);
                if (f == null) {
                    disassemble(at);
                    f = createFunction(at, null);
                }
                if (f == null) {
                    out.println("// " + args[i] + ": no function could be made there");
                    continue;
                }
                DecompileResults r = decomp.decompileFunction(f, 120, monitor);
                out.println("// ---- " + f.getName() + " at " + f.getEntryPoint() + " (asked: " + args[i] + ")");
                if (r != null && r.decompileCompleted()) {
                    out.println(r.getDecompiledFunction().getC());
                } else {
                    out.println("// decompiling failed: " + (r == null ? "?" : r.getErrorMessage()));
                }
            }
        }
        decomp.dispose();
    }
}
