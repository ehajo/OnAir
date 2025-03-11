# Aufbau ON AIR Anzeige

## Lieferumfang

Mit dem Bausatz kann die Basis für eine LED Anzeige gebaut werden, die extrem flexibel und einfach konfigurierbar ist.
Für den finalen Betrieb muss noch extra ein Raspberry Pi Pico W erworben werden, der die Ansteuerung übernimmt, die Beschreibung für die Software findest du hier: [Software](https://github.com/ehajo/OnAir/tree/main/Software)

Im Lieferumfang des Bausatzes befindets ich:
- Platine mit 50 vorbestückten WS2812 RGB-LEDs
- 50 Kondensatoren 100nF 0805
- 2 Widerstände 5k1 0805
- 1 Kondensator 100µF 0805
- 1 Ferrit 0805
- 1 USB-C-PD-Buchse
- 1 Diode 1N4148 micromelf (Polarität beachten, unten beschrieben!)

## Aufbau

### Grundlagen

Die WS2812 LEDs sind bereits auf der Top-Seite der Platine vorbestückt und verlötet.
Bitte verwende eine Unterlage beim Löten, die die LEDs nicht zerkratzt!

### Schritt 1: Kondensatoren

Verlöte alle 100nF Kondensatoren an den Stellen C1 bis C50. Verlöte zuerst das Masse-Pad (Das weiter am unteren Platinenrand), befestige dann die Kondensatoren an dem Pad, verlöte das zweite Pad und schmilz das erste noch einmal auf.
Kondensatoren haben keine Polarität.

### Schritt 2: Kondensator C51 und Ferritbead

Verlöte den Kondensator C51 und den Ferritbead an der Stelle FB1.

### Schritt 3: USB-PD + Widerstände

Überlege dir, wie du das Kabel an die Anzeige anschließen willst. Es gibt zwei Möglichkeiten:

- nach unten: 
  - In diesem Fall Widerstände R1 und R2 mit 5k1 bestücken
  - Die nach unten gerichtete USB-Buchse (X1) verlöten
- seitlich:
  - Widerstände R6 und R7 mit 5k1 bestücken
  - Die seitlich gerichtete USB-Buchse (X2) verlöten
  
### Schritt 4: Diode 1N4148

Die Diode an Stelle D1 verlöten. Achtung dabei: Die Kathode ist in Richtung Buchstaben gerichtet, die Anode also Richtung Platinenrand.
Der Bestückdruck ist an dieser Stelle fehlerhaft, bitte auf das PDF mit dem Bestückplan achten!

### Schritt 5: Raspberry Pi Pico W

Den Raspberry Pi Pico W (Separat kaufen, nicht in unserem Shop erhältlich) auf die vorgesehen Pads löten. Die Micro-USB-Buchse zeigt dabei zum Platinenrand.

Tipp: Es muss nicht der gesamte Pico verlötet werden, es reichen die Pins 1, 2, 3, 4, 18+23 (GND zur Stabilität), 36, 38, 39.


## Addon Helligkeitssensor

Auf der Platine ist sind Pads für einen Helligkeitssensor vom Typ BH1750FVI vorgesehen.
Dieser ist im Schaltplan ersichtlich und wurde bisher noch nicht getestet.