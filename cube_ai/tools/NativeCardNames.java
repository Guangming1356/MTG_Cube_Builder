// SPDX-License-Identifier: GPL-3.0-or-later
// Developer-only inspection of the original Forge database. No game is run.
package cube.tools;

import java.io.PrintStream;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import forge.GuiDesktop;
import forge.gui.GuiBase;
import forge.item.PaperCard;
import forge.model.FModel;

public final class NativeCardNames {
    public static void main(String[] args) throws Exception {
        Gson json = new Gson();
        Map<String,String> requested = json.fromJson(
            Files.readString(Path.of(args[0]), StandardCharsets.UTF_8),
            new TypeToken<Map<String,String>>(){}.getType());
        PrintStream protocol = new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8);
        try (PrintStream log = new PrintStream("card-name-startup.log", StandardCharsets.UTF_8)) {
            System.setOut(log); System.setErr(log);
            try {
                GuiBase.setInterface(new GuiDesktop());
                FModel.initialize(null, null);
                Map<String,Object> results = new LinkedHashMap<>();
                for (Map.Entry<String,String> entry : requested.entrySet()) {
                    PaperCard card = FModel.getMagicDb().getCommonCards().getCard(entry.getKey());
                    Map<String,Object> result = new LinkedHashMap<>();
                    result.put("found", card != null);
                    if (card != null) {
                        result.put("loaded_name", card.getName());
                        result.put("rules_name", card.getRules().getName());
                        result.put("verified", entry.getKey().equals(card.getName())
                            && entry.getValue().equals(card.getRules().getName()));
                    } else result.put("verified", false);
                    results.put(entry.getKey(), result);
                }
                protocol.println("CUBE_CARD_NAMES " + json.toJson(results));
                protocol.flush();
            } catch (Throwable error) {
                error.printStackTrace(log); log.flush(); System.exit(1);
            }
        }
        System.exit(0);
    }
}
