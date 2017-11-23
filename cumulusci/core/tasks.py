""" Tasks are the basic unit of execution in CumulusCI.

Subclass BaseTask or a descendant to define custom task logic
"""
from __future__ import unicode_literals

from builtins import object
import logging

from cumulusci.core.exceptions import TaskRequiresSalesforceOrg
from cumulusci.core.exceptions import TaskOptionsError
from cumulusci.core.task_behaviors import PollOrRetryMixin
from cumulusci.core.task_options import CCIOptionHandlerMixin, MarshmallowOptionHandlerMixin

class Task(object):
    """ BaseTask provides the core execution logic for a Task

    Subclass BaseTask and provide a `_run_task()` method with your
    code.
    """
    task_options = {}
    salesforce_task = False  # Does this task require a salesforce org?

    def __init__(self, project_config, task_config, org_config=None, flow=None, **kwargs):
        self.project_config = project_config
        self.task_config = task_config
        self.org_config = org_config

        # dict of return_values that can be used by task callers
        self.return_values = {}

        # simple result object for introspection, often a return_code
        self.result = None

        # the flow for this task execution
        self.flow = flow

        if self.salesforce_task and not self.org_config:
            raise TaskRequiresSalesforceOrg(
                'This task requires a Saleforce org_config but' +
                ' none was passed to the Task constructor'
            )
        self._init_logger()
        self._init_mixins()
        self._init_options(kwargs)
        self._validate_options()
        self._update_credentials()
        self._init_task()

    def _init_logger(self):
        """ Initializes self.logger """
        self.logger = logging.getLogger(__name__)

    def _init_options(self, kwargs):
        """ Initializes self.options """
        self.options = self.task_config.options
        if self.options is None:
            self.options = {}
        if kwargs:
            self.options.update(kwargs)

        # Handle dynamic lookup of project_config values via $project_config.attr
        for option, value in list(self.options.items()):
            try:
                if value.startswith('$project_config.'):
                    attr = value.replace('$project_config.', '', 1)
                    self.options[option] = getattr(
                        self.project_config, attr, None)
            except AttributeError:
                pass


    def get_task_options(self):
        assert self.task_options is not None, (
            "'%s' needs a task_config or to override get task config!" % self.__class__.__name__
        )

        task_options = self.task_options
        return task_options

    def _validate_options(self):
        missing_required = []
        for name, config in list(self.get_task_options().items()):
            if config.get('required') is True and name not in self.options:
                missing_required.append(name)

        if missing_required:
            raise TaskOptionsError(
                '{} requires the options ({}) '
                'and no values were provided'.format(
                    self.__class__.__name__,
                    ', '.join(missing_required),
                )
            )

    def __call__(self):
        try:
            self._log_begin()
            self.result = self._run_task()
            return self.return_values
        except Exception as e:
            self._process_exception(e)
            raise

    def _init_mixins(self):
        pass

    def _update_credentials(self):
        """ Override to do any logic to refresh credentials """
        pass

    def _init_task(self):
        """ Override to implement dynamic logic for initializing the task. """
        pass

    def _process_exception(self, e):
        pass

    def _run_task(self):
        """ Subclasses should override to provide their implementation """
        pass

    def _log_begin(self):
        """ Log the beginning of the task execution """
        self.logger.info('Beginning task: %s', self.__class__.__name__)
        if self.salesforce_task and not self.flow:
            self.logger.info('%15s %s', 'As user:', self.org_config.username)
            self.logger.info('%15s %s', 'In org:', self.org_config.org_id)
        self.logger.info('')


class SchematicTask(MarshmallowOptionHandlerMixin, Task):
    pass


class BaseTask(CCIOptionHandlerMixin, PollOrRetryMixin, Task):
    def _init_mixins(self):
        # If sentry is configured, initialize sentry for error capture
        self.project_config.init_sentry()

        return super(BaseTask, self)._init_mixins()

    def _process_exception(self, e):
        if self.project_config.use_sentry:
            self.logger.info('Logging error to sentry.io')

            tags = {
                'task class': self.__class__.__name__,
            }
            if self.org_config:
                tags['org username'] = self.org_config.username
                tags['scratch org'] = self.org_config.scratch is True
            for key, value in list(self.options.items()):
                tags['option_' + key] = value
            self.project_config.sentry.tags_context(tags)

            resp = self.project_config.sentry.captureException()
            self.project_config.sentry_event = resp
