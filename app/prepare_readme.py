import re
import gitlab.exceptions
from gitlab.v4.objects import Project, MergeRequest
from config.settings import logger, settings
from ruamel.yaml import YAML, StringIO
from controller.gitlab import get_gitlab, get_repository_tree, get_file, create_commit


def is_new_readme(project: Project, branch) -> bool:
    """
        Метод проверяет существование файла readme.yaml в главной ветке целевого проекта
    """
    try:
        # Пытаемся получить информацию о файле
        project.files.get(file_path='README.yaml', ref=branch)
        return True

    except gitlab.GitlabGetError as e:
        if e.response_code == 404:
            return False
        raise  # Повторно вызываем исключение если это не 404 ошибка
    except Exception as e:
        print(f"Произошла ошибка: {str(e)}")
        return False


def _empty_parameters() -> dict:
    """
        Пустые списки параметров по секциям configmap и secret.
    """
    return {name: [] for name in settings.list_of_checked_paremeters}


def _collect_parameters(config, result: dict, seen: dict) -> None:
    """
        Добавляет ключи configmap и secret всех сервисов.
        Секцию без словаря пропускает, повторяющиеся имена не дублирует.
    """
    if not isinstance(config, dict):
        return

    for service, values in config.items():
        if not isinstance(values, dict):
            logger.debug(f'Ключ {service} пропущен: значение не является словарём')
            continue
        for parameter in result:
            section = values.get(parameter)
            if not isinstance(section, dict):
                logger.debug(f'У сервиса {service} нет секции {parameter}')
                continue
            for key in section:
                if key in seen[parameter]:
                    continue
                seen[parameter].add(key)
                result[parameter].append(key)


def get_parameters(project: Project, branch: str) -> dict:
    """
        Метод получает параметры всех сервисов из values-prod.yaml.
        Возвращает словарь {'configmap': [...], 'secret': [...]}.
    """
    result = _empty_parameters()
    seen = {name: set() for name in result}
    logger.info(f'Начата генерация readme для проекта: {project.name} из ветки {branch}')

    try:
        tree = get_repository_tree(project, branch, path='.helm')
    except Exception as e:
        logger.error(f'Ошибка при получении дерева репозитория: {e}')
        return None

    if tree is None:
        logger.error(f'Дерево .helm в ветке {branch} не получено')
        return None

    # Поиск файлов values-prod.yaml
    files = [i for i in tree if i.get('type') == 'blob' and re.search(r'values-prod.yaml', i.get('name'))]

    for file in files:
        try:
            raw_file = get_file(project, file.get('path'), branch=branch)
            if not raw_file:
                continue
            config = YAML(typ='safe', pure=True).load(raw_file)
            _collect_parameters(config, result, seen)
        except Exception as e:
            logger.error(f'Ошибка при загрузке файла {file.get("path")}: {e}')
            continue

    return result


def prepare_yaml(parameters: dict) -> dict:
    """
    Метод формирует словарь на основе шаблона result
    """
    logger.info("Формируем README.yaml")

    #TODO Необходимо доставать шаблон из settings
    result = {
        'team': {'name': '<NAME>'},
        'link': '<LINK>',
        'jira-project': '<LINK>',
        'description': '<DESCRIPTION>',
        'load-testing': [
            {
                'date': '<DATE>',
                'link': '<LINK>'
            }
        ],
        'parameters': _empty_parameters()
    }

    for kind in result['parameters']:
        for param in parameters.get(kind, []):
            result['parameters'][kind].append({
                'name': param,
                'description': '<DESCRIPTION>'
            })

    return result


def is_edited(mr: MergeRequest) -> bool:
    """
        Метод проверяет были ли изменения в файле values_prod.yaml
    """
    changes = mr.changes()
    files = [diff['new_path'] for diff in changes['changes']]
    if '.helm/values-prod.yaml' in files:
        return True
    return False


def compare_configs(dev_parameters, feature_parameters) -> tuple[list, list]:
    """
        Метод принимает два списка параметров и возвращает кортеж из добавленных и удалённых параметров
    """
    dev = set(dev_parameters)
    feature = set(feature_parameters)
    added = list(feature - dev)  # Элементы, которые есть в list2, но нет в list1
    removed = list(dev - feature)  # Элементы, которые есть в list1, но нет в list2
    return added, removed


def _append_missing(items: list, names) -> None:
    """
        Добавляет параметры, которых ещё нет в списке.
    """
    existing = {line.get('name') for line in items}
    for name in names:
        if name in existing:
            continue
        items.append({'name': name, 'description': '<DESCRIPTION>'})
        existing.add(name)


def _without_removed(items: list, removed) -> list:
    """
        Возвращает список без параметров, которые нужно удалить.
    """
    removed_names = set(removed)
    return [line for line in items if line.get('name') not in removed_names]


def update_yaml(project:Project, branch:str, added_cfgm, removed_cfgm, added_sec, removed_sec) -> dict:
    """
        Получаем существующий ямл и вносим изменения на основе added и removed параметров
        Это плохая функция, её стоит бы переписать, но лучше идей у меня нет
    """
    logger.info('Обновляем ямл')
    #Получаем ямл который есть в основной ветка
    try:
        tree = get_repository_tree(project, branch, path='.')
    except Exception as e:
        logger.error(f'Ошибка при получении дерева репозитория: {e}')
        return None
    # Поиск файлов README.yaml
    files = [i for i in tree if i.get('type') == 'blob' and re.search(r'README.yaml', i.get('name'))]

    config = {}
    for file in files:
        try:
            raw_file = get_file(project, file.get('path'), branch=branch)
            if raw_file:
                config = YAML(typ='safe', pure=True).load(raw_file)
        except Exception as e:
            logger.error(f'Ошибка при загрузке файла {file.get("path")}: {e}')
            continue

    parameters = config.setdefault('parameters', {})
    parameters.setdefault('configmap', [])
    parameters.setdefault('secret', [])

    #Добавляем новые параметры, уже описанные имена не дублируем
    _append_missing(parameters['configmap'], added_cfgm)
    _append_missing(parameters['secret'], added_sec)

    #Удаляем старые параметры отдельным списком, чтобы не пропускать соседние имена
    parameters['configmap'] = _without_removed(parameters['configmap'], removed_cfgm)
    parameters['secret'] = _without_removed(parameters['secret'], removed_sec)

    return config


def save_yaml(parameters: dict):
    """
        Метод генерирует ямл на основе словаря и сохраняет в yaml_str
    """
    yaml = YAML()
    stream = StringIO()
    yaml.dump(parameters, stream)
    yaml_str = stream.getvalue()
    stream.close()
    logger.info('YAML сгенерирован')

    return yaml_str


def gen_yaml(project:Project, mr:MergeRequest):
    if not is_new_readme(project, mr.target_branch):
        logger.info("Файл README.yaml не найден, генерируем новый")
        parameters = get_parameters(project, mr.target_branch)
        if parameters is None:
            logger.error('Не удалось получить параметры values-prod.yaml')
            exit(1)
        yaml_to_save = save_yaml(prepare_yaml(parameters))
        create_commit(project, mr.source_branch, 'README.yaml', 'create', yaml_to_save)
    else:
        logger.info("Файл README.yaml найден")
        if is_edited(mr):
            #Получаем параметры values-prod из dev и feature веток
            dev_params = get_parameters(project, mr.target_branch)
            feature_params = get_parameters(project, mr.source_branch)
            if dev_params is None or feature_params is None:
                logger.error('Не удалось получить параметры values-prod.yaml')
                exit(1)

            #находим разницу для конфигов
            configmap_added, configmap_removed = compare_configs(dev_params['configmap'], feature_params['configmap'])
            secret_added, secret_removed = compare_configs(dev_params['secret'], feature_params['secret'])

            #обновляем существующий ямл
            config = update_yaml(project, mr.target_branch, configmap_added, configmap_removed, secret_added, secret_removed)

            #коммитим
            yaml_to_save = save_yaml(config)
            create_commit(project, mr.source_branch, 'README.yaml', 'update', yaml_to_save)
            logger.info('YAML успешно создан')
        else:
            logger.info("Изменения отсутствую")
            exit(1)
