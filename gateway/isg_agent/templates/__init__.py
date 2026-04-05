"""Template system for ISG Agent 1.

Provides industry/purpose templates that define how an agent behaves
for a given business vertical or personal use-case.  Templates are
stored as JSON configuration in the database — not as separate code files.

Public surface
--------------
- :class:`TemplateRecord`    — frozen dataclass mirroring the ``agent_templates`` table
- :class:`TemplateRegistry`  — async CRUD + seed for the ``agent_templates`` table
- :class:`PromptBuilder`     — builds final system prompts from template + agent context
"""

from isg_agent.templates.template_registry import TemplateRecord, TemplateRegistry
from isg_agent.templates.prompt_builder import PromptBuilder

__all__ = [
    "TemplateRecord",
    "TemplateRegistry",
    "PromptBuilder",
]
