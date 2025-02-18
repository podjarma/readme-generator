import os
from functools import cached_property
from typing import List, Dict, Optional

from jinja2.compiler import F
from pydantic import (
    Field,
    FilePath,
    HttpUrl,
    NonNegativeInt,
    BaseModel,
    ValidationError,
    computed_field,
    field_validator,
    DirectoryPath,
    SecretStr
)
from pydantic_core.core_schema import ValidationInfo

from pydantic_settings import BaseSettings, SettingsConfigDict
from logging import INFO, DEBUG, WARNING, ERROR, CRITICAL, getLogger, Logger, Formatter, StreamHandler


class CustomFormatter(Formatter):
    grey = '\x1b[38;20m'
    yellow = '\x1b[33;20m'
    red = '\x1b[31;20m'
    bold_red = '\x1b[31;1m'
    reset = '\x1b[0m'
    msg_format = '[%(asctime)s] [%(levelname)s] %(message)s'

    FORMATS = {
        DEBUG: grey + msg_format + reset,
        INFO: grey + msg_format + reset,
        WARNING: yellow + msg_format + reset,
        ERROR: red + msg_format + reset,
        CRITICAL: bold_red + msg_format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = Formatter(log_fmt, '%d-%m-%Y %H:%M:%S')
        return formatter.format(record)


def logger_config(level: int = INFO) -> Logger:
    logger = getLogger('root')
    logger.setLevel(level)
    stream_handler = StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(CustomFormatter())
    logger.addHandler(stream_handler)
    return logger


class ProductsItem(BaseModel):
    production: str
    product_name: str
    project_id: Optional[NonNegativeInt] = None
    main_project: Optional[str] = None
    fix_version_keyword: Optional[str] = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='allow')
    logger: Logger = getLogger('root')

    gitlab_token: SecretStr = Field(...)
    ci_job_id: Optional[NonNegativeInt] = Field(default=None, frozen=True, )
    ci_job_url: Optional[HttpUrl] = Field(default=None, frozen=True, )
    merge_request_iid: Optional[NonNegativeInt] = Field(default=None, frozen=True, )
    source_branch: Optional[str] = Field(default=None, frozen=True, )
    source_project_id: Optional[NonNegativeInt] = Field(default=None, frozen=True, )
    current_project_id: Optional[NonNegativeInt] = Field(default=None, frozen=True, alias='CI_PROJECT_ID')
    stage: Optional[str] = Field(default=None, frozen=True, )

    gitlab_url: HttpUrl = Field('https://git.edu-infra.ru', frozen=True,
                                description='URL для доступа к GitLab. При запуске в локальном окружении будет использован URL полученный от Teleport после авторизации')

    product: Optional[str] = Field(default=None, frozen=True, )
    namespace: str = Field(default='', frozen=True, alias='CI_PROJECT_ROOT_NAMESPACE')
    project_dir: DirectoryPath = Field(default=os.getcwd(), frozen=True)

    readme_pattern: dict = Field(default={
        'team': {'name': '<Name>'},
        'link': '<Link>',
        'jira-project': '<https://jira.pcbltools.ru/jira/projects/....>',
        'description': '<Description>',
        'load-testing': [
            {
                'date': '<Date>',
                'link': 'https://confluence.pcbltools.ru/XXX'
            }
        ],
        'parameters': {
            'configmap': [],
            'secret': []
        }
    }, frozen=True, description='Шаблон YAML файла для генерации Readme')

    list_of_checked_paremeters: List[str] = Field(
        default=['configmap', 'secret'],
        frozen=True,
        description='Ключи по которым находятся параметры, необходимые для генерации Readme', )

    @computed_field
    @cached_property
    def local_mode(self) -> bool:
        if self.ci_job_id:
            self.logger.info('Установлен режим работы с окружением GitLab')
            return False
        else:
            self.logger.info('Установлен локальный режим')
            return True

    @computed_field
    def get_log_level(self) -> int:
        return self.logger.getEffectiveLevel()

logger = logger_config(INFO)

try:
    settings = Settings()

except ValidationError as e:
    logger.error(f'Exception:{e.json(indent=4)}')
