"""Small Win32 adapter. No hooks, administrator rights, or background service."""
import ctypes
from ctypes import wintypes


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                ('wParamH', wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUTUNION)]


class WindowsMouse:
    FLAGS = {'left': (0x0002, 0x0004), 'right': (0x0008, 0x0010),
             'middle': (0x0020, 0x0040)}

    def __init__(self):
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.pressed = set()
        self.old_keys = {}
        self.width = self.user32.GetSystemMetrics(0)
        self.height = self.user32.GetSystemMetrics(1)

    def _send(self, flags, data=0, x=0, y=0):
        event = INPUT(type=0, mi=MOUSEINPUT(x, y, data & 0xffffffff, flags, 0, 0))
        if self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise OSError('Windows отклонила управление мышью. Включите паузу и вернитесь в обычное окно.')

    def move(self, point):
        self._send(0x8001, x=round(point[0] * 65535), y=round(point[1] * 65535))

    def apply(self, events):
        for action, value in events:
            if action == 'scroll':
                self._send(0x0800, int(value) * 120)
            elif action == 'down':
                self._send(self.FLAGS[value][0])
                self.pressed.add(value)
            elif action == 'up':
                self._send(self.FLAGS[value][1])
                self.pressed.discard(value)
            elif action == 'click':
                self.apply([('down', value), ('up', value)])

    def release_all(self):
        for button in tuple(self.pressed):
            try:
                self.apply([('up', button)])
            except OSError:
                # Keep it recorded so the next UI tick retries releasing it.
                pass

    def key_pressed(self, vk):
        down = bool(self.user32.GetAsyncKeyState(vk) & 0x8000)
        edge = down and not self.old_keys.get(vk, False)
        self.old_keys[vk] = down
        return edge
