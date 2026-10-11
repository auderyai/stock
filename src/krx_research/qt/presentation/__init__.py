"""Presentation package for the PySide6 application.

Keep package initialization side-effect free.  Import concrete presenters and
policies from their modules so lightweight, Qt-free presentation helpers can be
used in tests without importing the Qt runtime.
"""

__all__: list[str] = []
