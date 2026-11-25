# Zapret EXE

Zapret Manager — экспериментальный графический интерфейс для Windows, который работает с уже установленными сборками Zapret. Интерфейс позволяет переключать профили и управлять запуском из окна приложения или системного трея.

[![Лицензия MIT](https://img.shields.io/badge/license-MIT-427259)](LICENSE)

## Что есть в репозитории

| Материал | Содержание |
| --- | --- |
| [main](main) | Основной монолитный прототип на Python и Tkinter |
| [app](app) | Более ранний вариант интерфейса |
| [PR #4](https://github.com/Lizard51/zapret-exe/pull/4) | Разбиение приложения на пакет и модули |
| [PR #8](https://github.com/Lizard51/zapret-exe/pull/8) | Эксперименты со сборкой Windows-приложения |

В GitHub пока доступны исходники и рабочие ветки. Готовый установщик в [Releases](https://github.com/Lizard51/zapret-exe/releases) ещё не опубликован.

## Зависимости

Для исходного прототипа нужны Windows, Python с Tkinter, CustomTkinter, Pillow и pystray. Менеджер использует отдельную локальную установку Zapret. Сведения о происхождении внешних компонентов собраны в [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Лицензия

Авторский код менеджера распространяется по [лицензии MIT](LICENSE). У компонентов Zapret и WinDivert собственные условия лицензирования.
