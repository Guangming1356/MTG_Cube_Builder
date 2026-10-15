# Resident Forge bridge

CubeWorker.java is distributed under GPL-3.0-or-later; see LICENSE.txt.
It links to the unmodified Forge 2.0.15 runtime through public Java APIs.
The bridge loads the card database once and constructs a fresh Match per request.
The Python controller terminates and replaces a worker on a timeout, an engine error, or after 16 games.

Build with Java 21 and Eclipse ECJ (build-time dependency only):

`java -jar ecj.jar -21 -encoding UTF-8 -cp forge-gui-desktop-2.0.15-jar-with-dependencies.jar -d classes CubeWorker.java`

The portable distribution includes source, GPL text, and compiled classes.
Forge itself remains unmodified. The engine falls back to its native CLI when a verified bridge is unavailable.
