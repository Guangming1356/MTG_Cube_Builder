/* SPDX-License-Identifier: GPL-3.0-or-later
 * Experimental, version-specific build tool. The input Forge JAR stays intact.
 * Only the modal-description formatter receives an early context initializer.
 * No spell resolution, mode choice or target-legality method is modified.
 */
import java.nio.file.*;
import org.objectweb.asm.*;

public final class ModalDescriptionPatch {
    public static void main(String[] args) throws Exception {
        if (args.length != 3 || !(args[2].equals("patch") || args[2].equals("identity")))
            throw new IllegalArgumentException("input.class output.class patch|identity");
        byte[] original = Files.readAllBytes(Path.of(args[0]));
        ClassReader reader = new ClassReader(original);
        if (!reader.getClassName().equals("forge/game/ability/effects/CharmEffect"))
            throw new IllegalArgumentException("Unexpected input class");
        final boolean patch = args[2].equals("patch");
        ClassWriter writer = new ClassWriter(reader, patch ? ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS : 0);
        int[] changed = {0};
        ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
            @Override public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
                MethodVisitor target = super.visitMethod(access, name, descriptor, signature, exceptions);
                if (!patch || !name.equals("makeFormatedDescription") || !descriptor.equals("(Lforge/game/spellability/SpellAbility;Z)Ljava/lang/String;")) return target;
                changed[0]++;
                return new MethodVisitor(Opcodes.ASM9, target) {
                    @Override public void visitCode() {
                        super.visitCode();
                        String ability = "forge/game/spellability/SpellAbility";
                        String card = "forge/game/card/Card";
                        String player = "Lforge/game/player/Player;";
                        Label ready = new Label();
                        // The original formatter performs this initialization
                        // AFTER querying targets. Initialize only missing context,
                        // with the same controller it already uses later.
                        visitVarInsn(Opcodes.ALOAD, 0);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, ability, "getActivatingPlayer", "()" + player, false);
                        visitJumpInsn(Opcodes.IFNONNULL, ready);
                        visitVarInsn(Opcodes.ALOAD, 0);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, ability, "getHostCard", "()Lforge/game/card/Card;", false);
                        visitJumpInsn(Opcodes.IFNULL, ready);
                        visitVarInsn(Opcodes.ALOAD, 0);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, ability, "getHostCard", "()Lforge/game/card/Card;", false);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, card, "getController", "()" + player, false);
                        visitJumpInsn(Opcodes.IFNULL, ready);
                        visitVarInsn(Opcodes.ALOAD, 0);
                        visitVarInsn(Opcodes.ALOAD, 0);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, ability, "getHostCard", "()Lforge/game/card/Card;", false);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, card, "getController", "()" + player, false);
                        visitMethodInsn(Opcodes.INVOKEVIRTUAL, ability, "setActivatingPlayer", "(" + player + ")V", false);
                        visitLabel(ready);
                    }
                };
            }
        };
        reader.accept(visitor, 0);
        if (patch && changed[0] != 1) throw new IllegalStateException("Expected exactly one formatter method");
        Path destination = Path.of(args[1]);Files.createDirectories(destination.getParent());
        Files.write(destination, writer.toByteArray());
        System.out.println("changed_methods=" + changed[0]);
    }
}
