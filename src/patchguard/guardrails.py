from pathlib import Path

class PathGuard:
  """Validate file paths before allowing repository access."""

  def __init__(self,repo_root:str):
    self.repo_root = Path(repo_root).resolve()

  def validate(self, path:str) -> Path:
    """Return a safe absolute path or reject the request"""
    candidate = Path(path)

    # Resolve relative path from the repository
    if not candidate.is_absolute():
      candidate = self.repo_root / candidate

    # Resolve '..' and existing symlinks.
    resolved = candidate.resolve()

    # Reject paths that escape the repository.
    if not resolved.is_relative_to(self.repo_root):  # checks whether one path is lexically contained under another path.
      raise ValueError("Access denied: path is outside the repository")

    return resolved

