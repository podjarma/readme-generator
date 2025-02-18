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


def get_parameters(project: Project, branch: str) -> list:
    """
        Метод получает список параметров values-prod.yaml
    """
    result = []
    logger.info(f'Начата генерация readme для проекта: {project.name} из ветки {branch}')

    try:
        tree = get_repository_tree(project, branch, path='.helm')
    except Exception as e:
        logger.error(f'Ошибка при получении дерева репозитория: {e}')
        return None

    # Поиск файлов values-prod.yaml
    files = [i for i in tree if i.get('type') == 'blob' and re.search(r'values-prod.yaml', i.get('name'))]

    config = {}
    for file in files:
        try:
            raw_file = get_file(project, file.get('path'), branch=branch)
            if raw_file:
                config = YAML(typ='safe', pure=True).load(raw_file)
        except Exception as e:
            logger.error(f'Ошибка при загрузке файла {file.get("path")}: {e}')
            continue

    # Сбор параметров configmap и secret
    for service, values in config.items():
        for parameter in ['configmap', 'secret']:
            result.append(list(values[parameter].keys()))

    return result


def prepare_yaml(parameters: list) -> dict:
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
        'parameters': {
            'configmap': [],
            'secret': []
        }
    }

    # Заполняем configmap
    for param in parameters[0]:
        result['parameters']['configmap'].append({
            'name': param,
            'description': '<DESCRIPTION>'
        })

    # Заполняем secret
    for param in parameters[1]:
        result['parameters']['secret'].append({
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

    #Добавляем новые параметры
    for parameter in added_cfgm:
        config['parameters']['configmap'].append({'name': parameter, 'description': '<DESCRIPTION>'})
    for parameter in added_sec:
        config['parameters']['secret'].append({'name': parameter, 'description': '<DESCRIPTION>'})

    #Удаляем старые параметры
    for line in config['parameters']['configmap']:
        if line.get('name') in removed_cfgm:
            config['parameters']['configmap'].remove(line)
    for line in config['parameters']['secret']:
        if line.get('name') in removed_sec:
            config['parameters']['secret'].remove(line)

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
    if not is_new_readme(project, mr.targer_brunch):
        logger.info("Файл README.yaml не найден, генерируем новый")
        yaml_to_save = save_yaml(prepare_yaml(get_parameters(project, mr.targer_brunch)))
        create_commit(project, mr.source_branch, 'README.yaml', 'create', yaml_to_save)
    else:
        logger.info("Файл README.yaml найден")
        if is_edited(mr):
            #Получаем параметры values-prod из dev и feature веток
            dev_params = get_parameters(project, mr.targer_brunch)
            feature_params = get_parameters(project, mr.source_branch)

            #находим разницу для конфигов
            configmap_added, configmap_removed = compare_configs(dev_params[0], feature_params[0])
            secret_added, secret_removed = compare_configs(dev_params[1], feature_params[1])

            #обновляем существующий ямл
            config = update_yaml(project, mr.targer_brunch, configmap_added, configmap_removed, secret_added, secret_removed)

            #коммитим
            yaml_to_save = save_yaml(config)
            create_commit(project, mr.source_branch, 'README.yaml', 'update', yaml_to_save)
            logger.info('YAML успешно создан')
        else:
            logger.info("Изменения отсутствую")
            exit(1)
