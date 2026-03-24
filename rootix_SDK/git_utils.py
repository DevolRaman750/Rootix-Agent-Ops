import subprocess
from functools import lru_cache

@lru_cache(maxsize=1)
def __get_git_context():
    """Extracts git information to bind to spans."""
    try:
        git_ref = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        
        git_repo = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"], 
            stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()
        
        return git_ref, git_repo
    except Exception:
        return None, None

def get_git_ref():
    return __get_git_context()[0]

def get_git_repo():
    return __get_git_context()[1]
