import logging
import argparse
import requests

PRD_HOST = 'https://git.devops.bfsaws.net/api/v4'
PRD_API_TOKEN = 'zQ2dseqsBmx_CmM7HjBi'
BRANCHES_API = PRD_HOST + '/projects/%s/repository/branches/%s'

MAPPING = [
    ('APAC/TokyoAdapters', 'TokyoAdapters', 3077),
    ('APAC/BPRIOR', 'BPRIOR', 3078),
    ('APAC/DPMTE', 'DPMTE', 3076),
    ('APAC/jpsgw', 'jpsgw', 5444),
    ('APAC/jpsgw_ftl_generator', 'jpsgw_ftl_generator', 5445),
    ('APAC/ACMTE', 'ACM_TE', 3080),
    ('APAC/dpm-tools', 'dpm-tools', 3077),
    ('APAC/BOJ_BRPIOR', 'BOJ_BPRIOR', 3106),
    ('APAC/BOJGW', 'BOJGW',3126),
    ('APAC/BOJGW_FTL_GENERATOR','BOJGW_FTL_GENERATOR',21782),
    ('APAC/BOJ_REGRESSION','BOJ_REGRESSION',11494),
    ('APAC/BOJ_TE','BOJ_TE',3086),
    ('APAC/boj-tools','BOJTOOLS',11489)
]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_session = None


class GitRepo(object):
    def __init__(self, path='', component='', id=''):
        self.path = path
        self.component = component
        self.id = id

        if self.component in ['ACMTE', 'DPMTE', 'jpsgw','dpm-tools','BOJTE','BOJGW','boj-tools']:
        #if self.component in ['PP', 'TE', 'CCPNE']:
            branch = 'feature/release_main/%s'
        else:
            branch = 'feature/%s'

        self.branch = branch

    def __repr__(self):
        return 'GitRepo(%r, %r, %r, %r)' % (self.path, self.component, self.id, self.branch)


_repo_list = [GitRepo(*r) for r in MAPPING]

def find_repos(attribute, value):
    """Lookup Git Repo by attribute"""
    g = GitRepo()
    valid_attributes = list(g.__dict__.keys())
    if attribute in valid_attributes:
        # TODO Ugly Fix properly
        if attribute == 'path':
            return (repo for repo in _repo_list if value in getattr(repo, attribute))
        else:
            return (repo for repo in _repo_list if getattr(repo, attribute) == value)
    else:
        raise AttributeError('%r is not an attribute of the %r class' % (attribute, g.__class__.__name__))


def first(iterable, default=None):
    """Helper function that returns first item in an iterable"""
    for item in iterable:
        return item
    return default


def list_components():
    """Return list of Jira Components valid for builds"""
    components = list(set([repo.component for repo in _repo_list]))
    components.sort()
    return components


_build_components = list_components()


def _setup_session():
    """Set up session object for quering gitlab api"""
    global _session
    _session = requests.Session()
    _session.headers.update({'PRIVATE-TOKEN': PRD_API_TOKEN})
    _session.trust_env = False  # bypass windows proxy


def check_project_branch(component, ticket):
    """Check whether a branch exists for a ticket in the repositories associated with a component"""
    if not _session:
        _setup_session()

    branch = ''
    for repo in find_repos('component', component):
        branch = repo.branch % ticket
        logger.info('Checking whether branch %s exists in project %s for component %s' % (branch, repo.id, component))
        encoded_path = requests.utils.quote(branch, '')  # gitlab API expects url encoded / for the branch path
        res = _session.get(BRANCHES_API % (repo.id, encoded_path))
        if res.ok:
            logger.debug('Found branch %r in repo %r for component %s' % (branch, repo.path, component))
            return branch

    logger.warning('Could not find branch %r in the repositories for component %s' % (branch, component))
    return None


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Return project id for selected component')
    parser.add_argument('-c', '--component', help='Component', type=str)
    parser.add_argument('-s', '--sub_component', help='PP Sub Component', type=str)
    args = parser.parse_args()

    repo = None

    
    
    if args.component:
        print("args.component ", args.component)
        repo = first(find_repos('component', args.component))
    elif args.sub_component:
        print("args.sub_component ", args.sub_component)
        repo = first(find_repos('path', args.sub_component))

    if repo:
        print(repo.id)
    else:
        exit(1)
