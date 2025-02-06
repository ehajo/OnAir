import time
import board
import neopixel
import random

# --- NeoPixel-Setup ---
pixel_pin = board.GP2
num_pixels = 50  # Gesamtzahl der LEDs
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=1.0, auto_write=False)

# --- Buchstabenbereiche definieren ---
# Hinweis: LED1 entspricht Index 0, LED50 entspricht Index 49.
letters = {
    "O": range(0, 10),    # LEDs 1 bis 10 (Indices 0 bis 9)
    "N": range(10, 23),   # LEDs 11 bis 23 (Indices 10 bis 22)
    "A": range(23, 33),   # LEDs 24 bis 33 (Indices 23 bis 32)
    "I": range(33, 38),   # LEDs 34 bis 38 (Indices 33 bis 37)
    "R": range(38, 50)    # LEDs 39 bis 50 (Indices 38 bis 49)
}

def base_effect_update():
    """
    Setzt für jeden Buchstaben eine zufällig generierte Farbe.
    Diese Funktion sorgt dafür, dass im Basismodus
    jeder Buchstabe in einer anderen, zufälligen Farbe leuchtet.
    """
    for letter, indices in letters.items():
        # Zufällige Farbe generieren
        color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for i in indices:
            pixels[i] = color
    pixels.show()

def running_white_effect(speed=0.005):
    """
    Lässt eine einzelne weiße LED von LED50 bis LED1 laufen.
    """
    white = (255, 255, 255)
    for i in range(num_pixels - 1, -1, -1):
        pixels.fill((0, 0, 0))
        pixels[i] = white
        pixels.show()
        time.sleep(speed)
    pixels.fill((0, 0, 0))
    pixels.show()

def fade_in_letters(fade_steps=20, fade_delay=0.02, pause_after=1):
    """
    Lässt die Buchstaben in der Reihenfolge (O, N, A, I, R) einfaden.
    Dabei fadet der Buchstabe "O" von Schwarz zu Blau (0,0,255),
    während die übrigen Buchstaben (N, A, I, R) von Schwarz zu Orange (255,165,0) einfaden.
    """
    # Definition der Ziel-Farben
    target_colors = {
        "O": (0, 0, 255),        # Blau
        "N": (255, 165, 0),      # Orange
        "A": (255, 165, 0),
        "I": (255, 165, 0),
        "R": (255, 165, 0)
    }
    letter_order = ["O", "N", "A", "I", "R"]
    
    # Alle LEDs ausschalten
    pixels.fill((0, 0, 0))
    pixels.show()
    
    # Nacheinander jeden Buchstaben einfaden lassen
    for letter in letter_order:
        color = target_colors[letter]
        for step in range(fade_steps + 1):
            factor = step / fade_steps
            scaled_color = tuple(int(c * factor) for c in color)
            for i in letters[letter]:
                pixels[i] = scaled_color
            pixels.show()
            time.sleep(fade_delay)
    time.sleep(pause_after)

def main():
    """
    Hauptprogramm:
    - Im Basismodus leuchten die Buchstaben in zufälligen Farben (alle 0,5 Sekunden aktualisiert).
    - Alle 5 Sekunden wird zuerst eine einzelne weiße LED von LED50 bis LED1 laufen gelassen,
      anschließend fadet der Text ein: "O" in Blau und "N", "A", "I", "R" in Orange.
    Danach beginnt der Zyklus von vorne.
    """
    while True:
        start_time = time.monotonic()
        # Basismodus für ca. 5 Sekunden
        while (time.monotonic() - start_time) < 5:
            base_effect_update()
            time.sleep(0.5)
        # Sondereffekt: Running-LED in Weiß
        running_white_effect(speed=0.005)
        # Sondereffekt: Buchstaben-Fade (O in Blau, Rest in Orange)
        fade_in_letters(fade_steps=20, fade_delay=0.02, pause_after=1)

# Programmstart
main()
