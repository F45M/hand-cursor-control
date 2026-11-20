"""Explicit integration check: send mouse events only inside a temporary test window."""
import ctypes
from ctypes import wintypes
import json
import time
import tkinter as tk
from windows_mouse import WindowsMouse


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
    root = tk.Tk()
    root.title('Проверка мыши — автоматически закроется')
    root.geometry('520x240+80+80')
    root.attributes('-topmost', True)
    tk.Label(root, text='Проверяю кнопки и прокрутку Windows…',
             font=('Segoe UI', 14)).pack(pady=24)
    area = tk.Canvas(root, bg='#173d46', highlightthickness=0)
    area.pack(fill='both', expand=True)
    events = []
    for sequence, label in (('<ButtonPress-1>', 'left-down'), ('<ButtonRelease-1>', 'left-up'),
                            ('<ButtonPress-3>', 'right-down'), ('<ButtonRelease-3>', 'right-up'),
                            ('<ButtonPress-2>', 'middle-down'), ('<ButtonRelease-2>', 'middle-up')):
        area.bind(sequence, lambda event, label=label: events.append(label))
    area.bind('<MouseWheel>', lambda event: events.append(['wheel', event.delta]))
    mouse = WindowsMouse()
    previous = wintypes.POINT()
    mouse.user32.GetCursorPos(ctypes.byref(previous))
    def pump():
        until = time.monotonic() + 0.09
        while time.monotonic() < until:
            root.update()
            time.sleep(0.005)
    try:
        root.update()
        root.lift()
        root.focus_force()
        area.focus_set()
        pump()
        x = area.winfo_rootx() + area.winfo_width() // 2
        y = area.winfo_rooty() + area.winfo_height() // 2
        mouse.move((x / (mouse.width - 1), y / (mouse.height - 1)))
        pump()
        actual = wintypes.POINT()
        mouse.user32.GetCursorPos(ctypes.byref(actual))
        if abs(actual.x-x) > 3 or abs(actual.y-y) > 3:
            raise AssertionError(f'Pointer did not reach test area: {actual.x}, {actual.y}')
        for button in ('left', 'right', 'middle'):
            mouse.apply([('down', button)])
            pump()
            mouse.apply([('up', button)])
            pump()
        mouse.apply([('scroll', 1)])
        pump()
        mouse.apply([('scroll', -1)])
        pump()
        expected = ['left-down', 'left-up', 'right-down', 'right-up', 'middle-down',
                    'middle-up', ['wheel', 120], ['wheel', -120]]
        if events != expected:
            raise AssertionError(f'Expected {expected}, got {events}')
        print(json.dumps({'native_input': 'passed', 'events': events, 'pressed': list(mouse.pressed)}))
    finally:
        mouse.release_all()
        mouse.user32.SetCursorPos(previous.x, previous.y)
        root.destroy()


if __name__ == '__main__':
    main()
