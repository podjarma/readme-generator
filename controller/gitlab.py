import base64
import re
import subprocess
from gitlab.v4.objects import Project, MergeRequest
from requests import Session

from config.settings import logger, settings
from gitlab import Gitlab, GitlabGetError, GitlabCreateError

from logging import INFO
from ruamel.yaml import YAML

def get_credentials() -> ():
    """
        Метод для получения кредов для подключения к gitlab через телепорт
    """
    output = None
    logger.info('Авторизация в teleport')
    try:
        output = subprocess.getoutput('C:\\utils\\tsh app login gitlab')
    except Exception as e:
        logger.exception(f'Ошибка при авторизации в teleport: {e}')

    cert_regex = r'(?<=cert\s").+(?="\s\\)'
    key_regex = r'(?<=key\s").+(?="\s\\)'
    url_regex = r'https.+'

    cert_list = re.findall(cert_regex, output)
    key_list = re.findall(key_regex, output)
    url_list = re.findall(url_regex, output)

    if len(cert_list) != 1:
        raise ValueError(f'Не удаётся распознать путь к сертификату. Найдено путей: {len(cert_list)}')
    if len(key_list) != 1:
        raise ValueError(f'Не удаётся распознать путь к ключу. Найдено путей: {len(key_list)}')
    if len(key_list) != 1:
        raise ValueError(f'Не удаётся распознать URL. Найдено URL: {len(url_list)}')

    return cert_list[0], key_list[0], url_list[0]


def get_gitlab() -> Gitlab:
    """
        Метод для получения объекта GitLab, через который осуществляется всё взаимодействие.
    """
    logger.info('Подключение к GitLab')
    try:
        if settings.local_mode:
            cert, key, url = get_credentials()
            if cert and key:
                session = Session()
                session.cert = (cert, key)
                gl = Gitlab(url=url, session=session, private_token=settings.gitlab_token.get_secret_value())
            else:
                raise ValueError('Сертификат или ключ, для подключения к GitLab не получены')
        else:
            gl = Gitlab(url=str(settings.gitlab_url), private_token=settings.gitlab_token.get_secret_value())
    except Exception as e:
        logger.exception(f'Ошибка при подключении к GitLab: {e}')
        raise Exception(e)

    logger.info('Подключение к GitLab выполнено')
    return gl


def get_repository_tree(project: Project, ref, path=None, all=True, recursive=True):
    """
        Метод для получения дерева репозитория из GitLab
    """
    try:
        items = project.repository_tree(path=path, ref=ref, all=all, recursive=recursive)
        return items

    except GitlabGetError:
        logger.debug(f'Дерево для пути {path} в проекте {project.id}, ветки {ref} не найдено')
    except Exception as e:
        logger.exception(f'Дерево для пути {path} в проекте {project.id}, ветки {ref} не найдено. Ошибка: {e}')
        raise Exception(e)


def get_file(project: Project, file_path: str, branch: str) -> str:
    """
        Метод для получения содержимого файла, из GitLab
    """
    try:
        file = project.files.get(file_path=file_path, ref=branch)
        raw_file = base64.b64decode(file.content).decode('utf-8')
        return raw_file

    except GitlabGetError:
        logger.debug(f'Файл {file_path} в проекте {project.id} не найден')


def create_commit(project: Project, target_branch: str, file_path: str, action: str, content: str):
    """
        Метод создаёт и пушит коммит в целевую ветку проекта
    """
    logger.info(f"Коммитим в ветку {target_branch} проекта {project.name}")

    #TODO Это может быть нужно, если мы захотим коммитить в новую ветку. Но оно пока не работает.
    """
    try:
        branch = project.branches.get(target_branch)
    except GitlabCreateError:
    # Если ветки нет, создаем новую от master
        branch = project.branches.create({
            'branch': target_branch,
            'ref': 'main'
        })
    """

    # Создаем или обновляем файл
    commit_data = {
        'branch': target_branch,
        'commit_message': "Создан новый файл README.yaml, который необходимо заполнить",
        'actions': [{
            'action': action,  # create или 'update' для существующих файлов
            'file_path': file_path,
            'content': content
        }]
    }

    # Создаем коммит
    try:
        commit = project.commits.create(commit_data)

        logger.info(f"Коммит создан успешно! ID: {commit.id}")
        logger.info(f"Ссылка: {commit.web_url}")

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        raise
