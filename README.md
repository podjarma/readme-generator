# readme-generator

Автогенератор `README.md` для проектов в GitLab.

Версия 0.0.4

Утилита запускается в GitLab CI на merge request. Она собирает параметры сервиса из `.helm/values-prod.yaml`, готовит для команды шаблон `README.yaml` с описаниями, а затем превращает заполненный шаблон в раздел документации в `README.md`. Все изменения коммитятся через GitLab API в исходную ветку merge request.

## Как это работает

Генерация идёт в два этапа, этап выбирается переменной `STAGE`.

### Этап `prepare`: подготовка `README.yaml`

1. Если в целевой ветке MR нет `README.yaml`:
   - из `.helm/values-prod.yaml` целевой ветки берутся ключи секций `configmap` и `secret`;
   - по ним собирается шаблон `README.yaml` с заглушками `<DESCRIPTION>`, `<NAME>`, `<LINK>`, `<DATE>`;
   - шаблон коммитится в исходную ветку MR.
2. Если `README.yaml` уже есть и MR меняет `.helm/values-prod.yaml`:
   - параметры целевой и исходной веток сравниваются;
   - новые параметры добавляются в `README.yaml` с заглушкой `<DESCRIPTION>`, удалённые убираются;
   - обновлённый файл коммитится в исходную ветку MR.
3. Если `.helm/values-prod.yaml` в MR не менялся, утилита завершается с кодом `1`.

После этапа `prepare` команда вручную заполняет заглушки в `README.yaml`.

Пример `README.yaml` после подготовки:

```yaml
team:
  name: <NAME>
link: <LINK>
jira-project: <LINK>
description: <DESCRIPTION>
load-testing:
- date: <DATE>
  link: <LINK>
parameters:
  configmap:
  - name: LOG_LEVEL
    description: <DESCRIPTION>
  secret:
  - name: DB_PASSWORD
    description: <DESCRIPTION>
```

### Этап `generate`: сборка `README.md`

Этап выполняется, только если MR меняет `.helm/values-prod.yaml`, иначе утилита завершается с кодом `1`.

1. `README.yaml` читается из исходной ветки MR и превращается в Markdown: команда, ссылки на проект и Jira, описание, нагрузочное тестирование, таблицы параметров `configmap` и `secret`, дата формирования.
2. Если в целевой ветке нет `README.md`, создаётся новый файл.
3. Если `README.md` есть, заменяется только блок от заголовка `# Project Documentation` до строки `# End`. Остальной текст, написанный вручную, сохраняется.
4. Результат коммитится в исходную ветку MR.

## Структура проекта

| Путь | Назначение |
| :--- | :--- |
| `main.py` | Точка входа: получает проект и MR, запускает нужный этап |
| `app/prepare_readme.py` | Этап `prepare`: сбор параметров и формирование `README.yaml` |
| `app/gen_readme.py` | Этап `generate`: преобразование `README.yaml` в `README.md` |
| `controller/gitlab.py` | Подключение к GitLab, чтение файлов и деревьев, создание коммитов |
| `config/settings.py` | Настройки из переменных окружения и `.env`, логгер |

## Требования

- Python 3.9+
- Доступ к GitLab-инстансу и токен с правами на чтение репозитория и создание коммитов (scope `api`)
- Для локального запуска: Teleport-клиент `tsh` по пути `C:\utils\tsh`

## Установка

```bash
git clone https://github.com/podjarma/readme-generator.git
cd readme-generator
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

Настройки читаются из переменных окружения или из файла `.env` в корне проекта. Регистр имён не важен.

| Переменная | Обязательная | Описание |
| :--- | :---: | :--- |
| `GITLAB_TOKEN` | да | Токен доступа к GitLab |
| `SOURCE_PROJECT_ID` | да | ID проекта, для которого генерируется документация |
| `MERGE_REQUEST_IID` | да | Внутренний номер (IID) merge request в этом проекте |
| `STAGE` | да | Этап: `prepare` или `generate` |
| `CI_JOB_ID` | нет | Если задан, включается режим GitLab CI, иначе локальный режим |
| `GITLAB_URL` | нет | Адрес GitLab в режиме CI, по умолчанию `https://git.edu-infra.ru` |

Если не заданы `SOURCE_PROJECT_ID` или `MERGE_REQUEST_IID`, утилита пишет об этом в лог и ничего не делает.

## Запуск

### В GitLab CI

`CI_JOB_ID` GitLab выставляет сам, поэтому утилита подключается к `GITLAB_URL` по токену. Остальные переменные нужно передать в job, например:

```bash
export SOURCE_PROJECT_ID=$CI_MERGE_REQUEST_PROJECT_ID
export MERGE_REQUEST_IID=$CI_MERGE_REQUEST_IID
export STAGE=prepare   # или generate
python main.py
```

### Локально

Без `CI_JOB_ID` утилита вызывает `C:\utils\tsh app login gitlab`, берёт из вывода путь к сертификату, ключ и URL GitLab и подключается через Teleport с токеном `GITLAB_TOKEN`.

```bash
python main.py
```

## Известные ограничения

- Этап `prepare` сейчас не работает: в `app/prepare_readme.py` используется атрибут `mr.targer_brunch` вместо `mr.target_branch`, из-за чего падает `AttributeError`.
- Если в `.helm/values-prod.yaml` несколько сервисов, в `README.yaml` попадают параметры только первого из них. Если у сервиса нет секции `configmap` или `secret`, утилита падает с `KeyError`.
- Оба этапа завершаются с кодом `1`, если MR не меняет `.helm/values-prod.yaml`. В CI такой job будет отмечен как упавший.
- Сообщение коммита всегда одно: «Создан новый файл README.yaml, который необходимо заполнить», в том числе для `README.md`.
- Путь к `tsh` зашит в код, поэтому локальный режим работает только на Windows.
