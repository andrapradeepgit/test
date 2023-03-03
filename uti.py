from __future__ import print_function
import requests
import sys
import logging
import re
import os

# from functools import lru_cache
import time
from datetime import datetime
from gitlab import _build_components
import config

JIRA_HOST = config.JIRA_HOST

TIMEOUT = 10

session = None
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class InvalidJira(Exception):
    """Raised when a key is not a valid Jira ticket"""

    pass


def timeit(method):
    """Timing decorator"""

    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()
        if 'log_time' in kw:
            name = kw.get('log_name', method.__name__.upper())
            kw['log_time'][name] = int((te - ts) * 1000)
        else:
            logger.debug('%r took %2.2f ms' % (method.__name__, (te - ts) * 1000))
        return result

    return timed


def setup_session():
    """Set up global session object"""
    global session
    session = requests.Session()
    session.auth = (username, password)
    # current_path = os.path.abspath(os.path.dirname(__file__))
    # session.verify = os.path.join(current_path, 'jiracert.pem')


def check_response(res):
    """Check api response and raise appropriate error"""
    if res.status_code == 200:
        return res

    elif res.status_code == 400:
        msg = res.text
        logger.error(msg)
        raise Exception(msg)

    elif res.status_code == 401:
        msg = 'Invalid Jira credentials'
        logger.error(msg)
        raise Exception(msg)

    elif res.status_code == 403:
        msg = 'CAPTCHA challenge triggered'
        logger.error(msg)
        raise Exception(msg)

    elif res.status_code == 404:
        msg = 'Jira ticket not found'
        logger.error(msg)
        raise InvalidJira(msg)

    else:
        logger.error('Unhandled error trying to fetch details')
        res.raise_for_status()


def get_jira_for_sr(sr):
    """Return Jira ticket matching SR number"""
    tickets = get_issues(
        "'Remedy Link' = 'http://10.158.0.236/DevWorkbench/#ajax/case.html?sr=%s' and type in ('Story',Bug)" % sr
    )
    if tickets and len(tickets) == 1:
        return tickets[0]
    elif tickets and len(tickets) > 1:
        raise Exception('Mutliple Jira tickets found for SR %s' % sr)
    else:
        raise Exception('Could not find Jira ticket for SR %s' % sr)


def get_issues(jql, max=200, suppress_logs=False):
    """Get a list of issues using JQL"""
    if not suppress_logs:
        logger.info('Fetching issues for JQL: %r' % jql)
    res = check_response(
        session.get(url=Jira.SEARCH_API, params={'jql': jql, 'fields': Jira._fields, 'maxResults': max}, timeout=TIMEOUT,)
    )
    tickets = []
    total = res.json().get('total', 0)
    if not suppress_logs:
        logger.info('Query matched %s tickets' % total)

    if total > 0:
        for i in res.json()['issues']:
            tickets.append(Jira(json=i))
        if total > max and not suppress_logs:
            logger.warning('Retrieving %s ticket(s) out of a possible %s. Increase max parameter to retrieve more' % (max, total))
        return tickets
    return None


def next_major_ver():
    """Get next Major FixVersion for GTODEVJAS project"""
    today = datetime.today().date()
    next_ver = []
    res = check_response(
        session.get(url=Jira.PROJECT_VERSION_API % 'GTODEVJAS', params={'orderBy': '-releaseDate', 'maxResults': 200}, timeout=TIMEOUT,)
    )
    fixversions = res.json()['values']

    for fv in fixversions:
        release_date = None
        start_date = None
        if fv.get('releaseDate') and fv.get('startDate'):
            # cutoff is a day before release date
            release_date = datetime.strptime(fv.get('releaseDate'), '%Y-%m-%d').date()
            start_date = datetime.strptime(fv.get('startDate'), '%Y-%m-%d').date()
            if release_date >= today and start_date <= today and fv.get('name').endswith('.0'):
                next_ver.append(fv.get('name'))
    if next_ver:
        logger.info("FixVersion(s) with a start date <= today() and release date > today(): '%r'" % next_ver)
    return next_ver


def latest_major_ver():
    """Get latest released major FixVersion for GTODEVJAS project"""
    res = check_response(
        session.get(url=Jira.PROJECT_VERSION_API % 'GTODEVJAS', params={'orderBy': '-releaseDate', 'maxResults': 200}, timeout=TIMEOUT,)
    )
    fixversions = res.json()['values']

    for fv in fixversions:
        if fv.get('released') and fv.get('name').endswith('.0'):
            logger.info('Latest released major version: %r' % fv.get('name'))
            return fv.get('name')
    return None


def create_fixversion(name, project='GTODEVJAS'):
    """Create new fixversion and do nothing if it already exists"""

    post = session.post(
        FixVersion.VERSION_API,
        data='{"name": "' + name + '", "project" : "' + project + '"}',
        headers={'Content-type': 'application/json'},
        timeout=TIMEOUT,
    )
    if post.status_code == 201:
        logger.info('Successfully created FixVersion %s' % name)
        return True
    else:
        if eval(post.text).get('errors') and eval(post.text).get('errors').get('name') in [
            'A version with this name already exists in this project.',
            "You can't add a version that's been archived. If you need to use that version, you must unarchive it first.",
        ]:
            logger.warn('FixVersion %s already exists' % name)
            return True
        else:
            logger.error('Failed to create FixVerion %s' % name)
            post.raise_for_status()
            return False


class Jira(object):
    """Jira ticket class"""

    ISSUE_API = JIRA_HOST + '/rest/api/2/issue/'
    SEARCH_API = JIRA_HOST + '/rest/api/2/search'
    PROJECT_VERSION_API = JIRA_HOST + '/rest/api/2/project/%s/version'
    TRANSITION_API = JIRA_HOST + '/rest/api/2/issue/%s/transitions'
    _fields = '*navigable'

    kanban_dict = {
        'Open': 'open',
        'Analyzing': 'open',
        'Backlog': 'open',
        'To Do': 'open',
        'Implementing': 'wip',
        'In Progress': 'wip',
        'In Review': 'wip',
        'Ready For Packaging': 'ready',
        'Validating on Staging': 'done',
        'Deploy to Prod': 'done',
        'Releasing': 'done',
        'Done': 'done',
    }

    def __init__(self, key='', json=''):
        self.json = json
        if not self.json:
            self.json = self.get_json(key)
        self.parse(self.json)

    def parse(self, json):
        """populate attributes from json"""
        self.id = self.json['id']
        self.key = self.json['key']
        self.fields = self.json['fields']
        self.status = self.fields.get('status').get('name') if self.fields.get('status') else None
        self.kanban = self.kanban_dict[self.status] if self.status in self.kanban_dict.keys() else None
        self.resolution = self.fields.get('resolution').get('name') if self.fields.get('resolution') else None
        self.summary = self.fields.get('summary')
        self.type = self.fields.get('issuetype').get('name') if self.fields.get('issuetype') else None
        self.project = self.fields.get('project').get('key') if self.fields.get('project') else None
        self.url = JIRA_HOST + '/browse/' + self.key
        self.labels = self.fields.get('labels') if self.fields.get('labels') else []
        self.subtasks = self.fields.get('subtasks') if self.fields.get('subtasks') else []

        self.fixversions = []
        if self.fields.get('fixVersions'):
            for f in self.fields.get('fixVersions'):
                self.fixversions.append(f.get('name'))

        self.sprints = []
        if self.fields.get('customfield_10005'):
            for f in self.fields.get('customfield_10005'):
                self.sprints.append(re.search('name=(.*),startDate|$', f).group(1))

        self.components = []
        self.build_components = []
        if self.fields.get('components'):
            for f in self.fields.get('components'):
                self.components.append(f.get('name'))
                if f.get('name') in _build_components:
                    self.build_components.append(f.get('name'))

        self.pods = []
        if self.fields.get('customfield_13302'):
            for f in self.fields.get('customfield_13302'):
                self.pods.append(f.get('value'))
                
        
        #self.RAG = self.fields.get('customfield_11201').get('value') if self.fields.get('customfield_11201') else None
        self.Description = self.fields.get('Description').get('name') if self.fields.get('Description') else None
        self.Status = self.fields.get('Status').get('value') if self.fields.get('Status') else None

        self.product_capability = self.fields.get('customfield_13901').get('value') if self.fields.get('customfield_13901') else None
        self.client = self.fields.get('customfield_12082').get('value') if self.fields.get('customfield_12082') else None

        self.business_group = []
        if self.fields.get('customfield_13600'):
            for f in self.fields.get('customfield_13600'):
                self.business_group.append(f.get('value'))

        self.transaction_group = []
        if self.fields.get('customfield_13601'):
            for f in self.fields.get('customfield_13601'):
                self.transaction_group.append(f.get('value'))

        self.instrument_group = []
        if self.fields.get('customfield_13602'):
            for f in self.fields.get('customfield_13602'):
                self.instrument_group.append(f.get('value'))

        sr = self.fields.get('customfield_12077') if self.fields.get('customfield_12077') else ''
        self.sr = re.search('sr=([0-9]*)$', sr).group(1) if re.search('sr=([0-9]*)$', sr) else None
        self.sr_url = 'http://10.158.0.236/DevWorkbench/#ajax/case.html?sr=%s' % self.sr if self.sr else None

    def __repr__(self):
        return 'Jira(%r)' % self.key

    @classmethod
    def request_fields(cls, fields):
        """Override default jira rest api fields"""
        if isinstance(fields, list):
            cls._fields = ','.join(fields)
        elif isinstance(fields, str):
            cls._fields = fields
        logger.debug('Set request fields to: ' + cls._fields)

    @timeit
    # Basic caching to limit expensive calls to the rest api
    # TODO not compatible with python 2.7
    # @lru_cache
    def get_json(self, key):
        """Get the json represenation of a jira ticket"""
        logger.debug('Fetching details from Jira for: ' + key)
        res = check_response(session.get(self.ISSUE_API + key, params={'fields': self._fields}, timeout=TIMEOUT))
        return res.json()

    def set_field(self, field, value):
        """Set Jira field to a value"""
        put = session.put(
            self.ISSUE_API + self.key,
            data='{"fields": {"' + field + '": "' + value + '"}}',
            headers={'Content-type': 'application/json'},
            timeout=TIMEOUT,
        )
        if put.status_code == 204:
            logger.info('Successfully set %s field %r to %r' % (self.key, field, value))
            return True
        else:
            logger.error('Failed to set %s field %r to %r' % (self.key, field, value))
            put.raise_for_status()
            return False

    def add_component(self, component):
        """Add another Component"""
        put = session.put(
            self.ISSUE_API + self.key,
            data='{"update": {"components": [{"add": {"name": "' + component + '"}}]}}',
            headers={'Content-type': 'application/json'},
            timeout=TIMEOUT,
        )
        if put.status_code == 204:
            logger.info('Successfully added component %r to %s' % (component, self.key))
            return True
        else:
            logger.error('Failed to add component %r to %s' % (component, self.key))
            put.raise_for_status()
            return False

    def update_field(self, operation, field, value):
        """Add or remove a value to/from a mutli select field"""
        if operation not in ['add', 'remove']:
            raise Exception('Operation %r not supported' % operation)
        put = session.put(
            self.ISSUE_API + self.key,
            data='{"update": {"' + field + '": [{"' + operation + '": {"name": "' + value + '"}}]}}',
            headers={'Content-type': 'application/json'},
            timeout=TIMEOUT,
        )
        verb = 'added' if operation == 'add' else 'removed'
        preposition = 'to' if operation == 'add' else 'from'
        if put.status_code == 204:
            logger.info('%s: Successfully %s %r %s %s' % (self.key, verb, value, preposition, field))
            return True
        else:
            logger.error('%s: Failed to %s %r %s %s' % (self.key, operation, value, preposition, field))
            put.raise_for_status()
            return False

    def transition_id(self, name):
        """Return transition id for transition name"""
        res = session.get(self.TRANSITION_API % self.key, timeout=TIMEOUT)
        transitions = res.json().get('transitions')
        for t in transitions:
            if t.get('to').get('name') == name:
                return t.get('id')
        return None

    def transition_to(self, name):
        """Transition ticket to named status"""
        id = self.transition_id(name)
        if not id:
            logger.error('%r is not a valid transition for %s' % (name, self.key))
            return False
        post = session.post(
            self.TRANSITION_API % self.key,
            data='{"transition": {"id": "' + id + '"}}',
            headers={'Content-type': 'application/json'},
            timeout=TIMEOUT,
        )
        if post.status_code == 204:
            logger.info('Successfully transitioned %s to %r' % (self.key, name))
            return True
        else:
            logger.error('Failed to transition %s to %r' % (self.key, name))
            print(post.text)
            return False


class FixVersion(object):
    """A collection of attributes and Jira tickets for an IPE FixVersion"""

    VERSION_API = JIRA_HOST + '/rest/api/2/version/'

    def __init__(self, name):
        self.name = name
        self.id = self.get_id()
        self.suppress_logs = False
        self.refresh()
        self.suppress_logs = True

    def refresh(self):
        """Refresh (or initialise) object attributes"""
        fv = check_response(session.get(url=self.VERSION_API + self.id, timeout=TIMEOUT)).json()
        self.release_date = fv.get('releaseDate')
        self.start_date = fv.get('startDate')
        self.archived = fv.get('archived')
        self.released = fv.get('released')

        self.tickets = self.get_tickets()
        self.code_tickets = self.get_code_tickets()

    def get_id(self):
        """Get version id given a fixversion name"""
        ticket = get_issues('fixversion = %r and project = IPE' % self.name, max=1, suppress_logs=True)[0]
        for fv in ticket.fields.get('fixVersions'):
            if fv.get('name') == self.name:
                return fv.get('id')
        return None

    def get_tickets(self):
        """Return IPE tickets in this FixVersion"""
        return get_issues('fixversion in (%r) and project = IPE' % self.name, suppress_logs=self.suppress_logs)

    def get_code_tickets(self):
        """Return IPE code tickets in this FixVersion"""
        return [t for t in self.tickets if t.type in ('Bug', 'Story') and 'NO_DEV_CHANGES' not in t.labels]

    def release(self):
        """Set Released attribute for FixVersion to True using today's date"""
        today = datetime.today().date()
        put = session.put(
            self.VERSION_API + self.id,
            data='{"released": "true", "releaseDate": "' + str(today) + '"}',
            headers={'Content-type': 'application/json'},
            timeout=TIMEOUT,
        )
        if put.status_code == 200:
            logger.info('Successfully marked FixVersion %s as Released' % self.name)
            return True
        else:
            logger.error('Failed to mark FixVerion %s as Released' % self.name)
            put.raise_for_status()
            return False

    def archive(self):
        """Set Archived attribute for FixVersion to True"""
        put = session.put(
            self.VERSION_API + self.id, data='{"archived": "true"}', headers={'Content-type': 'application/json'}, timeout=TIMEOUT,
        )
        if put.status_code == 200:
            logger.info('Successfully marked FixVersion %s as Archived' % self.name)
            return True
        else:
            logger.error('Failed to mark FixVerion %s as Archived' % self.name)
            put.raise_for_status()
            return False


# Retrieve from environment vars and
# fall back to jira_creds.py file if not found
username = os.getenv('JIRA_USERNAME')
password = os.getenv('JIRA_PASSWORD')

if not username or not password:
    logger.debug('Env vars JIRA_USERNAME or JIRA_PASSWORD are undefined')
    try:
        from jira_creds import username, password

        _ = username
        _ = password
    except NameError:
        sys.exit('Error: Could not load credentials')
    except ImportError:
        sys.exit('Error: Could not import jira_creds.py')

setup_session()
