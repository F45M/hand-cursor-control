![Ручное управление](docs/banner.svg)

Управление курсором Windows жестами через веб-камеру. Приложение распознаёт точки ладони через MediaPipe, сглаживает движение пальца и передаёт клики, прокрутку и перемещение курсора через Win32.

## Первый запуск

Понадобятся Windows x64, Python 3.11 и веб-камера. Из папки проекта выполните команды PowerShell.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force models | Out-Null
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task' -OutFile 'models/hand_landmarker.task'
.\.venv\Scripts\python.exe app.py
```

Для установки с ярлыком на рабочем столе можно запустить `setup.ps1` в PowerShell. После установки приложение также открывается через `start.cmd`.

В окне приложения нажмите **F8**, покажите раскрытую ладонь и двигайте указательным пальцем внутри рамки предварительного просмотра. Курсор перемещается по основному экрану.

## Жесты и клавиши

| Действие | Жест или клавиша |
| --- | --- |
| Левая, правая или средняя кнопка | Коротко соедините большой палец с указательным, средним или безымянным соответственно |
| Удержание или перетаскивание | Удерживайте касание пальцев около 0,4 секунды, затем перемещайте руку |
| Прокрутка | Покажите указательный и средний пальцы, немного подождите и двигайте руку вверх или вниз |
| Выход из прокрутки | Раскройте ладонь и ненадолго задержите её |
| Включить управление или поставить на паузу | **F8** |
| Пауза | **Esc** |
| Выход | **Ctrl + Shift + Q** |

При исчезновении руки из кадра, паузе или остановке захвата приложение отпускает кнопки мыши. Классическим приложениям Windows нужен доступ к камере.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --diagnose
```

Модульные тесты проверяют распознавание жестов, сглаживание и вычисления по точкам руки. Диагностика проверяет камеру и модель без отправки событий мыши. Кадры обрабатываются локально, а параметры сохраняются в `settings.json`.

Подробнее о [MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python) и [Win32 SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).
