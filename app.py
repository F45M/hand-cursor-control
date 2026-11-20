"""Hand Mouse: local webcam gesture control for Windows."""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict
import json
import logging
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from gestures import Settings, Hand, GestureEngine, CursorFilter
from windows_mouse import WindowsMouse

ROOT = Path(__file__).resolve().parent
TITLE = 'Ручное управление — мышь жестами'
MODEL = ROOT / 'models' / 'hand_landmarker.task'
CONNECTIONS = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6),
               (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
               (9, 13), (13, 14), (14, 15), (15, 16), (13, 17),
               (0, 17), (17, 18), (18, 19), (19, 20))


def load_settings():
    cfg = Settings()
    try:
        data = json.loads((ROOT / 'settings.json').read_text(encoding='utf-8'))
        limits = {'camera': (0, 9), 'pinch': (0.15, 0.42),
                  'hold_seconds': (0.25, 1), 'smoothing': (0.015, 0.18),
                  'scroll_distance': (0.015, 0.07), 'margin': (0.05, 0.3)}
        for key, (low, high) in limits.items():
            value = float(data.get(key, getattr(cfg, key)))
            if math.isfinite(value):
                setattr(cfg, key, min(high, max(low, value)))
        cfg.camera = int(cfg.camera)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return cfg


class CameraWorker(threading.Thread):
    def __init__(self, index):
        super().__init__(name='hand-camera', daemon=True)
        self.index = index
        self.frames = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.error = None
        self.ready = False

    def run(self):
        capture = None
        try:
            import cv2
            import mediapipe as mp
            if not MODEL.exists():
                raise RuntimeError('Не найдена модель models/hand_landmarker.task. Запустите setup.ps1.')
            # Pass bytes so non-ASCII project paths work with native MediaPipe code.
            options = mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=MODEL.read_bytes()),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=2, min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.6, min_tracking_confidence=0.6)
            with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
                for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                    capture = cv2.VideoCapture(self.index, backend)
                    if capture.isOpened():
                        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        capture.set(cv2.CAP_PROP_FPS, 30)
                        ok, frame = capture.read()
                        if ok:
                            break
                    capture.release()
                    capture = None
                if capture is None:
                    raise RuntimeError('Камера недоступна. Закройте другие приложения с камерой, '
                                       'проверьте доступ к камере в параметрах Windows или выберите другой номер.')
                self.ready = True
                previous = 0
                failures = 0
                while not self.stop_event.is_set():
                    ok, frame = capture.read()
                    captured = time.monotonic()
                    if not ok:
                        failures += 1
                        if failures >= 8:
                            raise RuntimeError('Камера перестала передавать изображение. Перезапустите камеру.')
                        self.stop_event.wait(0.03)
                        continue
                    failures = 0
                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    stamp = max(previous + 1, int(captured * 1000))
                    previous = stamp
                    result = detector.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), stamp)
                    packet = (captured, rgb, result)
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                    self.frames.put_nowait(packet)
        except Exception as exc:
            logging.exception('Camera worker failed')
            self.error = str(exc)
        finally:
            self.ready = False
            if capture is not None:
                capture.release()


class HandMouseApp:
    def __init__(self, root, smoke_seconds=0):
        self.root = root
        self.cfg = load_settings()
        self.mouse = WindowsMouse()
        self.engine = GestureEngine(self.cfg)
        self.filter = CursorFilter()
        self.enabled = False
        self.countdown = 0.0
        self.closed = False
        self.last_frame = 0.0
        self.frame_count = 0
        self.selected = None
        self.selected_position = None
        self.selected_seen = 0.0
        self.error_shown = False
        self.worker = CameraWorker(self.cfg.camera)
        self.build_ui()
        self.worker.start()
        self.root.after(20, self.tick)
        if smoke_seconds:
            self.root.after(int(smoke_seconds * 1000), self.smoke_finish)

    def build_ui(self):
        root = self.root
        root.title(TITLE)
        root.configure(bg='#101722')
        root.geometry('1020x730')
        root.minsize(950, 700)
        if (ROOT / 'hand_mouse.ico').exists():
            root.iconbitmap(str(ROOT / 'hand_mouse.ico'))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#101722', foreground='#e5edf8')
        style.configure('TFrame', background='#101722')
        style.configure('TLabel', background='#101722', foreground='#e5edf8')
        style.configure('Muted.TLabel', foreground='#9dadc4')
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'))
        style.configure('Status.TLabel', foreground='#6de5bd', font=('Segoe UI', 12, 'bold'))
        style.configure('TButton', background='#27384e', foreground='#ffffff', padding=(12, 8))
        style.map('TButton', background=[('active', '#385673')])
        style.configure('TScale', background='#101722', troughcolor='#27384e')
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Мышь в твоих руках', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Камера → движения пальцев → управление компьютером',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 16))
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body)
        left.pack(side='left', fill='both', expand=True)
        self.preview = tk.Label(left, bg='#080d15', fg='#9dadc4',
                                text='Подключаю камеру…', font=('Segoe UI', 14))
        self.preview.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Запуск камеры и распознавания…')
        ttk.Label(left, textvariable=self.status, style='Status.TLabel',
                  wraplength=620).pack(anchor='w', pady=(12, 5))
        self.detail = tk.StringVar(value='Видео обрабатывается на компьютере и не сохраняется.')
        ttk.Label(left, textvariable=self.detail, style='Muted.TLabel',
                  wraplength=620).pack(anchor='w')
        right = ttk.Frame(body, padding=(20, 0, 0, 0), width=310)
        right.pack(side='right', fill='y')
        ttk.Label(right, text='Твои жесты', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        instructions = [
            ('Двигать курсор', 'Указывай кончиком указательного пальца, как в зеркале.'),
            ('Левая кнопка', 'Большой + указательный палец'),
            ('Правая кнопка', 'Большой + средний палец'),
            ('Средняя кнопка', 'Большой + безымянный палец'),
            ('Удержание / перетаскивание', 'Держи касание 0,4 с, затем двигай руку.\nРазведи пальцы, чтобы отпустить.'),
            ('Прокрутка: два пальца', 'Указательный и средний выпрями,\nбезымянный и мизинец согни, большой\nотведи. Двигай руку вверх / вниз.')]
        for title, desc in instructions:
            ttk.Label(right, text=title, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
            ttk.Label(right, text=desc, style='Muted.TLabel', wraplength=285).pack(anchor='w', pady=(1, 9))
        self.add_slider(right, 'Расстояние касания', 'pinch', 0.15, 0.42)
        self.add_slider(right, 'Сглаживание движения', 'smoothing', 0.015, 0.18)
        self.add_slider(right, 'Ход руки на шаг (меньше — быстрее)', 'scroll_distance', 0.015, 0.07)
        row = ttk.Frame(right)
        row.pack(fill='x', pady=(8, 0))
        ttk.Label(row, text='Камера:').pack(side='left')
        self.camera_var = tk.StringVar(value=str(self.cfg.camera))
        ttk.Combobox(row, textvariable=self.camera_var, values=list(range(10)),
                     state='readonly', width=3).pack(side='left', padx=6)
        ttk.Button(row, text='Подключить', command=self.restart_camera).pack(side='left')
        bottom = ttk.Frame(outer)
        bottom.pack(fill='x', pady=(16, 0))
        self.toggle_button = ttk.Button(bottom, text='Включить управление · F8', command=self.toggle)
        self.toggle_button.pack(side='left')
        ttk.Button(bottom, text='Инструкция', command=lambda: os.startfile(str(ROOT / 'README.md'))).pack(side='left', padx=8)
        ttk.Button(bottom, text='Выход', command=self.close).pack(side='right')
        ttk.Label(outer, text='F8 — включить / пауза     •     Esc — пауза     •     Ctrl + Shift + Q — выход',
                  style='Muted.TLabel').pack(anchor='w', pady=(12, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.report_callback_exception = self.ui_exception

    def add_slider(self, parent, title, name, low, high):
        ttk.Label(parent, text=title, style='Muted.TLabel').pack(anchor='w')
        variable = tk.DoubleVar(value=getattr(self.cfg, name))
        def update(value):
            setattr(self.cfg, name, float(value))
        ttk.Scale(parent, from_=low, to=high, variable=variable,
                  command=update, length=275).pack(fill='x', pady=(0, 5))

    def pause(self):
        self.enabled = False
        self.countdown = 0.0
        self.engine.reset()
        self.mouse.release_all()
        self.filter = CursorFilter()
        self.toggle_button.configure(text='Включить управление · F8')

    def toggle(self):
        if self.enabled or self.countdown:
            self.pause()
        elif self.worker.ready and not self.worker.error:
            self.engine.reset()
            self.filter = CursorFilter()
            self.countdown = time.monotonic() + 2
            self.toggle_button.configure(text='Отменить запуск · F8')
        else:
            self.status.set('Дождитесь камеры или нажмите «Подключить».')

    def restart_camera(self):
        self.pause()
        self.worker.stop_event.set()
        self.status.set('Переподключаю камеру…')
        self.toggle_button.configure(state='disabled')
        self.await_restart(time.monotonic())

    def await_restart(self, started):
        if self.closed:
            return
        if self.worker.is_alive():
            if time.monotonic() - started > 5:
                self.status.set('Камера не отвечает. Закройте программу и откройте снова.')
                self.toggle_button.configure(state='normal')
                return
            self.root.after(100, lambda: self.await_restart(started))
            return
        self.cfg.camera = int(self.camera_var.get())
        self.selected = None
        self.selected_position = None
        self.last_frame = 0
        self.error_shown = False
        self.worker = CameraWorker(self.cfg.camera)
        self.worker.start()
        self.toggle_button.configure(state='normal')

    def select_hand(self, result, now):
        candidates = list(zip(result.hand_landmarks, result.handedness))
        if self.selected is not None and now - self.selected_seen < 0.5:
            candidates = [(p, h) for p, h in candidates if h[0].category_name == self.selected
                          and math.dist((p[0].x, p[0].y), self.selected_position) < 0.28]
            if not candidates:
                return None
            points, handed = min(candidates, key=lambda item: math.dist(
                (item[0][0].x, item[0][0].y), self.selected_position))
        elif candidates:
            points, handed = max(candidates, key=lambda item: math.dist(
                (item[0][0].x, item[0][0].y), (item[0][9].x, item[0][9].y)))
            self.mouse.apply(self.engine.reset())
            self.filter = CursorFilter()
        else:
            return None
        self.selected = handed[0].category_name
        self.selected_position = (points[0].x, points[0].y)
        self.selected_seen = now
        return points

    def process_frame(self, packet, now):
        import cv2
        from PIL import Image, ImageTk
        captured, rgb, result = packet
        self.last_frame = captured
        self.frame_count += 1
        height, width = rgb.shape[:2]
        points = self.select_hand(result, now)
        fresh = now - captured < 0.35
        hand = Hand.from_landmarks(points, width, height) if points and fresh else None
        if self.enabled:
            events = self.engine.update(hand, now)
            self.mouse.apply(events)
            if hand and self.engine.armed and not self.engine.freeze_cursor:
                self.mouse.move(self.filter.update(hand.cursor, now, self.cfg))
            if hand is None:
                self.filter = CursorFilter()
            self.status.set(self.engine.label if hand else 'Рука не видна — кнопки отпущены')
        elif not self.countdown:
            self.status.set('Пауза · нажми F8 или «Включить управление»')
        m = self.cfg.margin
        cv2.rectangle(rgb, (int(width*m), int(height*m)),
                      (int(width*(1-m)), int(height*(1-m))), (63, 94, 118), 1)
        for landmarks in result.hand_landmarks:
            active = landmarks is points
            color = (109, 229, 189) if active else (115, 135, 160)
            coords = [(int(p.x*width), int(p.y*height)) for p in landmarks]
            for a, b in CONNECTIONS:
                cv2.line(rgb, coords[a], coords[b], color, 2, cv2.LINE_AA)
            for i, p in enumerate(coords):
                cv2.circle(rgb, p, 5 if i in (4, 8, 12, 16, 20) else 3, color, -1)
            if active and hand:
                cv2.circle(rgb, (int(hand.cursor[0]*width), int(hand.cursor[1]*height)),
                           9, (255, 213, 109), 2)
        image = Image.fromarray(rgb)
        image.thumbnail((max(100, self.preview.winfo_width()), max(100, self.preview.winfo_height())))
        self.photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.photo, text='')
        if hand:
            side = 'левая' if self.selected == 'Left' else 'правая'
            self.detail.set(f'Рука: {side} · задержка {int((now-captured)*1000)} мс · '
                            'держи всю ладонь в кадре')
        else:
            self.detail.set('Покажи камере раскрытую ладонь. Подойдёт любая рука.')

    def tick(self):
        if self.closed:
            return
        try:
            now = time.monotonic()
            if self.mouse.key_pressed(0x77):  # F8, globally
                self.toggle()
            if self.mouse.key_pressed(0x1B):
                self.pause()
            q_edge = self.mouse.key_pressed(0x51)
            if (q_edge and self.mouse.user32.GetAsyncKeyState(0x11) & 0x8000
                    and self.mouse.user32.GetAsyncKeyState(0x10) & 0x8000):
                self.close()
                return
            if self.countdown:
                remaining = self.countdown - now
                self.status.set(f'Управление через {max(1, math.ceil(remaining))}… Раскрой ладонь')
                if remaining <= 0:
                    self.countdown = 0
                    self.enabled = True
                    self.toggle_button.configure(text='Приостановить · F8')
            try:
                packet = self.worker.frames.get_nowait()
            except queue.Empty:
                packet = None
            if packet is not None:
                self.process_frame(packet, now)
            if self.enabled and now - self.last_frame > 0.35:
                self.engine.reset()
                self.mouse.release_all()
                self.filter = CursorFilter()
                self.status.set('Нет свежих кадров — кнопки отпущены')
            if not self.enabled:
                self.mouse.release_all()
            if self.worker.error:
                self.pause()
                self.status.set(self.worker.error)
                if not self.error_shown:
                    self.error_shown = True
                    messagebox.showerror('Не удалось включить камеру', self.worker.error)
        except Exception:
            logging.exception('UI processing failed')
            self.pause()
            self.status.set('Ошибка обработки. Управление остановлено. Подробности: hand_mouse.log')
        self.root.after(15, self.tick)

    def ui_exception(self, exc_type, value, tb):
        logging.error('UI callback failed', exc_info=(exc_type, value, tb))
        self.pause()
        messagebox.showerror('Ошибка', str(value))

    def smoke_finish(self):
        clipped = []
        def check(widget):
            for child in widget.winfo_children():
                if child.winfo_ismapped():
                    if (child.winfo_x() + child.winfo_width() > widget.winfo_width() + 2
                            or child.winfo_y() + child.winfo_height() > widget.winfo_height() + 2):
                        clipped.append(str(child))
                    check(child)
        check(self.root)
        report = {'frames': self.frame_count, 'camera_ready': self.worker.ready,
                  'error': self.worker.error, 'mouse_enabled': self.enabled,
                  'pressed_buttons': sorted(self.mouse.pressed),
                  'clipped_widgets': clipped,
                  'preview_size': [self.preview.winfo_width(), self.preview.winfo_height()]}
        (ROOT / 'diagnostics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pause()
        self.worker.stop_event.set()
        try:
            (ROOT / 'settings.json').write_text(
                json.dumps(asdict(self.cfg), indent=2, ensure_ascii=False), encoding='utf-8')
        except OSError:
            logging.exception('Cannot save settings')
        self.worker.join(timeout=1.0)
        self.mouse.release_all()
        self.root.destroy()


def diagnose():
    worker = CameraWorker(load_settings().camera)
    worker.start()
    started = time.monotonic()
    frames = 0
    shape = None
    hands = 0
    latencies = []
    try:
        while time.monotonic() - started < 25 and frames < 45:
            if worker.error:
                raise RuntimeError(worker.error)
            try:
                captured, rgb, result = worker.frames.get(timeout=0.25)
            except queue.Empty:
                continue
            frames += 1
            shape = list(rgb.shape)
            hands = max(hands, len(result.hand_landmarks))
            latencies.append(time.monotonic() - captured)
        if not frames:
            raise RuntimeError('Нет кадров камеры за 25 секунд')
        report = {'frames': frames, 'image_shape': shape, 'max_hands_detected': hands,
                  'mean_inference_ms': round(sum(latencies)/len(latencies)*1000, 1),
                  'mouse_input_sent': False}
        print(json.dumps(report, indent=2))
    finally:
        worker.stop_event.set()
        worker.join(timeout=2)


def main():
    logging.basicConfig(filename=str(ROOT / 'hand_mouse.log'), level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--smoke-test', type=float, default=0)
    args = parser.parse_args()
    if args.diagnose:
        diagnose()
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\HandMouseGestureApp')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        user32 = ctypes.WinDLL('user32')
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        window = user32.FindWindowW(None, TITLE)
        if window:
            user32.ShowWindow(window, 9)
            user32.SetForegroundWindow(window)
        kernel.CloseHandle(mutex)
        return
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        root = tk.Tk()
        root.tk.call('tk', 'scaling', 1.333333)
        app = HandMouseApp(root, args.smoke_test)
        try:
            root.mainloop()
        finally:
            if not app.closed:
                app.close()
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.exception('Application startup failed')
        if '--diagnose' in sys.argv or '--smoke-test' in sys.argv:
            raise
        ctypes.windll.user32.MessageBoxW(0, f'{exc}\n\nПодробности: {ROOT / "hand_mouse.log"}',
                                        'Ручное управление: ошибка запуска', 0x10)
