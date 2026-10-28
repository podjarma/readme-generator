import os
import subprocess
import unittest
from unittest.mock import ANY, MagicMock, patch

os.environ.setdefault('GITLAB_TOKEN', 'test-token')

from app.gen_readme import create_markdown_file
from app.prepare_readme import gen_yaml, get_parameters, prepare_yaml, update_yaml
from config.settings import Settings, settings
from controller.gitlab import commit_message, create_commit, get_credentials


TSH_OUTPUT = '\n'.join([
    'curl \\',
    '--cert "C:/temp/cert.pem" \\',
    '--key "C:/temp/key.pem" \\',
    'https://git.example.com',
])


class PrepareBranchTests(unittest.TestCase):
    def _merge_request(self):
        merge_request = MagicMock(spec=['source_branch', 'target_branch'])
        merge_request.source_branch = 'feature'
        merge_request.target_branch = 'dev'
        return merge_request

    @patch('app.prepare_readme.create_commit')
    @patch('app.prepare_readme.get_parameters', return_value={'configmap': ['LOG_LEVEL'], 'secret': ['DB_PASSWORD']})
    @patch('app.prepare_readme.is_new_readme', return_value=False)
    def test_new_yaml_reads_target_branch(self, is_new_readme, get_parameters, create_commit_mock):
        project = MagicMock()
        merge_request = self._merge_request()

        gen_yaml(project, merge_request)

        is_new_readme.assert_called_once_with(project, 'dev')
        get_parameters.assert_called_once_with(project, 'dev')
        create_commit_mock.assert_called_once()
        self.assertEqual(create_commit_mock.call_args.args[1], 'feature')
        self.assertEqual(create_commit_mock.call_args.args[2], 'README.yaml')
        self.assertEqual(create_commit_mock.call_args.args[3], 'create')

    @patch('app.prepare_readme.create_commit')
    @patch('app.prepare_readme.update_yaml', return_value={'parameters': {}})
    @patch('app.prepare_readme.get_parameters', return_value={'configmap': ['LOG_LEVEL'], 'secret': ['DB_PASSWORD']})
    @patch('app.prepare_readme.is_edited', return_value=True)
    @patch('app.prepare_readme.is_new_readme', return_value=True)
    def test_update_yaml_reads_target_branch(
        self, is_new_readme, is_edited, get_parameters, update_yaml, create_commit_mock
    ):
        project = MagicMock()
        merge_request = self._merge_request()

        gen_yaml(project, merge_request)

        is_new_readme.assert_called_once_with(project, 'dev')
        self.assertTrue(is_edited.called)
        self.assertEqual(get_parameters.call_args_list[0].args[1], 'dev')
        self.assertEqual(get_parameters.call_args_list[1].args[1], 'feature')
        self.assertEqual(update_yaml.call_args.args[1], 'dev')
        self.assertEqual(create_commit_mock.call_args.args[3], 'update')

    @patch('app.prepare_readme.is_edited', return_value=False)
    @patch('app.prepare_readme.is_new_readme', return_value=True)
    def test_no_helm_changes_still_exits_with_error(self, is_new_readme, is_edited):
        merge_request = self._merge_request()

        with self.assertRaises(SystemExit) as ctx:
            gen_yaml(MagicMock(), merge_request)

        self.assertEqual(ctx.exception.code, 1)
        is_new_readme.assert_called_once_with(ANY, 'dev')
        self.assertTrue(is_edited.called)


class GenerateExitTests(unittest.TestCase):
    @patch('app.gen_readme.is_edited', return_value=False)
    def test_no_helm_changes_still_exits_with_error(self, is_edited):
        with self.assertRaises(SystemExit) as ctx:
            create_markdown_file(MagicMock(), MagicMock())

        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(is_edited.called)


class CommitMessageTests(unittest.TestCase):
    def test_messages_depend_on_file_and_action(self):
        expected = {
            ('create', 'README.yaml'): 'Создан новый файл README.yaml, который необходимо заполнить',
            ('update', 'README.yaml'): 'Обновлён README.yaml по изменениям .helm/values-prod.yaml',
            ('create', 'README.md'): 'Создан файл README.md',
            ('update', 'README.md'): 'Обновлён раздел документации в README.md',
        }
        for key, message in expected.items():
            self.assertEqual(commit_message(*key), message)

    def test_create_commit_sends_matching_message(self):
        project = MagicMock()
        project.name = 'demo'
        project.commits.create.return_value = MagicMock(id='abc', web_url='https://example.test/commit')

        create_commit(project, 'feature', 'README.md', 'update', 'text')

        commit_data = project.commits.create.call_args.args[0]
        self.assertEqual(commit_data['branch'], 'feature')
        self.assertEqual(commit_data['commit_message'], 'Обновлён раздел документации в README.md')
        self.assertEqual(commit_data['actions'][0]['action'], 'update')
        self.assertEqual(commit_data['actions'][0]['file_path'], 'README.md')
        self.assertEqual(commit_data['actions'][0]['content'], 'text')


class TeleportTests(unittest.TestCase):
    def test_default_tsh_command_is_from_path(self):
        self.assertEqual(Settings.model_fields['tsh_path'].default, 'tsh')

    def test_login_uses_configured_tsh_path(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=TSH_OUTPUT, stderr='')
        previous = settings.tsh_path
        settings.tsh_path = r'C:\utils\tsh.exe'
        try:
            with patch('controller.gitlab.subprocess.run', return_value=completed) as run:
                cert, key, url = get_credentials()
        finally:
            settings.tsh_path = previous

        run.assert_called_once_with(
            [r'C:\utils\tsh.exe', 'app', 'login', 'gitlab'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cert, 'C:/temp/cert.pem')
        self.assertEqual(key, 'C:/temp/key.pem')
        self.assertEqual(url, 'https://git.example.com')

    def test_missing_url_raises_clear_error(self):
        output = '\n'.join([
            '--cert "C:/temp/cert.pem" \\',
            '--key "C:/temp/key.pem" \\',
        ])
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr='')
        with patch('controller.gitlab.subprocess.run', return_value=completed):
            with self.assertRaises(ValueError) as ctx:
                get_credentials()

        self.assertIn('URL', str(ctx.exception))

    def test_missing_tsh_explains_tsh_path(self):
        with patch('controller.gitlab.subprocess.run', side_effect=FileNotFoundError('tsh')):
            with self.assertRaises(ValueError) as ctx:
                get_credentials()

        self.assertIn('TSH_PATH', str(ctx.exception))


class ParameterCollectionTests(unittest.TestCase):
    def test_collects_every_service_and_skips_missing_sections(self):
        values_main = """
svc-a:
  configmap:
    A_ONE: "1"
  secret:
    A_SEC: "s"
svc-b:
  configmap:
    B_ONE: "1"
    A_ONE: "same"
svc-c:
  image: nginx
plain: just-text
svc-e:
  configmap:
  secret: []
"""
        values_extra = """
svc-d:
  secret:
    D_SEC: "x"
  configmap:
    D_ONE: "1"
"""
        tree = [
            {'type': 'blob', 'name': 'values-prod.yaml', 'path': '.helm/values-prod.yaml'},
            {'type': 'blob', 'name': 'values-prod.yaml', 'path': '.helm/extra/values-prod.yaml'},
            {'type': 'blob', 'name': 'values-dev.yaml', 'path': '.helm/values-dev.yaml'},
        ]
        files = {
            '.helm/values-prod.yaml': values_main,
            '.helm/extra/values-prod.yaml': values_extra,
        }
        project = MagicMock()
        project.name = 'demo'

        with patch('app.prepare_readme.get_repository_tree', return_value=tree), \
             patch('app.prepare_readme.get_file', side_effect=lambda project, path, branch: files.get(path)):
            parameters = get_parameters(project, 'dev')

        self.assertEqual(parameters['configmap'], ['A_ONE', 'B_ONE', 'D_ONE'])
        self.assertEqual(parameters['secret'], ['A_SEC', 'D_SEC'])

    def test_prepare_yaml_keeps_parameters_from_all_services(self):
        prepared = prepare_yaml({
            'configmap': ['A_ONE', 'B_ONE'],
            'secret': ['A_SEC'],
        })

        self.assertEqual(
            [item['name'] for item in prepared['parameters']['configmap']],
            ['A_ONE', 'B_ONE'],
        )
        self.assertEqual(
            [item['name'] for item in prepared['parameters']['secret']],
            ['A_SEC'],
        )
        self.assertTrue(all(item['description'] == '<DESCRIPTION>' for item in prepared['parameters']['configmap']))

    def test_update_removes_every_listed_name(self):
        readme = """
parameters:
  configmap:
    - name: A
      description: da
    - name: B
      description: db
    - name: C
      description: dc
  secret:
    - name: S1
      description: ds
    - name: S2
      description: ds2
"""
        tree = [{'type': 'blob', 'name': 'README.yaml', 'path': 'README.yaml'}]
        project = MagicMock()

        with patch('app.prepare_readme.get_repository_tree', return_value=tree), \
             patch('app.prepare_readme.get_file', return_value=readme):
            config = update_yaml(project, 'dev', ['D'], ['A', 'B'], [], ['S1'])

        self.assertEqual([item['name'] for item in config['parameters']['configmap']], ['C', 'D'])
        self.assertEqual([item['name'] for item in config['parameters']['secret']], ['S2'])
        self.assertEqual(config['parameters']['configmap'][-1]['description'], '<DESCRIPTION>')


if __name__ == '__main__':
    unittest.main()
