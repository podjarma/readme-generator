from gitlab.v4.objects import Project, MergeRequest
from controller.gitlab import get_gitlab
import gitlab.exceptions

from app.prepare_readme import gen_yaml, get_parameters
from app.gen_readme import create_markdown_file
from config.settings import settings, logger


def main():
    gl = get_gitlab()
    if settings.source_project_id and settings.merge_request_iid:
        try:
            logger.info(f'Получение основных параметров project {settings.source_project_id}')
            project = gl.projects.get(settings.source_project_id)
        except gitlab.exceptions.GitlabGetError:
            logger.error(f'Проект с ID: {settings.source_project_id} не найден.')
            exit(1)

        try:
            logger.info(f'Получение основных параметров merge request {settings.merge_request_iid}')
            merge_request = project.mergerequests.get(settings.merge_request_iid)
        except Exception as e:
            raise Exception(f'Ошибка при получении merge request {settings.merge_request_iid}: {e}')
        if not merge_request:
            raise Exception('MergeRequest не получен')

        if settings.stage == 'prepare':
            gen_yaml(project, merge_request)
        elif settings.stage == 'generate':
            create_markdown_file(project, merge_request)
    else:
        logger.info("Не заданы параметры project_id или merge_request_id")


if __name__ == '__main__':
    main()
