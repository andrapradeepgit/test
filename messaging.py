#!/usr/bin/python
from __future__ import print_function
import re
from jirautils import Jira, InvalidJira, logger, next_major_ver
import logging
import os
import argparse
from gitlab import first, find_repos

__name__ = 'check-msg'

# Argument Parser
#
parser = argparse.ArgumentParser()
parser.add_argument('-m', '--message', help='Commit Message', type=str)
parser.add_argument('-r', '--repo_path', help='gitlab repository', type=str, default=None)
parser.add_argument('-t', '--target_branch', help='target branch', type=str, default=None)
parser.add_argument('-v', '--verbose', help='increase output verbosity', action='count', default=0)

args = parser.parse_args()
# set logger verbosity
#
if args.verbose == 1:
    log_level = logging.WARNING
elif args.verbose == 2:
    log_level = logging.INFO
elif args.verbose == 3:
    log_level = logging.DEBUG
else:
    log_level = logging.WARNING


log = logging.getLogger(__name__)

# create console handler
ch = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)
log.setLevel(log_level)
logger.setLevel(log_level)
logger.addHandler(ch)

errors = []
jira = None

msg = args.message if args.message else ''
repo_path = args.repo_path if args.repo_path else os.getenv('CI_PROJECT_PATH')
target_branch = args.target_branch if args.target_branch else os.getenv('CI_MERGE_REQUEST_TARGET_BRANCH_NAME')
source_branch = os.getenv('CI_MERGE_REQUEST_SOURCE_BRANCH_NAME')

log.info('Checking message %r' % msg)
log.info('GitLab Project %r' % repo_path)
log.info('Source branch %r' % source_branch)
log.info('Target branch %r' % target_branch)

force = re.search(r'OOP', msg)
if force:
    log.info('Out of Process. Skipping validation')
    exit(0)

Jira.request_fields(
    'project, fixVersions, issuetype, components, customfield_13600, customfield_13601, customfield_13602, customfield_13901, subtasks, customfield_11201, Description, Status'
)

jira_match = re.match(r'[a-zA-Z]{2,10}-[0-9]{2,7}', msg)

if not jira_match:
    errors.append('Could not find Jira ticket in commit message')
else:
    try:
        jira = Jira(jira_match.group(0))
        log.info('Found Jira %s' % jira.key)
    except InvalidJira:
        errors.append('%s is not a valid Jira ticket' % jira_match.group(0))

if jira:

    if jira.project == 'GTODEVJAS'or 'GTODEVBOJ':

        repo = first(find_repos('path', repo_path))                
        if not repo:
            errors.append(jira.key + ": Not a valid repo " + repo_path )
        if repo and repo.component not in jira.components:
            errors.append(jira.key + ": component not added to JIRA ticket " + repo.component )
        
        #if not jira.RAG:
        #    if not repo:
        #        errors.append('%s: RAG Status cannot be empty' % jira.key )
        
        if not jira.Description:
            errors.append('%s: Description cannot be empty' % jira.key)
        else:
            exit
            
        if not jira.Status:
            errors.append('%s: status is not present' % jira.key)
        elif jira.status != 'IMPLEMENTING':
            exit
        else:   
            errors.append('%s: status is not in Implementing' % jira.key )
            


        if not jira.fixversions:
            errors.append('%s: FixVersion cannot be empty' % jira.key)
        else:
            if target_branch == 'tst-core':
                next_ver = next_major_ver()
                for f in jira.fixversions:
                    if f in next_ver:
                        break
                else:
                    errors.append('%s: FixVersion set to %r. Expecting %r' % (jira.key, ','.join(jira.fixversions), next_ver))

        if jira.type not in ['Bug', 'Story']:
            errors.append("%s: Issue type is %r. Expecting 'Bug' or 'Story'" % (jira.key, jira.type))
        #else:
            #if len(jira.subtasks) < 1:
               # errors.append('%s: There are no linked subtask type tickets' % jira.key)

             #this is a mandatory field - should we skip this check?
            #if not jira.product_capability:
                #errors.append('%s: Product Capability is not set' % jira.key)

           # if not jira.business_group:
                #errors.append('%s: Business Group is not set' % jira.key)

            #if not jira.transaction_group:
                #errors.append('%s: Transaction Group is not set' % jira.key)

            #if not jira.instrument_group:
               # errors.append('%s: Instrument Group is not set' % jira.key)

if len(errors) == 0:
    log.info('Validation SUCCESS')
    print('Validation SUCCESS')
    exit(0)
else:
    log.error('Validation FAILED')
    log.error('|'.join(errors))
    print('Validation FAILED')
    print('\n'.join(errors))
    exit(1)
