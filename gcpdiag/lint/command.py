# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""gcpdiag lint command."""

import argparse
import logging
import re
import sys

from gcpdiag import config, lint, models, utils
from gcpdiag.lint import gce, gke, iam, report_terminal
from gcpdiag.queries import apis


def _flatten_multi_arg(arg_list):
  """Flatten a list of comma-separated values, like:
  ['a', 'b, c'] -> ['a','b','c']
  """
  for arg in arg_list:
    for split_item in re.split(r'\s*,\s*', arg):
      yield split_item


def run(argv) -> int:
  del argv
  parser = argparse.ArgumentParser(
      description='Run diagnostics in GCP projects.', prog='gcpdiag lint')

  parser.add_argument('--auth-adc',
                      help='Authenticate using Application Default Credentials',
                      action='store_true')

  parser.add_argument(
      '--auth-key',
      help='Authenticate using a service account private key file',
      metavar='FILE')

  parser.add_argument('--auth-oauth',
                      help='Authenticate using OAuth user authentication',
                      action='store_true')

  parser.add_argument('--project',
                      metavar='P',
                      required=True,
                      help='Project ID of project to inspect')

  parser.add_argument(
      '--billing-project',
      metavar='P',
      help='Project used for billing/quota of API calls done by gcpdiag '
      '(default is the inspected project, requires '
      '\'serviceusage.services.use\' permission)')

  parser.add_argument('--show-skipped',
                      help='Show skipped rules',
                      action='store_true',
                      default=False)

  parser.add_argument('--hide-skipped',
                      help=argparse.SUPPRESS,
                      action='store_false',
                      dest='show_skipped')

  parser.add_argument('--hide-ok',
                      help='Hide rules with result OK',
                      action='store_true',
                      default=False)

  parser.add_argument('--show-ok',
                      help=argparse.SUPPRESS,
                      action='store_false',
                      dest='hide_ok')

  parser.add_argument(
      '--include',
      help=('Include rule pattern (e.g.: `gke`, `gke/*/2021*`). '
            'Multiple pattern can be specified (comma separated, '
            'or with multiple arguments)'),
      action='append')

  parser.add_argument('--exclude',
                      help=('Exclude rule pattern (e.g.: `BP`, `*/*/2022*`)'),
                      action='append')

  parser.add_argument('-v',
                      '--verbose',
                      action='count',
                      default=0,
                      help='Increase log verbosity')

  parser.add_argument(
      '--within-days',
      metavar='D',
      type=int,
      help=
      f'How far back to search logs and metrics (default: {config.WITHIN_DAYS})',
      default=config.WITHIN_DAYS)

  args = parser.parse_args()

  # Initialize configuration
  config.WITHIN_DAYS = args.within_days

  # Determine what authentication should be used
  if args.auth_key:
    config.AUTH_ADC = False
    config.AUTH_KEY = args.auth_key
  elif args.auth_oauth:
    config.AUTH_ADC = False
    config.AUTH_KEY = None
  else:
    # TODO(b/195908593): use oauth as default once consent screen approved
    config.AUTH_ADC = True
    config.AUTH_KEY = None

  try:
    # This is for Google-internal use only and allows us to modify
    # default options for internal use.
    # pylint: disable=import-outside-toplevel
    from gcpdiag_google_internal import hooks
    hooks.set_google_default_options(args)
  except ImportError:
    pass

  # --include
  include_patterns = None
  if args.include:
    include_patterns = []
    for arg in _flatten_multi_arg(args.include):
      try:
        include_patterns.append(lint.LintRulesPattern(arg))
      except ValueError:
        print(f"ERROR: can't parse rule pattern: {arg}", file=sys.stderr)
        sys.exit(1)

  # --exclude
  exclude_patterns = None
  if args.exclude:
    exclude_patterns = []
    for arg in _flatten_multi_arg(args.exclude):
      try:
        exclude_patterns.append(lint.LintRulesPattern(arg))
      except ValueError:
        print(f"ERROR: can't parse rule pattern: {arg}", file=sys.stderr)
        sys.exit(1)

  # Initialize Context, Repository, and Tests.
  context = models.Context(project_id=args.project)
  repo = lint.LintRuleRepository()
  repo.load_rules(gce)
  repo.load_rules(gke)
  repo.load_rules(iam)
  # ^^^ If you add rules directory, update also pyinstaller/hook-gcpdiag.lint.py
  report = report_terminal.LintReportTerminal(
      log_info_for_progress_only=(args.verbose == 0),
      show_ok=not args.hide_ok,
      show_skipped=args.show_skipped)

  # Verify that we have access and that the CRM API is enabled
  apis.verify_access(context.project_id)

  # Logging setup.
  logging_handler = report.get_logging_handler()
  logger = logging.getLogger()
  # Make sure we are only using our own handler
  logger.handlers = []
  logger.addHandler(logging_handler)
  if args.verbose >= 2:
    logger.setLevel(logging.DEBUG)
  else:
    logger.setLevel(logging.INFO)

  # Run the tests.
  report.banner()
  apis.login()
  report.lint_start(context)
  exit_code = repo.run_rules(context, report, include_patterns,
                             exclude_patterns)

  # (google internal) Report usage information.
  details = {
      str(k): v['overall_status'] for k, v in report.rules_report.items()
  }
  utils.report_usage_if_running_at_google('lint', details)

  # Exit 0 if there are no failed rules.
  sys.exit(exit_code)
