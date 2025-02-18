import datetime
import re
from typing import Dict, Any

import gitlab
from gitlab.v4.objects import Project, MergeRequest
from ruamel.yaml import YAML
from config.settings import logger
from controller.gitlab import create_commit, get_file, get_repository_tree


def is_new_readme(project: Project, branch) -> bool:
    """
        Метод проверяет существование файла readme.md в главной ветке целевого проекта
    """
    try:
        # Пытаемся получить информацию о файле
        project.files.get(file_path='README.md', ref=branch)
        return False

    except gitlab.GitlabGetError as e:
        if e.response_code == 404:
            return True
        raise  # Повторно вызываем исключение если это не 404 ошибка
    except Exception as e:
        print(f"Произошла ошибка: {str(e)}")
        return True


def is_edited(mr: MergeRequest) -> bool:
    """
        Метод проверяет были ли изменения в файле README.yaml
    """
    changes = mr.changes()
    files = [diff['new_path'] for diff in changes['changes']]
    if '.helm/values-prod.yaml' in files:
        return True
    return False


def get_yaml(project: Project, branch: str):
    """
        Метод получает сгенерированный на предыдущем этапе ямл
    """
    try:
        tree = get_repository_tree(project, branch)
    except Exception as e:
        logger.error(f'Ошибка при получении дерева репозитория: {e}')
        return None

    # Поиск файла README.yaml
    files = [i for i in tree if i.get('type') == 'blob' and re.search(r'README.yaml', i.get('name'))]

    yaml = {}
    for file in files:
        try:
            raw_file = get_file(project, file.get('path'), branch=branch)
            if raw_file:
                yaml = YAML(typ='safe', pure=True).load(raw_file) if file else None
        except Exception as e:
            logger.error(f'Ошибка при загрузке файла {file.get("path")}: {e}')
            continue
    return yaml


def yaml_to_markdown(yaml_data: Dict[str, Any]) -> str:
    """
        Преобразует данные из YAML в Markdown.
    """
    markdown = "# Project Documentation\n"
    markdown += f"### Дата формирования: {datetime.date.today().isoformat()}\n\n"

    # Team
    markdown += "## Team\n"
    markdown += f"- **Name:** {yaml_data.get('team', {}).get('name', 'N/A')}\n\n"

    # Links
    markdown += "## Links\n"
    markdown += f"- **Project Link:** [{yaml_data.get('link', 'N/A')}]({yaml_data.get('link', 'N/A')})\n"
    markdown += f"- **Jira Project:** [{yaml_data.get('jira-project', 'N/A')}]({yaml_data.get('jira-project', 'N/A')})\n\n"

    # Description
    markdown += "## Description\n"
    markdown += f"{yaml_data.get('description', 'N/A')}\n\n"

    # Load Testing
    markdown += "## Load Testing\n"
    for test in yaml_data.get('load-testing', []):
        markdown += f"- **Date:** {test.get('date', 'N/A')}\n"
        markdown += f"- **Link:** [{test.get('link', 'N/A')}]({test.get('link', 'N/A')})\n"
    markdown += "\n"

    # Parameters
    markdown += "## Parameters\n"
    for param_type, params in yaml_data.get('parameters', {}).items():
        markdown += f"### {param_type.capitalize()}\n"
        markdown += generate_md_table_from_dicts(params)
        markdown += "\n"
    markdown += '# End\n'
    return markdown


def create_markdown_table(headers, rows, alignments=None):
    """
        Генерирует Markdown-таблицу.

        Аргументы:
            headers (list): Заголовки столбцов (например, ["Name", "Age"])
            rows (list of lists): Данные таблицы (например, [["Alice", 25], ["Bob", 30]])
            alignments (list): Выравнивание для каждого столбца (None = по умолчанию,
                              варианты: "left", "center", "right")

        Возвращает:
            str: Готовая таблица в формате Markdown
    """
    # Проверка совпадения количества колонок
    num_columns = len(headers)
    for row in rows:
        if len(row) != num_columns:
            raise ValueError("Количество элементов в строке не совпадает с заголовками")

    # Определение выравнивания
    align_map = {
        "left": ":---",
        "center": ":---:",
        "right": "---:"
    }

    if not alignments:
        alignments = ["left"] * num_columns
    elif len(alignments) != num_columns:
        raise ValueError("Количество значений выравнивания должно совпадать с количеством колонок")

    # Создание разделителя выравнивания
    separator = "|".join([align_map.get(align, "---") for align in alignments])

    # Сборка таблицы
    table = []
    # Заголовки
    table.append("|".join(headers))
    # Разделитель
    table.append(f"|{separator}|")
    # Данные
    for row in rows:
        table.append("|".join(map(str, row)))

    return "\n".join(table)


def generate_md_table_from_dicts(data_dicts, alignments=None):
    """
    Генерирует Markdown-таблицу из списка словарей

    :param data_dicts: Список словарей с ключами 'name' и 'description'
    :param alignments: Список выравниваний для колонок (по умолчанию: left)
    :return: Готовая таблица в формате Markdown
    """
    # Проверка наличия обязательных ключей
    required_keys = ['name', 'description']
    for item in data_dicts:
        if not all(key in item for key in required_keys):
            raise ValueError("Словарь должен содержать ключи 'name' и 'description'")

    # Формируем заголовки и данные
    headers = ["Name", "Description"]
    rows = [
        [item['name'], item['description']]
        for item in data_dicts
    ]

    # Настройки выравнивания по умолчанию
    if not alignments:
        alignments = ["left", "left"]

    # Создаем таблицу
    return create_markdown_table(headers, rows, alignments)


def get_existing_readme(project: Project, branch):
    """
        Метод получает текущее README.md для обновления
    """
    try:
        tree = get_repository_tree(project, branch)
    except Exception as e:
        logger.error(f'Ошибка при получении дерева репозитория: {e}')
        return None

    # Поиск файла README.md
    files = [i for i in tree if i.get('type') == 'blob' and re.search(r'README.md', i.get('name'))]

    for file in files:
        try:
            raw_file = get_file(project, file.get('path'), branch=branch)
            if raw_file:
                return raw_file
        except Exception as e:
            logger.error(f'Ошибка при загрузке файла {file.get("path")}: {e}')
            return None


def update_readme(old_markdown, new_markdown) -> str:
    """
        Метод должен обновляет блок сгенерированного текста независимо от положения в файле, сохраняя пользовательские данные
    """
    start_pattern = r'#\s*Project\sDocumentation'
    end_pattern = r'#\s*End'
    updated_content = ''
    pattern = rf'({start_pattern}.*?{end_pattern})'
    match = re.search(pattern, old_markdown, flags=re.DOTALL)

    if match:
        old_section = match.group(1)
        updated_content = old_markdown.replace(old_section, f"{new_markdown}")

        logger.info("Документ успешно обновлен.")
    else:
        logger.info("Раздел '# Project Documentation ... # End' не найден.")

    return updated_content


def create_markdown_file(project: Project, mr: MergeRequest):
    """
        Создает Markdown-файл на основе данных из YAML-файла.
        :param branch - source_branch из merge request
    """

    if is_edited(mr):
        # Получаем подготовленный ямл из исходной ветки
        yaml_data = get_yaml(project, mr.source_branch)
        if is_new_readme(project, mr.target_branch):
            logger.info('README.md ненайден\nНачинаем генерацию нового')
            try:
                if yaml_data:
                    # Преобразовываем yaml в markdown
                    markdown_content = yaml_to_markdown(yaml_data)
                    # Коммитим markdown в исходную ветку
                    create_commit(project, mr.source_branch, 'README.md', 'create', markdown_content)
            except Exception as e:
                logger.info(f"Ошибка при создании Markdown-файла: {e}")
        else:
            logger.info('README.md ненайден\nВносим изменения в текущий документ')
            try:
                if yaml_data:
                    # Получаем текст текущего файла
                    existing_markdown = get_existing_readme(project, mr.target_branch)
                    # Получаем текст обновленный вариант
                    new_markdown = yaml_to_markdown(yaml_data)
                    # Обновляем текст текущего файла
                    markdown_content = update_readme(existing_markdown, new_markdown)
                    # Коммитим изменения
                    create_commit(project, mr.source_branch, 'README.md', 'update', markdown_content)
            except Exception as e:
                logger.info(f"Ошибка при обновлении Markdown-файла: {e}")

            logger.info(f"Файл README успешно создан")
    else:
        logger.info("Изменения отсутствуют")
        exit(1)
