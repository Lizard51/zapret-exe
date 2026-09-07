# Инструкция по сборке ZapretManager в EXE-файл

## Требования

- **Python 3.8+** (только для сборки, пользователям Python не нужен)
- **Windows** (для создания .exe файла)
- **PyInstaller** (устанавливается автоматически скриптом сборки)

## Быстрая сборка

### Вариант 1: Использование скрипта сборки (рекомендуется)

```bash
python build.py
```

Этот скрипт:
- Автоматически установит PyInstaller если нужно
- Очистит предыдущие сборки
- Запустит PyInstaller с правильными параметрами
- Проверит результат сборки

Готовый exe-файл будет находиться в папке: `dist/ZapretManager/ZapretManager.exe`

### Вариант 2: Ручная сборка через PyInstaller

```bash
# Установите PyInstaller
pip install pyinstaller

# Соберите проект
pyinstaller ZapretManager.spec

# Или используйте команду напрямую
pyinstaller --name ZapretManager --onedir --windowed --collect-all tkinter zapret_manager/__main__.py
```

## Типы сборок

### Onedir (папка с зависимостями) - РЕКОМЕНДУЕТСЯ

```bash
pyinstaller --name ZapretManager --onedir --windowed zapret_manager/__main__.py
```

**Преимущества:**
- Быстрее запуск приложения
- Меньший размер основного exe-файла
- Легче обновлять отдельные компоненты

**Результат:** Папка `dist/ZapretManager/` с exe-файлом и библиотеками

### Onefile (единый файл)

```bash
pyinstaller --name ZapretManager --onefile --windowed zapret_manager/__main__.py
```

**Преимущества:**
- Один единственный .exe файл
- Удобно для распространения

**Недостатки:**
- Медленнее запуск (распаковка во временную папку)
- Больший размер файла (~50-60 MB)
- Антивирусы чаще ругаются на onefile сборки

**Результат:** Один файл `dist/ZapretManager.exe`

## Распространение

После успешной сборки:

1. **Для варианта onedir:**
   - Скопируйте всю папку `dist/ZapretManager/`
   - Передайте пользователю
   - Пользователь запускает `ZapretManager.exe`

2. **Для варианта onefile:**
   - Скопируйте файл `dist/ZapretManager.exe`
   - Передайте пользователю
   - Пользователь запускает `ZapretManager.exe`

**Важно:** Python устанавливать НЕ НУЖНО! Все библиотеки уже встроены в exe-файл.

## Решение проблем

### Ошибка: "No module named 'tkinter'"

Убедитесь, что у вас установлена полная версия Python, а не minimal. Для Windows скачайте установщик с python.org и убедитесь, что отмечен компонент "tcl/tk and IDLE".

### Ошибка: "module not found" для внутренних модулей

Используйте готовый spec-файл `ZapretManager.spec`, который содержит все необходимые hiddenimports.

### Антивирус удаляет exe-файл

Это ложное срабатывание. PyInstaller создает exe-файлы, которые некоторые антивирусы ошибочно определяют как подозрительные. 

Решения:
- Добавьте папку с программой в исключения антивируса
- Подпишите exe-файл цифровой подписью (требуется сертификат)
- Используйте вариант onedir вместо onefile

### Большой размер exe-файла

Это нормально. PyInstaller включает в себя:
- Интерпретатор Python (~10 MB)
- Стандартную библиотеку Python
- Tkinter и зависимости (~20-30 MB)
- Ваш код

Минимальный размер GUI приложения на Python + Tkinter: ~40-50 MB

## Дополнительная настройка

### Добавление иконки

1. Создайте или скачайте иконку в формате .ico
2. Добавьте параметр `--icon=path/to/icon.ico` к команде PyInstaller
3. Или отредактируйте ZapretManager.spec, указав путь в параметре `icon=`

### Режим отладки (с консолью)

Для отладки можно собрать версию с консольным окном:

```bash
pyinstaller --name ZapretManager --onedir zapret_manager/__main__.py
```

Или измените в spec-файле: `console=True`

### Уменьшение размера

Отключите UPX сжатие (может помочь при ложных срабатываниях антивируса):

```bash
pyinstaller --name ZapretManager --onedir --windowed --upx-exclude="*.dll" zapret_manager/__main__.py
```

## Структура проекта

```
zapret-manager/
├── build.py                    # Скрипт автоматической сборки
├── ZapretManager.spec          # Конфигурация PyInstaller
├── README_BUILD.md             # Эта инструкция
└── zapret_manager/             # Исходный код проекта
    ├── __main__.py             # Точка входа
    ├── gui.py                  # GUI модуль
    ├── config.py               # Конфигурация
    ├── utils.py                # Утилиты
    ├── service_manager.py      # Управление сервисом
    └── bat_parser.py           # Парсер BAT файлов
```

## Примечания

- Сборка работает только на Windows (создает Windows .exe)
- Для кроссплатформенной сборки используйте GitHub Actions или виртуальную машину Windows
- Готовый exe-файл работает на Windows 7 и новее
