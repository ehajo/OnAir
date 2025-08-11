# boot.py
import board
import digitalio
import storage
import usb_cdc
import usb_hid
import usb_midi

# Optional: serielle Konsole anlassen (praktisch fürs Debuggen), Data-CDC aus
usb_cdc.enable(console=True, data=False)
# HID/MIDI ausschalten (spart RAM, optional)
usb_hid.disable()
usb_midi.disable()

# Wartungs-Pin: GP15 -> GND halten beim Einschalten, um CIRCUITPY sichtbar zu lassen
maint = digitalio.DigitalInOut(board.GP15)
maint.switch_to_input(pull=digitalio.Pull.UP)
print("Boot.py ausgeführt")

if maint.value:
    # Normalbetrieb: CIRCUITPY-USB-Laufwerk deaktivieren => Dateisystem für code.py schreibbar
    storage.disable_usb_drive()
else:
    # Wartungsmodus: alles wie gewohnt, CIRCUITPY sichtbar am PC
    pass
