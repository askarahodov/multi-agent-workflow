"""Platform-owned orchestration server with durable execution and task lifecycle.

The orchestration engine owns every state transition in the platform. Agents
interact only through the public REST API: they register, claim tasks, start
attempts and submit results. They can NEVER self-declare completion — the
engine transitions a task to ``completed`` only after contract verification
passes, and every transition is durably recorded in the saga journal so that
confirmed results survive server restarts while incomplete work is recovered.
"""

__version__ = "0.1.0"
