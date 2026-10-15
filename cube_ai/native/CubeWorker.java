package cube.worker;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import com.google.gson.Gson;
import forge.GuiDesktop;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.player.RegisteredPlayer;
import forge.player.GamePlayerUtil;
import forge.util.MyRandom;
import forge.view.SimulateMatch;

/** A sequential worker: immutable card database is loaded once; matches are fresh. */
public final class CubeWorker {
    static final Gson JSON = new Gson();
    static class Request {
        String id, deck_dir, log;
        String[] order;
        long seed;
        int clock;
    }
    public static void main(String[] args) throws Exception {
        PrintStream protocol = System.out;
        PrintStream startup = new PrintStream("worker-startup.log", StandardCharsets.UTF_8);
        System.setOut(startup); System.setErr(startup);
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        protocol.println("CUBE_READY 1"); protocol.flush();
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; int games = 0;
        while ((line = input.readLine()) != null) {
            if (line.equals("STOP")) break;
            Request request = JSON.fromJson(line, Request.class);
            boolean retire = false;
            try (PrintStream log = new PrintStream(request.log, StandardCharsets.UTF_8)) {
                System.setOut(log); System.setErr(log);
                // Exactly the same seeding order as the native sim entry point.
                MyRandom.setRandom(new Random(request.seed));
                GameRules rules = new GameRules(GameType.Commander);
                rules.setAppliedVariants(EnumSet.of(GameType.Commander));
                rules.setSimTimeout(request.clock);
                List<RegisteredPlayer> players = new ArrayList<>();
                for (int i = 0; i < request.order.length; i++) {
                    Deck deck = DeckSerializer.fromFile(Paths.get(request.deck_dir, request.order[i] + ".dck").toFile());
                    if (deck == null) throw new IllegalArgumentException("Could not load deck " + request.order[i]);
                    RegisteredPlayer player = RegisteredPlayer.forCommander(deck);
                    player.setPlayer(GamePlayerUtil.createAiPlayer("Ai(" + (i + 1) + ")-" + deck.getName(), i, ""));
                    players.add(player);
                }
                SimulateMatch.simulateSingleMatch(new Match(rules, players, "Test"), 0, true);
            } catch (Throwable error) {
                try (PrintStream log = new PrintStream(new FileOutputStream(request.log, true), true, StandardCharsets.UTF_8)) {
                    error.printStackTrace(log);
                }
                retire = true;
            } finally { System.setOut(startup); System.setErr(startup); }
            String log = Files.readString(Path.of(request.log), StandardCharsets.UTF_8);
            retire |= log.contains("Exception") || log.contains("Stopping slow match as draw") || ++games >= 16;
            protocol.println("CUBE_RESULT " + JSON.toJson(Map.of("id", request.id, "retire", retire)));
            protocol.flush();
            // Do not let a cancelled native AI thread contaminate a later game.
            if (retire) System.exit(0);
        }
        System.exit(0);
    }
}
